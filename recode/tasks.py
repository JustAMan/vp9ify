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

class Resource:
    CPU = 'cpu'
    IO = 'i/o'
ResourceLimit = collections.namedtuple('ResourceLimit', 'resource limit')

class IParallelTask(object):
    limit = None
    def __call__(self):
        raise NotImplementedError()
    def __str__(self):
        raise NotImplementedError()
    def can_run(self, all_tasks):
        raise NotImplementedError()
    def scriptize(self):
        raise NotImplementedError()
    def __eq__(self, other):
        raise NotImplementedError()
    def __ne__(self, other):
        return not (self == other)

class Executor:
    def __init__(self, resume_file, scriptize=False):
        self.resume_file = resume_file
        with open(self.resume_file, 'rb') as inp:
            self.tasklists = pickle.loads(inp.read())

        logging.info('Amount of batches: %d' % len(self.tasklists))
        self.unfinished = copy.deepcopy(self.tasklists)
        self.lock = threading.RLock()
        self.running = []
        self.resources = collections.defaultdict(int)
        self.scriptize = scriptize

    def __pop_next_task(self):
        with self.lock:
            for list_idx, tasklist in enumerate(self.tasklists):
                not_done = self.unfinished[list_idx]
                for task_idx, task in enumerate(tasklist):
                    if task and task.can_run(not_done):
                        already_running = self.resources[task.limit.resource]
                        if already_running < task.limit.limit:
                            self.resources[task.limit.resource] += 1
                            self.tasklists[list_idx][task_idx] = None
                            self.running.append(task)
                            logging.info('Starting %s' % task)
                            return list_idx, task_idx, task
        return None, None, None

    def __mark_finished(self, list_idx, task_idx, task):
        with self.lock:
            assert self.unfinished[list_idx][task_idx] == task
            self.unfinished[list_idx][task_idx] = None
            with open(self.resume_file, 'wb') as out:
                out.write(pickle.dumps(self.unfinished))

    def __run_task(self, list_idx, task_idx, task):
        try:
            try:
                task.scriptize() if self.scriptize else task()
            except:
                logging.exception('Error in %s' % task)
            else:
                logging.info('Completed %s' % task)
                self.__mark_finished(list_idx, task_idx, task)
            finally:
                with self.lock:
                    self.resources[task.limit.resource] -= 1
                    self.running.remove(task)
        except:
            logging.exception('Unhandled error while running task %s' % task)
    
    def execute(self):
        threads = []
        while True:
            with self.lock:
                remaining = []
                for tasklist in self.tasklists:
                    remaining.extend(task for task in tasklist if task)
                if not remaining:
                    break

                list_idx, task_idx, task = self.__pop_next_task()
                if task:
                    th = threading.Thread(target=self.__run_task, args=(list_idx, task_idx, task))
                    th.start()
                    threads.append(th)
                elif not self.running:
                    logging.warning('Exiting due to empty running queue while some tasks still remain, this is probably a bug')
                    break
            time.sleep(0.2)
        for th in threads:
            th.join()
        os.unlink(self.resume_file)
