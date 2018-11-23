import os
import sys
import glob
import argparse
try:
    import cPickle as pickle
except ImportError:
    import pickle
import logging
import collections

LOGGING_FORMAT = '%(asctime)s|%(levelname)s|%(message)s'
logging.basicConfig(format=LOGGING_FORMAT, level=logging.INFO)

from recode.helpers import NUM_THREADS, which, get_suffix, open_with_dir, ensuredir
from recode.tasks import Executor
from recode.media.parsers import PARSERS
from recode.media.base import UnknownFile, BadParameters
from recode.locked_state import LockedState

def parse_fentry(fentry, suffix, forced_parser=None, forced_params=None):
    fname, fpath = fentry
    if not suffix:
        fname = os.path.splitext(fname)[0]
    else:
        if not fname.endswith(suffix):
            raise ValueError('Bad name "%s" - not ending in suffix "%s"' % (fname, suffix))
        fname = fname[:-len(suffix)]

    if forced_parser:
        return forced_parser.parse_forced(fname, fpath, forced_params)

    for parser in PARSERS:
        try:
            entry = parser.parse(fname, fpath)
        except UnknownFile:
            continue
        else:
            return entry
    raise ValueError('Cannot parse "%s" - no handlers found' % fname)

def get_files(src_list):
    STUB = r'''/external/path1/Series Name.S01E01.Episode name 1.suffix.mkv
/external/path1/Series Name.S01E02.Episode name 2.suffix.mkv
/external/path1/Series Name.S01E03.Episode name 3.suffix.mkv
/external/path1/Series Name.S01E04.Episode name 4.suffix.mkv
'''.splitlines()
    lst = STUB if sys.platform == 'win32' else src_list
    return tuple((os.path.basename(fname), fname) for fname in lst)


def main():
    parser = argparse.ArgumentParser(description='Transcode some videos for storing')
    parser.add_argument('source', metavar='SRC_PATH_LIST', type=str, nargs='?', help='Source items to compress')
    parser.add_argument('--dest', metavar='DEST_PATH', type=str, default='', help='Path to target directory for this type of content (e.g. not including series name)')
    parser.add_argument('--resume', action='store_true', help='Resume unfinished recoding')
    parser.add_argument('--state', metavar='STATE_FILENAME', type=str, default='', help='Path to file where state to be stored')
    parser.add_argument('--log', metavar='LOG_FILENAME', type=str, default='', help='Path to append logs to')
    parser.add_argument('--nostart', action='store_true', help='Do not start encoding, just create state file for resuming later')
    parser.add_argument('--debug', action='store_true', help='Produce some additional debug output')
    parser.add_argument('--scriptize', action='store_true', help='Only generate shell scripts for encoding, do no real encoding work')
    parser.add_argument('--interactive', '-i', action='store_true', help='Be interactive: ask some questions before running')
    parser.add_argument('--force-type', choices=[media_parser.FORCE_NAME for media_parser in PARSERS], help='Force media type')
    parser.add_argument('--force-params', type=str, default='', help='Additional parameters for forced media type')
    parser.add_argument('--list-params', action='store_true', help='Show parameters accepted by each media type')
    args = parser.parse_args()

    if args.list_params:
        print 'Accepted parameters to be passed via --force-params:'
        for media_parser in PARSERS:
            print '[--force-type = %s]' % media_parser.FORCE_NAME
            params = media_parser.describe_parameters()
            maxkeylen = max(len(p.key) for p in params)
            maxkindlen = max(len(p.kind) for p in params)

            grouped = collections.defaultdict(list)
            for param in params:
                grouped[param.group].append(param)
            for group, params in sorted(grouped.items()):
                print 'Group "%s":' % (group or 'general')
                for param in sorted(params, key=lambda p: p.key):
                    print '\t%s [%s]%s' % (param.key.ljust(maxkeylen), param.kind.center(maxkindlen), ' - %s' % param.help if param.help else '')
        return

    if args.interactive and args.resume:
        parser.print_help()
        sys.exit('Cannot be interactive and resume at the same time')

    forced_parser, forced_params = None, None
    if args.force_type:
        forced_parser = [media_parser for media_parser in PARSERS if media_parser.FORCE_NAME == args.force_type][0]
        if args.force_params:
            try:
                forced_params = forced_parser.parse_parameters(args.force_params)
            except BadParameters as err:
                sys.exit('Incorrect parameters for "%s" media type: %s' % (args.force_type, err.msg))

    if not args.state:
        if not args.dest:
            parser.print_help()
            sys.exit("Please specify either dest path or --state")
        resume_file = os.path.abspath(os.path.join(args.dest, 'tasks.pickle'))
    else:
        resume_file = os.path.abspath(args.state)
    state = LockedState(resume_file)

    if args.log or args.dest:
        logpath = os.path.abspath(args.log or os.path.join(args.dest, 'recode.log'))
        ensuredir(os.path.dirname(logpath))
        handler = logging.FileHandler(logpath, delay=True)
        handler.setFormatter(logging.Formatter(LOGGING_FORMAT))
        logging.getLogger().addHandler(handler)
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if not args.resume:
        if not args.source or not args.dest:
            parser.print_help()
            sys.exit('You must specify at least one source item and DEST_PATH when running without --resume')
        inp = get_files([os.path.abspath(f) for f in args.source])
        logging.info('Found %d items' % len(inp))
        suffix = ''

        entries = []
        entry_types = set()

        for fentry in inp:
            entry = parse_fentry(fentry, suffix, forced_parser, forced_params)
            logging.debug('Parsed entry "%s"' % entry.full_name)
            entries.append(entry)
            entry_types.add(type(entry))

        need_reparse = False
        if not forced_parser and args.force_params:
            if len(entry_types) != 1:
                sys.exit('Cannot force params when multiple media types found')
            forced_parser = list(entry_types)[0]
            try:
                forced_params = forced_parser.parse_parameters(args.force_params)
            except BadParameters as err:
                sys.exit('Incorrect parameters for "%s" media type: %s' % (forced_parser.FORCE_NAME, err.msg))
            # re-parse entries
            logging.debug('Re-parsing entries as forced params detected')
            need_reparse = True
        
        if len(entry_types) == 1 and list(entry_types)[0].STRIP_SUFFIX:
            suffix = get_suffix(inp)
            logging.info('Detected suffix as "%s", re-parsing entries' % suffix)
            need_reparse = True

        if need_reparse:
            entries = []
            for fentry in inp:
                entry = parse_fentry(fentry, suffix, forced_parser, forced_params)
                logging.debug('Parsed entry "%s"' % entry.full_name)
                entries.append(entry)

        entries.sort(key=lambda fe: fe.comparing_key)
        if args.interactive:
            for entry in entries:
                entry.interact()

        new_tasks = [entry.make_encode_tasks(args.dest, logpath or None) for entry in entries]
        with state:
            try:
                tasks = state.read()
            except IOError:
                tasks = []
                logging.info('Resume file "%s" does not exist, starting from scratch' % resume_file)
            else:
                logging.info('Resume file "%s" exists, appending' % resume_file)
            tasks.extend(new_tasks)
            state.write(tasks)

    if args.scriptize:
        logging.info('Scriptizing started')
        Executor(state, scriptize=True).execute()
        logging.info('Scriptizing stopped')
    elif not args.nostart:
        logging.info('Recoding started')
        Executor(state).execute()
        logging.info('Recoding stopped')

if __name__ == '__main__':
    main()
