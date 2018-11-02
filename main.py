import os
import sys
import glob
import argparse
try:
    import cPickle as pickle
except ImportError:
    import pickle

from recode.helpers import NUM_THREADS, which, get_suffix
from recode.tasks import Executor
from recode.media import PARSERS, MediaEntry, MediaEncoder

def parse_fentry(fentry, suffix):
    fname, fpath = fentry
    if not fname.endswith(suffix):
        raise ValueError('Bad name "%s" - not ending in suffix "%s"' % (fname, suffix))
    fname = fname[:-len(suffix)]

    for parser in PARSERS:
        try:
            entry = parser.parse(fname, fpath)
        except MediaEntry.UnknownFile:
            continue
        else:
            return entry
    raise ValueError('Cannot parse "%s" - no handlers found' % fname)

def get_files(src):
    STUB = r'''/external/path1/Series Name.S01E01.Episode name 1.suffix.mkv
/external/path1/Series Name.S01E02.Episode name 2.suffix.mkv
/external/path1/Series Name.S01E03.Episode name 3.suffix.mkv
/external/path1/Series Name.S01E04.Episode name 4.suffix.mkv
'''.splitlines()
    lst = STUB if sys.platform == 'win32' else glob.glob(os.path.join(src, '*.mkv'))
    return tuple((os.path.basename(fname), fname) for fname in lst)


def main():
    parser = argparse.ArgumentParser(description='Transecode some videos for storing')
    parser.add_argument('source', metavar='SRC_PATH', type=str, nargs='?', help='Path to source directory with *.mkv inside')
    parser.add_argument('dest', metavar='DEST_PATH', type=str,  nargs='?',help='Path to target directory for this type of content (e.g. not including series name)')
    parser.add_argument('--resume', action='store_true', help='Resume unfinished recoding')
    parser.add_argument('--state', metavar='STATE_FILENAME', type=str, default='', help='Path to file where state to be stored')
    parser.add_argument('--log', metavar='LOG_FILENAME', type=str, default='', help='Path to append logs to')
    parser.add_argument('--nostart', action='store_true', help='Do not start encoding, just create state file for resuming later')
    parser.add_argument('--debug', action='store_true', help='Produce some additional debug output')
    args = parser.parse_args()

    if not args.state:
        if not args.source:
            sys.exit("Please specify either SRC_PATH or --state")
        resume_file = os.path.join(args.source, 'tasks.pickle')
    else:
        resume_file = os.path.abspath(args.state)
    if args.resume and args.log:
        sys.exit('Cannot change log file when resuming')
    os.environ['RECODE_PRODUCE_DEBUG'] = 'yes' if args.debug else 'no'

    if not args.resume:
        if not args.source or not args.dest:
            sys.exit('You must specify both SRC_PATH and DEST_PATH when running without --resume')
        inp = get_files(args.source)
        suffix = get_suffix(inp)

        entries = []
        for fentry in inp:
            entries.append(parse_fentry(fentry, suffix))
        entries.sort(key=lambda fe: fe.comparing_key)

        try:
            with open(resume_file, 'wb') as inp:
                tasks = pickle.loads(inp.read())
        except IOError:
            tasks = []

        logpath = os.path.abspath(args.log or os.path.join(args.source, 'recode.log'))
        for entry in entries:
            tasks.append(MediaEncoder(entry).make_tasks(args.dest, logpath))
        with open(resume_file, 'wb') as out:
            out.write(pickle.dumps(tasks))

    if not args.nostart:
        Executor(resume_file).execute()

if __name__ == '__main__':
    main()
