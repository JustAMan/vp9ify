import collections
import typing

WebmCrfOptions = collections.namedtuple('WebmCrfOptions', 'target_1080_crf audio_quality speed_first speed_second')

from ..tasks import IParallelTask, Resource, ResourceKind
from .base_tasks import EncoderTask, VideoEncodeTask
from .audio import NormalizeStereoTask, AudioEncodeTask, AudioCodecOptions
from .base_encoder import BaseEncoder

class VorbisNormalize(NormalizeStereoTask):
    def _get_codec_options(self):
        return AudioCodecOptions(name='libvorbis', bitrate=None, extra=('-aq', self.media.extra_options.audio_quality))

class VorbisEncode(AudioEncodeTask):
    def _get_codec_options(self):
        return AudioCodecOptions(name='libvorbis', bitrate=None, extra=('-aq', self.media.extra_options.audio_quality))

class Vp9EncodeTask(VideoEncodeTask):
    def __init__(self, encoder: BaseEncoder, is_first_pass: bool):
        VideoEncodeTask.__init__(self, encoder)
        self.is_first_pass = is_first_pass

    def _get_compare_attrs(self):
        return EncoderTask._get_compare_attrs(self) + [self.is_first_pass]

    @property
    def produced_files(self):
        return [self.encoder.make_tempfile('vp9-audio=no')]

    def _make_command(self):
        crf = (self.encoder.CRF_PROP * self.info.get_video_diagonal() ** self.encoder.CRF_POW) * \
                self.media.extra_options.target_1080_crf / self.encoder.CRF_VP9_1080P
        qmax = crf * self.encoder.QMAX_COEFF
        speed = self.media.extra_options.speed_first if self.is_first_pass else self.media.extra_options.speed_second
        passno = 1 if self.is_first_pass else 2

        return [self.encoder.FFMPEG, '-i', self.media.src, '-g', 240,
               '-movflags', '+faststart', '-map', '0:v', '-c:v', 'libvpx-vp9', '-an', '-crf', int(crf),
               '-qmax', int(qmax), '-b:v', 0, '-quality', 'good', '-speed', speed, '-pass', passno,
               '-passlogfile', self.encoder.make_tempfile('ffmpeg2pass', 'log', '-*.log'), '-y'] + self.produced_files

class Vp9CrfEncode1PassTask(Vp9EncodeTask):
    resource = Resource(kind=ResourceKind.CPU, priority=1)
    static_limit = 5
    def __init__(self, encoder: BaseEncoder):
        Vp9EncodeTask.__init__(self, encoder, True)
    def get_limit(self, candidate_tasks, running_tasks):
        pass2count = sum(1 for t in candidate_tasks if isinstance(t, Vp9CrfEncode2PassTask))
        need_lookahead = max(0, Vp9CrfEncode2PassTask.static_limit - pass2count)
        return min(self.static_limit, Vp9CrfEncode2PassTask.static_limit + need_lookahead)

class Vp9CrfEncode2PassTask(Vp9EncodeTask):
    resource = Resource(kind=ResourceKind.CPU, priority=0)
    static_limit = 4
    def __init__(self, encoder: BaseEncoder):
        Vp9EncodeTask.__init__(self, encoder, False)

class VP9CRFEncoder(BaseEncoder):
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

    NormalizeStereo = VorbisNormalize
    AudioEncode = VorbisEncode

    def _make_video_tasks(self):
        return [Vp9CrfEncode1PassTask(self), Vp9CrfEncode2PassTask(self)]

class VP9CRFYTEncoder(VP9CRFEncoder):
    AudioEncode = None # do not keep non-normalized audio tracks
    ExtractSubtitles = None
    SUFFIX = 'YT'
