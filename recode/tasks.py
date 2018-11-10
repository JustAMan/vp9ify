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

from .locked_state import LockedState

class Resource:
    CPU = 'cpu'
    IO = 'i/o'
    CPU_MAIN = CPU + '-main'
    CPU_OTHER = CPU + '-other'
    IO_MAIN = IO + '-main'
    IO_OTHER = IO + '-other'

ResourceLimit = collections.namedtuple('ResourceLimit', 'resource limit')

class IParallelTask(object):
    def get_limit(self, remaining_tasks, running_tasks):
        raise NotImplementedError()
    def __call__(self):
        raise NotImplementedError()
    def __str__(self):
        raise NotImplementedError()
    def can_run(self, batch_tasks):
        raise NotImplementedError()
    def scriptize(self):
        raise NotImplementedError()
    def __eq__(self, other):
        raise NotImplementedError()
    def __ne__(self, other):
        return not (self == other)

class Executor:
    def __init__(self, state, scriptize=False):
        self.state = state
        with self.state:
            self.tasklists = self.state.read()

        logging.info('Amount of batches: %d' % len(self.tasklists))
        self.unfinished = copy.deepcopy(self.tasklists)
        self.lock = threading.RLock()
        self.running = []
        self.resources = collections.defaultdict(int)
        self.scriptize = scriptize

    def __pop_next_task(self):
        with self.lock:
            candidates = []
            all_tasks = []
            for list_idx, tasklist in enumerate(self.tasklists):
                not_done = self.unfinished[list_idx]
                for task_idx, task in enumerate(tasklist):
                    if task and task.can_run(not_done):
                        candidates.append((list_idx, task_idx, task))
                        all_tasks.append(task)

            for list_idx, task_idx, task in candidates:
                limit = task.get_limit(all_tasks, self.running)
                if self.resources[limit.resource] < limit.limit:
                    self.resources[limit.resource] += 1
                    self.tasklists[list_idx][task_idx] = None
                    self.running.append(task)
                    logging.info('Starting %s' % task)
                    return list_idx, task_idx, task, limit
        return None, None, None, None

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
                task.scriptize()
                if not self.scriptize:
                    task()
            except:
                logging.exception('Error in %s' % task)
            else:
                logging.info('Completed %s' % task)
                self.__mark_finished(list_idx, task_idx, task)
            finally:
                with self.lock:
                    self.resources[limit.resource] -= 1
                    self.running.remove(task)
        except:
            logging.exception('Unhandled error while running task %s' % task)
            raise
    
    def _execute(self):
        threads = []
        while True:
            with self.lock:
                remaining = []
                for tasklist in self.tasklists:
                    remaining.extend(task for task in tasklist if task)
                if not remaining:
                    break

                list_idx, task_idx, task, limit = self.__pop_next_task()
                if task:
                    th = threading.Thread(target=self.__run_task, args=(list_idx, task_idx, task, limit))
                    th.start()
                    threads.append(th)
                elif not self.running:
                    logging.warning('Exiting due to empty running queue while some tasks still remain, this is probably a bug')
                    break
            time.sleep(0.2)
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
