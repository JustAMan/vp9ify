import collections
import copy
import threading
import os
import time
try:
    import cPickle as pickle
except ImportError:
    import pickle
import logging
import typing

from .locked_state import LockedState

class ResourceKind:
    CPU = 'cpu'
    IO = 'i/o'

Resource = collections.namedtuple('Resource', 'kind priority')

class IParallelTask(object):
    resource = None
    do_script = True
    def get_limit(self, candidate_tasks, running_tasks) -> int:
        raise NotImplementedError()
    def __call__(self):
        raise NotImplementedError()
    def __str__(self):
        raise NotImplementedError()
    def can_run(self, batch_tasks) -> bool:
        raise NotImplementedError()
    def scriptize(self):
        raise NotImplementedError()
    def __eq__(self, other):
        raise NotImplementedError()
    def __ne__(self, other):
        return not (self == other)

class Executor:
    UPDATE_DELAY = 20
    def __init__(self, state, scriptize=False):
        self.state = state
        with self.state:
            self.tasklists = self.state.read()
            self.state_updated = time.time()

        nonempty = sum(1 if any(tl) else 0 for tl in self.tasklists)
        logging.info('Amount of batches: %d' % nonempty)
        self.unfinished = copy.deepcopy(self.tasklists)
        self.lock = threading.RLock()
        self.running = []
        self.scriptize = scriptize

    def __pop_next_task(self):
        with self.lock:
            candidates = []
            all_tasks = []
            for list_idx, tasklist in enumerate(self.tasklists):
                not_done = self.unfinished[list_idx]
                for task_idx, task in enumerate(tasklist):
                    if task and task.can_run(not_done):
                        candidates.append((task.resource, list_idx, task_idx, task))
                        all_tasks.append(task)
            candidates.sort()

            candidates_limit = []
            resource_slots = collections.defaultdict(lambda: collections.defaultdict(int))
            for resource, list_idx, task_idx, task in candidates:
                limit = task.get_limit(all_tasks, self.running)
                candidates_limit.append((limit, resource, list_idx, task_idx, task))
                resource_slots[resource.kind][resource.priority] = max(resource_slots[resource.kind][resource.priority], limit)

            resource_uses = collections.defaultdict(lambda: collections.defaultdict(int))
            for task in self.running:
                resource_uses[task.resource.kind][task.resource.priority] += 1
            
            found_resource = None
            for resource_kind, slots in sorted(resource_slots.items()):
                for running_prio, running_users in resource_uses[resource_kind].items():
                    if running_prio not in slots:
                        slots[running_prio] = running_users
                for resource_priority in sorted(slots.keys()):
                    # check if taking one more task of given priority fits
                    potential = copy.deepcopy(resource_uses[resource_kind])
                    potential[resource_priority] += 1
                    for priority in (set(potential.keys()) | set(slots.keys())):
                        total = 0
                        for potential_prio, users in potential.items():
                            if potential_prio <= priority:
                                total += users
                        if total > slots[priority]:
                            # violates one of slot constraints :(
                            break
                    else:
                        # all priorities are fine, we found what we sought!
                        found_resource = Resource(kind=resource_kind, priority=resource_priority)
                        break
                if found_resource is not None:
                    break

            if found_resource is not None:
                for limit, resource, list_idx, task_idx, task in candidates_limit:
                    if resource == found_resource:
                        self.tasklists[list_idx][task_idx] = None
                        self.running.append(task)
                        dbg_items = []
                        for name, slots in sorted(resource_uses.items()):
                            for priority, users in sorted(slots.items()):
                                dbg_items.append('%s-%s=%s' % (name, priority, users))
                        logging.debug('Pre-task resource usage: %s' % ('|'.join(dbg_items)))
                        logging.info('Starting %s' % task)
                        logging.debug('Task resource: kind=%s, prio=%s, limit=%s' % (resource.kind, resource.priority, limit))
                        return list_idx, task_idx, task, limit
        return None, None, None, None

    def __update_state(self):
        if self.state_updated + self.UPDATE_DELAY > time.time():
            # do not update too frequently
            return
        with self.lock, self.state:
            self.state_updated = time.time()
            tasklists = self.state.read()
            logging.debug('Refreshing executor state, read %d batches' % len(tasklists))
            new_tasks = tasklists[len(self.unfinished):]
            if new_tasks:
                logging.info('Adding %d more batches' % len(new_tasks))
                self.tasklists.extend(new_tasks)
                self.unfinished.extend(copy.deepcopy(new_tasks))

    def __mark_finished(self, list_idx, task_idx, task):
        with self.lock:
            assert self.unfinished[list_idx][task_idx] == task
            self.unfinished[list_idx][task_idx] = None
            if not self.scriptize:
                with self.state:
                    tasklists = self.state.read()
                    for li, row in enumerate(self.unfinished):
                        for ti, task in enumerate(row):
                            if task is None:
                                tasklists[li][ti] = None
                    # read new tasklists
                    self.tasklists.extend(tasklists[len(self.unfinished):])
                    # now update unfinished stuff
                    self.unfinished = tasklists
                    self.state.write(self.unfinished)

    def __run_task(self, list_idx, task_idx, task, limit):
        try:
            try:
                if not self.scriptize:
                    task()
                if task.do_script:
                    task.scriptize()
            except:
                logging.exception('Error in %s' % task)
            else:
                logging.info('Completed %s' % task)
                self.__mark_finished(list_idx, task_idx, task)
            finally:
                with self.lock:
                    self.running.remove(task)
        except:
            logging.exception('Unhandled error while running task %s' % task)
            raise
    
    def _execute(self):
        threads = []
        while True:
            with self.lock:
                remaining = sum(1 if any(tl) else 0 for tl in self.tasklists)
                if remaining == 0:
                    break

                list_idx, task_idx, task, limit = self.__pop_next_task()
                if task:
                    th = threading.Thread(target=self.__run_task, args=(list_idx, task_idx, task, limit))
                    th.start()
                    threads.append(th)
                elif not self.running:
                    logging.warning('Exiting due to empty running queue while some tasks still remain, this is probably a bug')
                    break
            self.__update_state()
            time.sleep(0.5)
        for th in threads:
            th.join()
        if not self.scriptize and not self.unfinished:
            with self.state:
                # check that state is really empty before removing it
                tasklists = self.state.read()
                remaining = []
                for tl in tasklists:
                    remaining.extend(t for t in tl if t)
                if not remaining:
                    self.state.remove()

    def execute(self):
        try:
            return self._execute()
        except:
            logging.exception('Unhandled error while executing tasks')
            raise
