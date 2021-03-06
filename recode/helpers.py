import types
import copyreg
from functools import reduce
import sys
import os
import errno
import typing

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

copyreg.pickle(types.MethodType, _pickle_method, _unpickle_method)

def _get_numthreads() -> int:
    # not using multiprocessing.cpu_count() as it does not account well for LXC containers constrained by CPU cores
    try:
        return open('/proc/cpuinfo').read().count('vendor_id')
    except IOError:
        return 4
NUM_THREADS = _get_numthreads()

if sys.platform == 'win32':
    def which(prog, env_name=None, optional=False) -> str:
        ''' Stub for testing reasons '''
        return None if optional else prog
else:
    _which_cache = {}
    def which(prog: str, env_name: str=None, optional: bool=False) -> str:
        try:
            result = _which_cache[prog]
        except KeyError:
            pass
        else:
            if result is None and not optional:
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
                    _which_cache[prog] = path
                    return path

        for dname in os.environ['PATH'].split(os.pathsep):
            for ext in ('', '.exe', '.cmd', '.bat'):
                path = os.path.join(dname, prog) + ext
                if os.access(path, os.X_OK):
                    _which_cache[prog] = path
                    return path

        _which_cache[prog] = None
        if not optional:
            raise RuntimeError('"%s" not found in PATH' % prog)

def _stop(cond):
    if cond:
        return True
    raise StopIteration

def common_tail(sa: typing.Sequence[str], sb: typing.Sequence[str]) -> str:
    return ''.join(reversed(tuple(a for a,b in zip(reversed(sa), reversed(sb)) if _stop(a==b))))

def get_suffix(lst):
    suffix = reduce(common_tail, (fname for (fname, _) in lst), lst[0][0])
    return suffix

def ensuredir(path: str):
    try:
        os.makedirs(path)
    except OSError as err:
        if err.errno != errno.EEXIST:
            raise

def open_with_dir(path: str, *arg, **kw):
    ensuredir(os.path.dirname(path))
    return open(path, *arg, **kw)

def input_numbers(prompt: str, minval: int, maxval: int, accept_empty :bool=True) -> typing.List[int]:
    if accept_empty:
        template = '%s (from %d to %d, comma separated, hyphen denotes range, empty means "all"): '
    else:
        template = '%s (from %d to %d, comma separated, hyphen denotes range): '
    while True:
        text = input(template % (prompt, minval, maxval))
        if not text.strip() and accept_empty:
            return list(range(minval, maxval + 1))
        result = []
        try:
            for piece in text.strip().split(','):
                if '-' not in piece:
                    result.append(int(piece.strip()))
                else:
                    left, right = [int(x.strip()) for x in piece.split('-')]
                    result.extend(range(left, right + 1))
            if min(result) < minval:
                print('Minimum should be at least %d' % minval)
                continue
            elif max(result) > maxval:
                print('Maximum should be at least %d' % minval)
                continue
        except ValueError:
            print('Cannot parse numbers, try again')
            continue
        return result

def confirm_yesno(prompt: str, default: bool=True) -> bool:
    prompt = '%s [%s]: ' % (prompt, 'Y/n' if default else 'y/N')
    while True:
        text = input(prompt).strip().lower()
        if not text:
            return default
        if text in ('y', 'yes'):
            return True
        if text in ('n', 'no'):
            return False

def chop_tail(s: str, tail: str) -> str:
    if s.endswith(tail):
        return s[:-len(tail)]
    return s

def override_fields(named: typing.NamedTuple, params: dict) -> typing.NamedTuple:
    key_mapping = {field.lower(): field for field in named._fields}
    result = named
    for key, value in params.items():
        try:
            key_name = key_mapping[key]
        except KeyError:
            continue
        if isinstance(getattr(result, key_name), int):
            result = result._replace(**{key_name: int(value)})
        elif isinstance(getattr(result, key_name), str):
            result = result._replace(**{key_name: value})
    return result

def list_named_fields(named: typing.NamedTuple) -> typing.List[typing.Tuple[str, str]]:
    key_mapping = {field.lower(): field for field in named._fields}
    result = []
    for key, attr_name in sorted(key_mapping.items()):
        value = getattr(named, attr_name)
        if isinstance(value, int):
            result.append((key, 'integer', value))
        elif isinstance(value, str):
            result.append((key, 'string', value))
        else:
            result.append((key, 'unsupported', value))
    return result
