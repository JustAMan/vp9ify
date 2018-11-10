import os
try:
    import cPickle as pickle
except ImportError:
    import pickle

import flock

class LockedState(object):
    def __init__(self, state_path):
        dirname, fname = os.path.split(state_path)
        self.lock = flock.FLock('%s%s.%s.lock' % (dirname, os.sep, fname))
        self.path = state_path

    def __enter__(self):
        self.lock.__enter__()
        return self
    
    def __exit__(self, *a, **kw):
        return self.lock.__exit__(*a, **kw)

    def read(self):
        with open(self.path, 'rb') as inp:
            return pickle.loads(inp.read())

    def write(self, tasklists):
        with open(self.path, 'wb') as out:
            out.write(pickle.dumps(tasklists))

    def remove(self):
        os.unlink(self.path)
