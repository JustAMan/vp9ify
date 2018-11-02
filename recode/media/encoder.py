import os
import tempfile
import sys
import subprocess
import errno

from ..helpers import which, NUM_THREADS
from ..tasks import ParallelTask
from .info import MediaInfo

class MediaEncoder(object):
    # reverse-engineered VP9-recommended CRF-from-video-height
    CRF_PROP = 76.61285454891394
    CRF_POW = -0.11754124960465037

    CRF_VP9_1080P = 31.0 # as recommended by VP9 guide
    # CRF = (CRF_PROP * video_diagonal ** CRF_POW) / (CRF_VP9_1080P / TARGET_1080_QUALITY)

    # Manually invented qmax = crf * 4 / 3, ffmpeg option: "-qmax value"
    QMAX_COEFF = 4./3.
    # QMAX = CRF * QMAX_COEFF

    _FFMPEG = which('ffmpeg', 'FFMPEG_PATH')
    _FFMPEG_NORM = which('ffmpeg-normalize', 'FFMPEG_NORM_PATH')

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
            return NotImplemented
        return self.media == other.media

    def tempfile(self, suffix='', ext='mkv'):
        path = os.path.join(tempfile.gettempdir(), '%s.%s.%s' % (self.media.friendly_name, suffix, ext))
        if path not in self.tempfiles:
            self.tempfiles.append(path)
        return path

    def __run_command(self, cmd, stdout):
        cmd = [str(x) for x in cmd]
        frame = sys._getframe()
        try:
            caller = frame.f_back.f_code.co_name
        finally:
            del frame
        if stdout is not None:
            path, ext = os.path.splitext(stdout)
            stdout = path + '-%s-%s' % (caller, self.media.short_name) + ext

        if os.environ.get('RECODE_PRODUCE_DEBUG', 'no').lower() == 'yes':
            print "[DBG] running command: %s (logs to: %s)" % (subprocess.list2cmdline(cmd), stdout)
        if sys.platform != 'win32':
            if stdout is not None:
                stdout = open(stdout, 'a')
            try:
                subprocess.check_call(cmd, stdout=stdout, stderr=subprocess.STDOUT if stdout is not None else None)
            except subprocess.CalledProcessError as err:
                raise self.TranscodingFailure(err)
            finally:
                if stdout is not None:
                    stdout.close()

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

    ffmpeg option:
    -passlogfile prefix
    Set two-pass log file name prefix to prefix, the default file name prefix is ``ffmpeg2pass''. The
    complete file name will be PREFIX-N.log, where N is a number specific to the output stream.

    Current approach of encoding the file:
        $FFMPEG_PATH -i "$1" -tile-columns 2 -g 240 -threads 6 -movflags +faststart -max_muxing_queue_size 4000 -map 0:v -c:v libvpx-vp9 -an -crf 24 -qmax 32 -b:v 0 -quality good -speed 5 -pass 1 -y "$TARGET_NOEXT-vp9-audio=no.mkv"
        $FFMPEG_PATH -i "$1" -tile-columns 2 -g 240 -threads 6 -movflags +faststart -max_muxing_queue_size 4000 -map 0:v -c:v libvpx-vp9 -an -crf 24 -qmax 32 -b:v 0 -quality good -speed 2 -pass 2 -y "$TARGET_NOEXT-vp9-audio=no.mkv"
        $FFMPEG_NORM "$1" -c:a libvorbis -b:a 192k -e="-aq 5" -t -14 -vn -f -ar 48000 -pr -o "$TARGET_NOEXT-vorbis-video=no.mkv"
        $FFMPEG_PATH -i "$TARGET_NOEXT-vp9-audio=no.mkv" -i "$TARGET_NOEXT-vorbis-video=no.mkv" -map 0:v -map 1:a -c copy -y "$2"

    '''


    def run_video_transcode_cmd(self, is_first_pass, stdout=None):
        crf = (self.CRF_PROP * self.info.get_video_diagonal() ** self.CRF_POW) * self.media.TARGET_1080_QUALITY / self.CRF_VP9_1080P
        qmax = crf * self.QMAX_COEFF
        speed = self.media.SPEED_FIRST if is_first_pass else self.media.SPEED_SECOND
        passno = 1 if is_first_pass else 2

        cmd = [self._FFMPEG, '-i', self.src, '-tile-columns', 2, '-g', 240, '-threads', NUM_THREADS,
               '-movflags', '+faststart', '-map', '0:v', '-c:v', 'libvpx-vp9', '-an', '-crf', int(crf),
               '-qmax', int(qmax), '-b:v', 0, '-quality', 'good', '-speed', speed, '-pass', passno,
               '-passlogfile', self.tempfile('ffmpeg2pass', 'log'), '-y', self.tempfile('vp9-audio=no')]
        self.__run_command(cmd, stdout)

    def extract_audio_tracks(self, stdout=None):
        channels = self.info.get_audio_channels()
        for track_id, channel_count in channels.items():
            # extract only stereo, everything else would be taken from source
            if channel_count != 2:
                continue
            cmd = [self._FFMPEG, '-i', self.src, '-map', '0:a:%d' % track_id, '-c:a', 'copy', '-vn', '-y', self.tempfile('audio-%d' % track_id)]
            self.__run_command(cmd, stdout)

    def run_audio_transcode_cmd(self, stdout=None):
        ''' this normalizes the volume '''
        channels = self.info.get_audio_channels()
        for track_id, channel_count in channels.items():
            if channel_count == 2:
                # normalize only stereo, nothing else
                cmd = [self._FFMPEG_NORM, self.tempfile('audio-%d' % track_id),
                    '-c:a', 'libvorbis', '-b:a', self.media.AUDIO_BITRATE, '-e="-aq %s"' % self.media.AUDIO_QUALITY,
                    '-t', self.media.LUFS_LEVEL, '-f', '-ar', self.media.AUDIO_FREQ,
                    '-o', self.tempfile('audio-%d' % track_id), '-vn']
            else:
                # just re-encode as libvorbis
                cmd = [self._FFMPEG, '-i', self.src,
                    '-map', '0:a:%d' % track_id, '-vn',
                    '-c:a', 'libvorbis', '-b:a', self.media.AUDIO_BITRATE, '-aq', self.media.AUDIO_QUALITY,
                    '-y', self.tempfile('audio-%d' % track_id)]
            self.__run_command(cmd, stdout)

    def run_remux_cmd(self, dest, stdout=None):
        ''' this produces result file '''
        channels = self.info.get_audio_channels()
        cmd = [self._FFMPEG, '-i', self.tempfile('vp9-audio=no'), '-map', '0:v', '-c:v', 'copy']
        for idx, track_id in enumerate(channels):
            cmd.extend(['-i', self.tempfile('audio-%d' % track_id), '-map', '%d:a' % (idx + 1)])
        cmd.extend(['-c:a', 'copy', '-y', self.media.get_target_video_path(dest)])
        self.__run_command(cmd, stdout)

    def run_extract_subtitles(self, dest, stdout=None):
        subtitles = self.info.get_subtitles()
        if subtitles:
            cmd = [which('mkvextract'), 'tracks', self.src]
            for sub in subtitles:
                cmd.append('%s:%s' % (sub.track_id, self.media.get_target_subtitles_path(dest, sub.name)))
            self.__run_command(cmd, stdout)

    def cleanup_tempfiles(self):
        for tempfile in self.tempfiles:
            try:
                os.unlink(tempfile)
            except OSError as err:
                if err.errno != errno.ENOENT:
                    raise

    def __describe_task(self, task):
        name = task.func.__func__.__code__.co_name
        if name == 'run_video_transcode_cmd':
            name += ' pass=%d' % (1 if task.args[0] else 2)
        return '%s (%s)' % (name, self.media.friendly_name)

    def __make_task(self, cost, method, *args, **kw):
        return ParallelTask(func=method, args=args, kw=kw, cost=cost, describe=self.__describe_task)

    def make_tasks(self, dest, stdout=None):
        return [self.__make_task(NUM_THREADS, self.run_video_transcode_cmd, True, stdout),
                self.__make_task(NUM_THREADS, self.run_video_transcode_cmd, False, stdout),
                self.__make_task(1, self.run_audio_transcode_cmd, stdout),
                self.__make_task(1, self.run_remux_cmd, dest, stdout),
                self.__make_task(0, self.run_extract_subtitles, dest, stdout),
                self.__make_task(0, self.cleanup_tempfiles)
            ]
