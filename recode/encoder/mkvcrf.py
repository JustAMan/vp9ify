import collections
import subprocess
import sys

from .audio import NormalizeStereoTask, AudioEncodeTask, AudioCodecOptions, AudioBaseTask
from .base_encoder import BaseEncoder
from .base_tasks import VideoEncodeTask, RemuxTask

MkvCrfOptions = collections.namedtuple('MkvCrfOptions', 'crf preset audio_quality audio_profile scale_down')

_HAS_FDK = None
def has_fdk(encoder: BaseEncoder) -> bool:
    global _HAS_FDK
    if _HAS_FDK is not None:
        return _HAS_FDK
    try:
        out = subprocess.check_output([encoder.FFMPEG, '-encoders'], stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as err:
        sys.exit('Cannot get ffmpeg encoders: %s' % err.output)
    _HAS_FDK = 'libfdk_aac' in out.decode('utf8')
    return _HAS_FDK

def _get_aac_options(task: AudioBaseTask):
    extra = ['-vbr', task.media.extra_options.audio_quality, '-movflags', '+faststart']
    if task.media.extra_options.audio_profile and has_fdk(task.encoder):
        extra.extend(['-profile:a', task.media.extra_options.audio_profile, '-cutoff', task.media.AUDIO_FREQ])
    return AudioCodecOptions(name='libfdk_aac' if has_fdk(task.encoder) else 'aac', bitrate=None, extra=extra)

class AacNormalize(NormalizeStereoTask):
    _get_codec_options = _get_aac_options

class AacEncode(AudioEncodeTask):
    _get_codec_options = _get_aac_options

class HevcEncodeTask(VideoEncodeTask):
    @property
    def produced_files(self):
        return [self.encoder.make_tempfile('hevc-audio=no')]

    def _get_scaling(self):
        if not self.media.extra_options.scale_down:
            return []
        opts = [('force_original_aspect_ratio', 'decrease'),
                ('force_divisible_by', 8),
                ('height', self.media.extra_options.scale_down),
                ('width', -1)]
        return ['-vf', 'scale=' + ':'.join('%s=%s' % pair for pair in opts)]

    def _make_command(self):
        return [self.encoder.FFMPEG, '-i', self.media.src,
               '-movflags', '+faststart', '-map', '0:v', '-c:v', 'libx265', '-an', '-crf', int(self.media.extra_options.crf),
               '-x265-params', 'no-sao=1:rskip=1:keyint=120:min-keyint=24:rc-lookahead=120:bframes=12:aq-mode=3:no-strong-intra-smoothing=1:no-open-gop=1',
               '-preset', self.media.extra_options.preset] + self._get_scaling() + ['-y'] + self.produced_files

class MKVCRFEncoder(BaseEncoder):
    NormalizeStereo = AacNormalize
    AudioEncode = AacEncode

    def _make_video_tasks(self):
        return [HevcEncodeTask(self)]

class MKVCRFLowEncoder(MKVCRFEncoder):
    AudioEncode = None # do not keep non-normalized audio tracks
    ExtractSubtitles = None
    SUFFIX = 'LQ'
