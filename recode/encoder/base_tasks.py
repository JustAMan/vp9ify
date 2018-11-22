import tempfile
import os
import logging
import subprocess
import sys
import stat
import errno
import glob

from ..helpers import open_with_dir, ensuredir, chop_tail
from ..tasks import IParallelTask, Resource, ResourceKind
from ..flock import FLock

class TranscodingFailure(Exception):
    def __init__(self, err):
        Exception.__init__(self)
        self.err = err

class EncoderTask(IParallelTask):
    BLOCKERS = ()
    static_limit = 1

    def __init__(self, encoder):
        self.encoder = encoder
        self.media = encoder.media
        self.info = encoder.info
        self.stdout = encoder.stdout or None
        self.tmpdir = tempfile.gettempdir()
        self.dest = encoder.dest
        self.blockers = list(self.BLOCKERS)
    
    def _get_compare_attrs(self):
        return [self.encoder, self.media, self.stdout, self.blockers, self.dest]

    @classmethod
    def _get_name(cls):
        return chop_tail(cls.__name__, 'Task')

    @property
    def name(self):
        return self._get_name()

    def __eq__(self, other):
        if type(self) != type(other):
            return False
        for left, right in zip(self._get_compare_attrs(), other._get_compare_attrs()):
            if left != right:
                return False
        return True

    def __str__(self):
        return '%s (%s)' % (self.name, self.media.friendly_name)

    def can_run(self, batch_tasks):
        blockers = [t for t in batch_tasks if isinstance(t, EncoderTask) and t.name in self.blockers]
        return not blockers

    def _get_stdout(self):
        if self.stdout is not None:
            path, ext = os.path.splitext(self.stdout)
            return '%s-%s-%s%s' % (path, self.name.lower(), self.media.short_name, ext)
        return None

    def _run_command(self, cmd):
        cmd = [str(x) for x in cmd]
        stdout = self._get_stdout()

        logging.debug("running command: %s (logs to: %s)" % (subprocess.list2cmdline(cmd), stdout))
        if sys.platform != 'win32':
            if self.stdout is not None:
                stdout = open_with_dir(stdout, 'a')
            env = dict(os.environ)
            env['FFMPEG_PATH'] = self.encoder.FFMPEG
            env['TMP'] = env['TEMP'] = env['TMPDIR'] = self.tmpdir # for ffmpeg-normalize if run in "--resume" mode without TMP set for vp9ify
            try:
                subprocess.check_call(cmd, stdout=stdout, stderr=subprocess.STDOUT if stdout is not None else None, env=env)
            except subprocess.CalledProcessError as err:
                logging.error('Cannot run transcode, return code: %s' % err.returncode)
                raise TranscodingFailure(err)
            finally:
                if self.stdout is not None:
                    stdout.close()

    def _make_command(self):
        raise NotImplementedError()

    def __call__(self):
        cmd = self._make_command()
        if cmd:
            self._run_command(cmd)

    def _gen_command(self):
        return [str(x) for x in self._make_command()]

    def scriptize(self):
        cmd = self._gen_command()
        if not cmd:
            return
        script = self.media.get_target_scriptized_path(self.dest)
        with FLock(script + '.lock'):
            header_needed = not os.path.exists(script)
            with open_with_dir(script, 'a') as out:
                if header_needed:
                    out.write('#!/bin/bash\n')
                    for tmpname in 'TMP TEMP TMPDIR'.split():
                        out.write('export %s=%s\n' % (tmpname, subprocess.list2cmdline([self.tmpdir])))
                        out.write('mkdir -p %s\n' % subprocess.list2cmdline([self.tmpdir]))
                    out.write('export FFMPEG_PATH=%s\n\n' % subprocess.list2cmdline([self.encoder.FFMPEG]))
                out.write('# %s\n' % self.name)
                if self.stdout:
                    out.write('mkdir -p %s\n' % subprocess.list2cmdline([os.path.dirname(self._get_stdout())]))
                out.write(subprocess.list2cmdline(cmd))
                if self.stdout:
                    out.write(' >> %s 2>&1' % subprocess.list2cmdline([self._get_stdout()]))
                out.write('\n')
            stats = os.stat(script)
            os.chmod(script, stats.st_mode | stat.S_IXUSR)

    def get_limit(self, candidate_tasks, running_tasks):
        return self.static_limit

    @property
    def produced_file(self):
        raise NotImplementedError()

class RemoveScriptTask(EncoderTask):
    resource = Resource(kind=ResourceKind.IO, priority=0)
    static_limit = 30
    BLOCKERS = ()
    @property
    def produced_files(self):
        return []

    def __call__(self):
        pass

    def scriptize(self):
        script = self.media.get_target_scriptized_path(self.dest)
        try:
            os.unlink(script)
        except OSError as err:
            if err.errno != errno.ENOENT:
                raise

EncoderTask.BLOCKERS += (RemoveScriptTask._get_name(),)

class RemuxTask(EncoderTask):
    resource = Resource(kind=ResourceKind.IO, priority=0)
    static_limit = 1
    def __init__(self, encoder, video_tasks, audio_tasks):
        EncoderTask.__init__(self, encoder)
        assert video_tasks
        self.video_inputs = list(video_tasks[-1].produced_files)
        assert self.video_inputs
        self.audio_inputs = []
        for task in audio_tasks:
            self.audio_inputs.extend(task.produced_files)
        self.blockers.extend(task.name for task in (list(video_tasks) + list(audio_tasks)))

    @property
    def produced_files(self):
        return [self.media.get_target_video_path(self.dest)]

    def _make_command(self):
        cmd = [self.encoder.FFMPEG, '-i'] + self.video_inputs
    
        for audio_input in self.audio_inputs:
            cmd.extend(['-i', audio_input])

        cmd.extend(['-movflags', '+faststart'])
        for idx in range(len(self.video_inputs)):
            cmd.extend(['-map', '%d:v' % idx])
        for idx in range(len(self.video_inputs), len(self.video_inputs) + len(self.audio_inputs)):
            cmd.extend(['-map', '%d:a' % idx])

        target = self.produced_files[0]
        ensuredir(os.path.dirname(target))
        cmd.extend(['-c', 'copy', '-y', target])
        return cmd

class ExtractSubtitlesTask(EncoderTask):
    resource = Resource(kind=ResourceKind.IO, priority=1)
    static_limit = 2
    @property
    def produced_files(self):
        subtitles = self.info.get_subtitles()
        result = []
        for sub in subtitles:
            result.append(self.media.get_target_subtitles_path(self.dest, sub.language))
        return result

    def _make_command(self):
        subtitles = self.info.get_subtitles()
        if subtitles:
            cmd = [self.encoder.MKVEXTRACT, 'tracks', self.media.src]
            for sub, subpath in zip(subtitles, self.produced_files):
                ensuredir(os.path.dirname(subpath))
                cmd.append('%s:%s' % (sub.track_id, subpath))
            return cmd
        return None

class CleanupTempfiles(EncoderTask):
    resource = Resource(kind=ResourceKind.IO, priority=2)
    static_limit = 10
    def __init__(self, encoder, remux_task):
        EncoderTask.__init__(self, encoder)
        self.blockers.append(remux_task.name)

    @property
    def produced_files(self):
        return []

    def __call__(self):
        files = list(self.encoder.tempfiles)
        for pattern in self.encoder.patterns:
            files.extend(glob.glob(pattern))
        for fname in files:
            try:
                os.unlink(fname)
            except OSError as err:
                if err.errno != errno.ENOENT:
                    raise

    def _gen_command(self):
        if not any((self.encoder.tempfiles, self.encoder.patterns)):
            return []
        return ['rm', '-f'] + self.encoder.tempfiles + self.encoder.patterns
