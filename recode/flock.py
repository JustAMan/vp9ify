import sys
import os
import sys
import logging

from .helpers import open_with_dir

if sys.platform == 'win32':
    logging.warning(('[%s] No locking on Windows, '
            'for developing only, be CAREFUL!\n') % os.path.basename(__file__))
            
    class FLock:
        def __init__(self, path):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a, **kw):
            pass
else:
    import fcntl
    class FLock:
        def __init__(self, path):
            self.path = os.path.abspath(path)
            self.handle = None
        def __enter__(self):
            while True:
                handle = open_with_dir(self.path, 'w')
                try:
                    logging.debug('Trying to grab lock "%s"' % self.path)
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                    # now check that file wasn't deleted while we were waiting for the lock
                    link = os.readlink('/proc/self/fd/%d' % handle.fileno())
                    if os.path.isabs(link) and os.path.abspath(link) == self.path:
                        # yay, we succeeded
                        logging.debug('Grabbed lock "%s"' % self.path)
                        break
                    else:
                        logging.debug('File "%s" was deleted while we were waiting to lock it!' % self.path)
                except:
                    handle.close()
                    raise
            self.handle = handle
            return self
        def __exit__(self, *a, **kw):
            os.unlink(self.path)
            logging.debug('Letting go of lock "%s"' % self.path)
            self.handle.close()
