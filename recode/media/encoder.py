import os
import tempfile
import sys
import subprocess
import errno

from ..helpers import which
from ..tasks import IParallelTask
from .info import MediaInfo

class CommandTask(IParallelTask):
    BLOCKERS = {
        'extract_audio_tracks': [],
        'run_audio_transcode_cmd': ['extract_audio_tracks'],
        'run_remux_cmd': ['run_video_transcode_cmd', 'run_audio_transcode_cmd'],
        'run_extract_subtitles': [],
        'cleanup_tempfiles': ['run_remux_cmd']
    }

    def __init__(self, media, method, cost, *args):
        self.method = method
        self.media = media
        self.args = args
        self.cost = cost
        self.task_name = self.method.__func__.__code__.co_name
        self.is_primary = False

    def __eq__(self, other):
        if not isinstance(other, CommandTask):
            return False
        return self.method == other.method and self.media == other.media and self.args == other.args

    def __call__(self):
        return self.method(*self.args)

    def __str__(self):
        return '%s (%s)' % (self.task_name, self.media.friendly_name)

    def can_run(self, all_tasks):
        blocker_names = set(self.BLOCKERS[self.task_name])
        blockers = [t for t in all_tasks if isinstance(t, CommandTask) and t.task_name in blocker_names]
        return not blockers

class VideoTranscodeTask(CommandTask):
    def __init__(self, media, method, cost, is_first_pass, *args):
        CommandTask.__init__(self, media, method, cost, is_first_pass, *args)
        self.is_first_pass = is_first_pass
        self.is_primary = True

    def __str__(self):
        return '%s pass=%d (%s)' % (self.task_name, 1 if self.is_first_pass else 2, self.media.friendly_name)

    def can_run(self, all_tasks):
        all_transcodes = [t for t in all_tasks if isinstance(t, VideoTranscodeTask)]
        return all_transcodes[0] == self

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

    Current approach of encoding the file:
        $FFMPEG_PATH -i "$1" -tile-columns 2 -g 240 -threads 6 -movflags +faststart -max_muxing_queue_size 4000 -map 0:v -c:v libvpx-vp9 -an -crf 24 -qmax 32 -b:v 0 -quality good -speed 5 -pass 1 -y "$TARGET_NOEXT-vp9-audio=no.mkv"
        $FFMPEG_PATH -i "$1" -tile-columns 2 -g 240 -threads 6 -movflags +faststart -max_muxing_queue_size 4000 -map 0:v -c:v libvpx-vp9 -an -crf 24 -qmax 32 -b:v 0 -quality good -speed 2 -pass 2 -y "$TARGET_NOEXT-vp9-audio=no.mkv"
        $FFMPEG_NORM "$1" -c:a libvorbis -b:a 192k -e="-aq 5" -t -14 -vn -f -ar 48000 -pr -o "$TARGET_NOEXT-vorbis-video=no.mkv"
        $FFMPEG_PATH -i "$TARGET_NOEXT-vp9-audio=no.mkv" -i "$TARGET_NOEXT-vorbis-video=no.mkv" -map 0:v -map 1:a -c copy -y "$2"

    Burn subs in:
        $FFMPEG_PATH -i 60sec.mkv -max_muxing_queue_size 4000 -filter_complex '[0:v][0:s:0]overlay[v]' -map '[v]' -map 0:a -sn -c:v libx264 -crf 24 -c:a copy 60sec-subs-burned.mkv -y
    '''

    def run_video_transcode_cmd(self, is_first_pass, stdout=None):
        crf = (self.CRF_PROP * self.info.get_video_diagonal() ** self.CRF_POW) * self.media.TARGET_1080_QUALITY / self.CRF_VP9_1080P
        qmax = crf * self.QMAX_COEFF
        speed = self.media.SPEED_FIRST if is_first_pass else self.media.SPEED_SECOND
        passno = 1 if is_first_pass else 2

        cmd = [self._FFMPEG, '-i', self.src, '-tile-columns', 2, '-g', 240, '-threads', 6,
               '-movflags', '+faststart', '-map', '0:v', '-c:v', 'libvpx-vp9', '-an', '-crf', int(crf),
               '-qmax', int(qmax), '-b:v', 0, '-quality', 'good', '-speed', speed, '-pass', passno,
               '-passlogfile', self.tempfile('ffmpeg2pass', 'log'), '-y', self.tempfile('vp9-audio=no')]
        self.__run_command(cmd, stdout)

    def extract_audio_tracks(self, stdout=None):
        channels = self.info.get_audio_channels()
        for track_id, channel_count in channels.items():
            if channel_count == 2: # extract stereo as-is
                cmd = [self._FFMPEG, '-i', self.src, '-map', '0:%d:0' % track_id, '-c:a', 'copy', '-vn', '-y', self.tempfile('audio-%d' % track_id)]
            else:
                # extract other audio tracks with downmixing to stereo for normalizing, so that we have all tracks
                # that are normalized (normalizing a properly designed 5.1 audio means destroying its quality, but
                # having each instance of original audio as normalized stereo helps when watching on simple, non-5.1-enabled hardware)
                cmd = [self._FFMPEG, '-i', self.src, '-map', '0:%d:0' % track_id, '-c:a', 'aac', '-b:a', self.media.AUDIO_INTERMEDIATE_BITRATE,
                       '-ac', 2, '-af', 'pan=stereo|FL < 1.0*FL + 0.707*FC + 0.707*BL|FR < 1.0*FR + 0.707*FC + 0.707*BR',
                       '-vn', '-y', self.tempfile('audio-%d-2ch' % track_id)]

            self.__run_command(cmd, stdout)

    def run_audio_transcode_cmd(self, stdout=None):
        ''' this normalizes the volume '''
        channels = self.info.get_audio_channels()
        for track_id, channel_count in channels.items():
            if channel_count == 2:
                cmd = [self._FFMPEG_NORM, self.tempfile('audio-%d' % track_id),
                    '-c:a', 'libvorbis', '-b:a', self.media.AUDIO_BITRATE, '-e=-aq %s' % self.media.AUDIO_QUALITY,
                    '-t', self.media.LUFS_LEVEL, '-f', '-ar', self.media.AUDIO_FREQ,
                    '-o', self.tempfile('audio-%d' % track_id), '-vn']
            else:
                # re-encode original as libvorbis, normalize downmixed
                cmd = [self._FFMPEG, '-i', self.src,
                    '-map', '0:%d:0' % track_id, '-vn',
                    '-c:a', 'libvorbis', '-b:a', self.media.AUDIO_BITRATE, '-aq', self.media.AUDIO_QUALITY,
                    '-y', self.tempfile('audio-%d' % track_id)]
                self.__run_command(cmd, stdout)

                cmd = [self._FFMPEG_NORM, self.tempfile('audio-%d-2ch' % track_id),
                    '-c:a', 'libvorbis', '-b:a', self.media.AUDIO_BITRATE, '-e=-aq %s' % self.media.AUDIO_QUALITY,
                    '-t', self.media.LUFS_LEVEL, '-f', '-ar', self.media.AUDIO_FREQ,
                    '-o', self.tempfile('audio-%d-2ch' % track_id), '-vn']
            self.__run_command(cmd, stdout)

    def run_remux_cmd(self, dest, stdout=None):
        ''' this produces result file '''
        channels = self.info.get_audio_channels()
        cmd = [self._FFMPEG, '-i', self.tempfile('vp9-audio=no')]
    
        total_audio = 0
        for track_id, channel_count in channels.items():
            cmd.extend(['-i', self.tempfile('audio-%d' % track_id)])
            total_audio += 1
            if channel_count != 2:
                cmd.extend(['-i', self.tempfile('audio-%d-2ch' % track_id)])
                total_audio += 1
        cmd.extend(['-movflags', '+faststart', '-map', '0:v', '-c:v', 'copy'])
        for number in range(1, total_audio + 1):
            cmd.extend(['-map', '%d:a' % number])
    
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

    def __make_task(self, cost, method, *args):
        return (VideoTranscodeTask if method == self.run_video_transcode_cmd else CommandTask)(self.media, method, cost, *args)

    def make_tasks(self, dest, stdout=None):
        return [self.__make_task(1.5, self.run_video_transcode_cmd, True, stdout),
                self.__make_task(4, self.run_video_transcode_cmd, False, stdout),
                self.__make_task(1, self.extract_audio_tracks, stdout),
                self.__make_task(1, self.run_audio_transcode_cmd, stdout),
                self.__make_task(1, self.run_remux_cmd, dest, stdout),
                self.__make_task(0.5, self.run_extract_subtitles, dest, stdout),
                self.__make_task(0, self.cleanup_tempfiles)
            ]
