import os
import tempfile
import sys
import subprocess
import errno
import glob

from ..helpers import which, open_with_dir, ensuredir, NUM_THREADS
from ..tasks import IParallelTask, Resource, ResourceLimit
from .info import MediaInfo
from ..options import OPTIONS

class EncoderTask(IParallelTask):
    BLOCKERS = ()

    def __init__(self, encoder, stdout=None):
        self.encoder = encoder
        self.media = encoder.media
        self.info = encoder.info
        self.stdout = stdout or None
        self.tmpdir = tempfile.tempdir()
    
    def _get_compare_attrs(self):
        return [self.encoder, self.media, self.stdout, self.BLOCKERS]

    @classmethod
    def _get_name(cls):
        return cls.__name__.rstrip('Task')

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

    def can_run(self, all_tasks):
        blockers = [t for t in all_tasks if isinstance(t, EncoderTask) and t.name in self.BLOCKERS]
        return not blockers

    def _run_command(self, cmd):
        cmd = [str(x) for x in cmd]
        if self.stdout is not None:
            path, ext = os.path.splitext(self.stdout)
            stdout = '%s-%s-%s%s' % (path, self.name.lower(), self.media.short_name, ext)

        if OPTIONS.debug:
            print "[DBG] running command: %s (logs to: %s)" % (subprocess.list2cmdline(cmd), stdout)
        if sys.platform != 'win32':
            if self.stdout is not None:
                stdout = open_with_dir(stdout, 'a')
            env = dict(os.environ)
            env['FFMPEG_PATH'] = self.encoder.FFMPEG
            env['TMP'] = self.tmpdir # for ffmpeg-normalize if run in "--resume" mode without TMP set for vp9ify
            try:
                subprocess.check_call(cmd, stdout=stdout, stderr=subprocess.STDOUT if stdout is not None else None, env=env)
            except subprocess.CalledProcessError as err:
                raise MediaEncoder.TranscodingFailure(err)
            finally:
                if self.stdout is not None:
                    stdout.close()

    def _make_command(self):
        raise NotImplementedError()

    def __call__(self):
        cmd = self._make_command()
        if cmd:
            self._run_command(cmd)

class VideoEncodeTask(EncoderTask):
    COMPARE = ('encoder', 'media', 'stdout', 'is_first_pass')
    limit = ResourceLimit(resource=Resource.CPU, limit=NUM_THREADS-2)

    def __init__(self, encoder, is_first_pass, stdout=None):
        EncoderTask.__init__(self, encoder, stdout)
        self.is_first_pass = is_first_pass

    def _get_compare_attrs(self):
        return EncoderTask._get_compare_attrs(self) + [self.is_first_pass]

    @property
    def name(self):
        return '%s-pass=%d' % (self._get_name(), 1 if self.is_first_pass else 2)

    def can_run(self, all_tasks):
        all_transcodes = [t for t in all_tasks if isinstance(t, VideoEncodeTask)]
        return all_transcodes[0] == self

    def _make_command(self):
        crf = (self.encoder.CRF_PROP * self.info.get_video_diagonal() ** self.encoder.CRF_POW) * self.media.TARGET_1080_QUALITY / self.encoder.CRF_VP9_1080P
        qmax = crf * self.encoder.QMAX_COEFF
        speed = self.media.SPEED_FIRST if self.is_first_pass else self.media.SPEED_SECOND
        passno = 1 if self.is_first_pass else 2

        return [self.encoder.FFMPEG, '-i', self.media.src, '-g', 240,
               '-movflags', '+faststart', '-map', '0:v', '-c:v', 'libvpx-vp9', '-an', '-crf', int(crf),
               '-qmax', int(qmax), '-b:v', 0, '-quality', 'good', '-speed', speed, '-pass', passno,
               '-passlogfile', self.encoder.make_tempfile('ffmpeg2pass', 'log'), '-y', self.encoder.make_tempfile('vp9-audio=no')]

class AudioBaseTask(EncoderTask):
    def __init__(self, encoder, track_id, stdout=None):
        EncoderTask.__init__(self, encoder, stdout)
        self.track_id = track_id

    def _get_compare_attrs(self):
        return EncoderTask._get_compare_attrs(self) + [self.track_id]

    @property
    def name(self):
        return '%s-track=%d' % (self._get_name(), self.track_id)

class ExtractStereoAudioTask(AudioBaseTask):
    limit = ResourceLimit(resource=Resource.IO, limit=3)
    def __init__(self, encoder, track_id, stdout=None):
        AudioBaseTask.__init__(self, encoder, track_id, stdout)
        # this only extracts stereo
        assert self.info.get_audio_channels()[track_id] == 2

    def _make_command(self):
        return [self.encoder.FFMPEG, '-i', self.media.src,
                '-map', '0:%d:0' % self.track_id, '-c:a', 'copy', '-vn',
                '-y', self.encoder.make_tempfile('audio-%d-2ch' % self.track_id)]

class DownmixToStereoTask(AudioBaseTask):
    ''' Extract non-stereo audio tracks with downmixing to stereo for normalizing, so that we have all tracks
    that are normalized (normalizing a properly designed 5.1 audio means destroying its quality, but
    having each instance of original audio as normalized stereo helps when watching on simple, non-5.1-enabled hardware) '''
    limit = ResourceLimit(resource=Resource.CPU, limit=NUM_THREADS-1)
    def __init__(self, encoder, track_id, stdout=None):
        AudioBaseTask.__init__(self, encoder, track_id, stdout)
        # this only works with non-stereo
        assert self.info.get_audio_channels()[track_id] > 2

    def _make_command(self):
        return [self.encoder.FFMPEG, '-i', self.media.src,
                '-map', '0:%d:0' % self.track_id, '-c:a', 'aac', '-b:a', self.media.AUDIO_INTERMEDIATE_BITRATE,
                '-ac', 2, '-af', 'pan=stereo|FL < 1.0*FL + 0.707*FC + 0.707*BL|FR < 1.0*FR + 0.707*FC + 0.707*BR',
                '-vn', '-y', self.encoder.make_tempfile('audio-%d-2ch' % self.track_id)]

class NormalizeStereoTask(AudioBaseTask):
    limit = ResourceLimit(resource=Resource.CPU, limit=NUM_THREADS-1)
    def __init__(self, encoder, track_id, parent_task, stdout=None):
        AudioBaseTask.__init__(self, encoder, track_id, stdout)
        # normalization should be only applied to stereo
        assert self.info.get_audio_channels()[track_id] == 2
        self.BLOCKERS = (parent_task.name,)

    def _make_command(self):
        return [self.encoder.FFMPEG_NORM, self.encoder.make_tempfile('audio-%d-2ch' % self.track_id),
                '-c:a', 'libvorbis', '-b:a', self.media.AUDIO_BITRATE, '-e=-aq %s' % self.media.AUDIO_QUALITY,
                '-t', self.media.LUFS_LEVEL, '-f', '-ar', self.media.AUDIO_FREQ,
                '-o', self.encoder.make_tempfile('audio-%d-2ch' % self.track_id), '-vn']

class AudioEncodeTask(AudioBaseTask):
    limit = ResourceLimit(resource=Resource.CPU, limit=NUM_THREADS-1)
    def __init__(self, encoder, track_id, stdout=None):
        AudioBaseTask.__init__(self, encoder, track_id, stdout)
        # encoding without normalization is applied to non-stereo only
        assert self.info.get_audio_channels()[track_id] != 2

    def _make_command(self):
        return [self.encoder.FFMPEG, '-i', self.media.src,
                '-map', '0:%d:0' % self.track_id, '-vn',
                '-c:a', 'libvorbis', '-b:a', self.media.AUDIO_BITRATE, '-aq', self.media.AUDIO_QUALITY,
                '-y', self.encoder.make_tempfile('audio-%d' % self.track_id)]

class BaseDestTask(EncoderTask):
    def __init__(self, encoder, dest, stdout=None):
        EncoderTask.__init__(self, encoder, stdout)
        self.dest = dest

    def _get_compare_attrs(self):
        return EncoderTask._get_compare_attrs(self) + [self.dest]

class RemuxTask(BaseDestTask):
    limit = ResourceLimit(resource=Resource.IO, limit=1)
    def __init__(self, encoder, codec_tasks, dest, stdout=None):
        BaseDestTask.__init__(self, encoder, dest, stdout)
        self.BLOCKERS = tuple(task.name for task in codec_tasks)

    def _make_command(self):
        channels = self.info.get_audio_channels()
        cmd = [self.encoder.FFMPEG, '-i', self.encoder.make_tempfile('vp9-audio=no')]
    
        total_audio = 0
        for track_id, channel_count in channels.items():
            cmd.extend(['-i', self.encoder.make_tempfile('audio-%d-2ch' % track_id)])
            total_audio += 1
            if channel_count != 2:
                cmd.extend(['-i', self.encoder.make_tempfile('audio-%d' % track_id)])
                total_audio += 1
        cmd.extend(['-movflags', '+faststart', '-map', '0:v', '-c:v', 'copy'])
        for number in range(1, total_audio + 1):
            cmd.extend(['-map', '%d:a' % number])
    
        target = self.media.get_target_video_path(self.dest)
        ensuredir(os.path.dirname(target))
        cmd.extend(['-c:a', 'copy', '-y', target])
        return cmd

class ExtractSubtitlesTask(BaseDestTask):
    limit = ResourceLimit(resource=Resource.IO, limit=3)
    def _make_command(self):
        subtitles = self.info.get_subtitles()
        if subtitles:
            cmd = [self.encoder.MKVEXTRACT, 'tracks', self.media.src]
            for sub in subtitles:
                subpath = self.media.get_target_subtitles_path(self.dest, sub.language)
                ensuredir(os.path.dirname(subpath))
                cmd.append('%s:%s' % (sub.track_id, subpath))
            return cmd
        return None

class CleanupTempfiles(EncoderTask):
    limit = ResourceLimit(resource=Resource.IO, limit=10)
    def __init__(self, encoder, remux_task, stdout=None):
        EncoderTask.__init__(self, encoder, stdout)
        self.BLOCKERS = (remux_task.name,)

    def __call__(self):
        self.encoder.cleanup_tempfiles()

class MediaEncoder(object):
    '''
    VP9 reverse-engineered recommended CRF-from-height:
    >>> a
    76.61285454891394
    >>> b
    -0.11754124960465037
    >>> a*(math.hypot(1920,1080)**b)
    31.0

    Manually invented qmax = crf * 4 / 3, ffmpeg option: "-qmax value"
    For better (probably) quality: 1080p -> crf=24

    Current approach of encoding the file:
        $FFMPEG_PATH -i "$1" -tile-columns 2 -g 240 -threads 6 -movflags +faststart -max_muxing_queue_size 4000 -map 0:v -c:v libvpx-vp9 -an -crf 24 -qmax 32 -b:v 0 -quality good -speed 5 -pass 1 -y "$TARGET_NOEXT-vp9-audio=no.mkv"
        $FFMPEG_PATH -i "$1" -tile-columns 2 -g 240 -threads 6 -movflags +faststart -max_muxing_queue_size 4000 -map 0:v -c:v libvpx-vp9 -an -crf 24 -qmax 32 -b:v 0 -quality good -speed 2 -pass 2 -y "$TARGET_NOEXT-vp9-audio=no.mkv"
        $FFMPEG_NORM "$1" -c:a libvorbis -b:a 192k -e="-aq 5" -t -14 -vn -f -ar 48000 -pr -o "$TARGET_NOEXT-vorbis-video=no.mkv"
        $FFMPEG_PATH -i "$TARGET_NOEXT-vp9-audio=no.mkv" -i "$TARGET_NOEXT-vorbis-video=no.mkv" -map 0:v -map 1:a -c copy -y "$2"

    Burn subs in:
        $FFMPEG_PATH -i 60sec.mkv -max_muxing_queue_size 4000 -filter_complex '[0:v][0:s:0]overlay[v]' -map '[v]' -map 0:a -sn -c:v libx264 -crf 24 -c:a copy 60sec-subs-burned.mkv -y
    '''

    # reverse-engineered VP9-recommended CRF-from-video-height
    CRF_PROP = 76.61285454891394
    CRF_POW = -0.11754124960465037

    CRF_VP9_1080P = 31.0 # as recommended by VP9 guide
    # CRF = (CRF_PROP * video_diagonal ** CRF_POW) / (CRF_VP9_1080P / TARGET_1080_QUALITY)

    # Manually invented qmax = crf * 4 / 3, ffmpeg option: "-qmax value"
    QMAX_COEFF = 5./4.
    # QMAX = CRF * QMAX_COEFF

    FFMPEG = which('ffmpeg', 'FFMPEG_PATH')
    FFMPEG_NORM = which('ffmpeg-normalize', 'FFMPEG_NORM_PATH')
    MKVEXTRACT = which('mkvextract')

    class TranscodingFailure(Exception):
        def __init__(self, err):
            Exception.__init__(self)
            self.err = err

    def __init__(self, media):
        self.media = media
        self.src = media.src
        self.info = MediaInfo.parse(self.src)
        self.tempfiles = []

    def __eq__(self, other):
        if not isinstance(other, MediaEncoder):
            return False
        return self.media == other.media

    def make_tempfile(self, suffix='', ext='mkv'):
        tmpdir = tempfile.gettempdir()
        ensuredir(tmpdir)
        path = os.path.join(tmpdir, '%s.%s.%s' % (self.media.friendly_name, suffix, ext))
        if path not in self.tempfiles:
            self.tempfiles.append(path)
        return path

    def make_tasks(self, dest, stdout=None):
        video_tasks = [VideoEncodeTask(self, True, stdout), VideoEncodeTask(self, False, stdout)]
        audio_tasks = []
        for track_id, channel_count in self.info.get_audio_channels().items():
            if channel_count == 2:
                prepare_2ch_task = ExtractStereoAudioTask(self, track_id, stdout)
            else:
                prepare_2ch_task = DownmixToStereoTask(self, track_id, stdout)
                audio_tasks.append(AudioEncodeTask(self, track_id, stdout))
            audio_tasks.extend([prepare_2ch_task, NormalizeStereoTask(self, track_id, prepare_2ch_task, stdout)])
        remux_task = RemuxTask(self, video_tasks + audio_tasks, dest, stdout)
        return video_tasks + audio_tasks + [remux_task,
                ExtractSubtitlesTask(self, dest, stdout), CleanupTempfiles(self, remux_task, stdout)]
