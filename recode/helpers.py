import types
import copy_reg
import sys
import os

def _unpickle_method(func_name, func_self, cls):
    for base in cls.mro():
        try:
            func = base.__dict__[func_name]
        except KeyError:
            continue
        else:
            break
    return func.__get__(func_self, base)

def _pickle_method(method):
    func_name = method.__func__.__name__
    func_self = method.__self__
    cls = method.im_class
    if func_name.startswith('__') and not func_name.endswith('__'):
        cls_name = cls.__name__.lstrip('_')
        if cls_name:
            func_name = '_' + cls_name + func_name
    return _unpickle_method, (func_name, func_self, cls)

copy_reg.pickle(types.MethodType, _pickle_method, _unpickle_method)

def _get_numthreads():
    # not using multiprocessing.cpu_count() as it does not account well for LXC containers constrained by CPU cores
    try:
        return open('/proc/cpuinfo').read().count('vendor_id')
    except IOError:
        return 4
NUM_THREADS = _get_numthreads()

if sys.platform == 'win32':
    def which(prog, env_name=None):
        ''' Stub for testing reasons '''
        return prog
else:
    def which(prog, env_name=None, _cache={}):
        try:
            result = _cache[prog]
        except KeyError:
            pass
        else:
            if result is None:
                raise RuntimeError('"%s" not found in PATH' % prog)
            return result

        if env_name is not None:
            try:
                path = os.environ[env_name]
            except KeyError:
                pass
            else:
                path = os.path.abspath(path)
                if os.access(path, os.X_OK):
                    _cache[prog] = path
                    return path

        for dname in os.environ['PATH'].split(os.pathsep):
            for ext in ('', '.exe', '.cmd', '.bat'):
                path = os.path.join(dname, prog) + ext
                if os.access(path, os.X_OK):
                    _cache[prog] = path
                    return path

        _cache[prog] = None
        raise RuntimeError('"%s" not found in PATH' % prog)

def _stop(cond):
    if cond:
        return True
    raise StopIteration

def common_tail(sa, sb):
    return ''.join(reversed(tuple(a for a,b in zip(reversed(sa), reversed(sb)) if _stop(a==b))))

def get_suffix(lst):
    suffix = reduce(common_tail, (fname for (fname, _) in lst), lst[0][0])
    return suffix
