import collections
import copy
import threading
import os
import time
try:
    import cPickle as pickle
except ImportError:
    import pickle

from .helpers import NUM_THREADS

ParallelTask = collections.namedtuple('ParallelTask', 'func args kw cost describe')

class Executor:
    def __init__(self, resume_file):
        self.resume_file = resume_file
        with open(self.resume_file, 'rb') as inp:
            self.tasklists = pickle.loads(inp.read())

        self.unfinished = copy.deepcopy(self.tasklists)
        self.running = set()
        self.power = NUM_THREADS
        self.lock = threading.RLock()

    def __pop_next_task(self):
        with self.lock:
            candidates = [(-tasks[0].cost, idx, tasks[0]) for (idx, tasks) in enumerate(self.tasklists) if tasks and idx not in self.running and tasks[0].cost <= self.power]
            if candidates:
                _, idx, task = min(candidates)
                self.power -= task.cost
                self.tasklists[idx].pop(0)
                self.running.add(idx)
                return idx, task
        return None, None

    def __mark_finished(self, idx, task):
        with self.lock:
            assert self.unfinished[idx][0] == task
            self.unfinished[idx].pop(0)
            with open(self.resume_file, 'wb') as out:
                out.write(pickle.dumps(self.unfinished))

    def __run_task(self, idx, task):
        descr = str(task) if not task.describe else task.describe(task)
        print 'Running %s' % descr
        try:
            task.func(*task.args, **task.kw)
        except:
            print 'Error in %s' % descr
            raise
        else:
            print 'Stopped %s' % descr
            self.__mark_finished(idx, task)
        finally:
            with self.lock:
                self.power += task.cost
                self.running.remove(idx)
    
    def execute(self):
        threads = []
        while True:
            with self.lock:
                if not any(self.tasklists):
                    break
                idx, task = self.__pop_next_task()
                if task:
                    th = threading.Thread(target=self.__run_task, args=(idx, task))
                    th.start()
                    threads.append(th)
            time.sleep(0.2)
        for th in threads:
            th.join()
        os.unlink(self.resume_file)
