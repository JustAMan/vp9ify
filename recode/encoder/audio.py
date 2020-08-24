import collections
import subprocess

AudioCodecOptions = collections.namedtuple('AudioCodecOptions', 'name bitrate extra')

from ..tasks import IParallelTask, Resource, ResourceKind
from .base_tasks import EncoderTask
from .abstract_encoder import AbstractEncoder

class AudioBaseTask(EncoderTask):
    def __init__(self, encoder: AbstractEncoder, track_id: int):
        EncoderTask.__init__(self, encoder)
        self.track_id = track_id

    def _get_compare_attrs(self):
        return EncoderTask._get_compare_attrs(self) + [self.track_id]

    def _get_codec_options(self):
        raise NotImplementedError()

    @property
    def name(self):
        return '%s-track=%d' % (self._get_name(), self.track_id)

class ExtractStereoAudioTask(AudioBaseTask):
    resource = Resource(kind=ResourceKind.IO, priority=1)
    static_limit = 2
    def __init__(self, encoder: AbstractEncoder, track_id: int):
        AudioBaseTask.__init__(self, encoder, track_id)
        # this only extracts stereo
        assert self.info.get_audio_channels()[track_id] <= 2

    @property
    def produced_files(self):
        return [self.encoder.make_tempfile('audio-%d-2ch' % self.track_id)]

    def _make_command(self):
        return [self.encoder.FFMPEG, '-i', self.media.src,
                '-map', '0:%d:0' % self.track_id, '-c:a', 'copy', '-vn',
                '-y'] + self.produced_files

class DownmixToStereoTask(AudioBaseTask):
    ''' Extract non-stereo audio tracks with downmixing to stereo for normalizing, so that we have all tracks
    that are normalized (normalizing a properly designed 5.1 audio means destroying its quality, but
    having each instance of original audio as normalized stereo helps when watching on simple, non-5.1-enabled hardware) '''
    resource = Resource(kind=ResourceKind.CPU, priority=2)
    static_limit = 6
    def __init__(self, encoder: AbstractEncoder, track_id: int):
        AudioBaseTask.__init__(self, encoder, track_id)
        # this only works with non-stereo
        assert self.info.get_audio_channels()[track_id] > 2

    @property
    def produced_files(self):
        return [self.encoder.make_tempfile('audio-%d-2ch' % self.track_id)]

    def _make_command(self):
        return [self.encoder.FFMPEG, '-i', self.media.src,
                '-map', '0:%d:0' % self.track_id, '-c:a', 'aac', '-b:a', '512k',
                '-ac', 2, '-af', 'pan=stereo|FL < 1.0*FL + 0.707*FC + 0.707*BL|FR < 1.0*FR + 0.707*FC + 0.707*BR',
                '-vn', '-y'] + self.produced_files

class NormalizeStereoTask(AudioBaseTask):
    resource = Resource(kind=ResourceKind.CPU, priority=2)
    static_limit = 6
    def __init__(self, encoder: AbstractEncoder, track_id: int, parent_task: AudioBaseTask):
        AudioBaseTask.__init__(self, encoder, track_id)
        self.blockers.append(parent_task.name)

    @property
    def produced_files(self):
        return [self.encoder.make_tempfile('audio-%d-2ch' % self.track_id)]

    def _make_command(self):
        options = self._get_codec_options()
        bitrate = ['-b:a', options.bitrate] if options.bitrate else []
        extra = ['-e=%s' % subprocess.list2cmdline(str(x) for x in options.extra)] if options.extra else []
        return [self.encoder.FFMPEG_NORM, self.produced_files[0],
                '-c:a', options.name] + bitrate + extra + ['--dual-mono',
                '-t', self.media.LUFS_LEVEL, '-f', '-ar', self.media.AUDIO_FREQ,
                '-vn', '-o'] + self.produced_files

class AudioEncodeTask(AudioBaseTask):
    resource = Resource(kind=ResourceKind.CPU, priority=2)
    static_limit = 6
    def __init__(self, encoder: AbstractEncoder, track_id: int):
        AudioBaseTask.__init__(self, encoder, track_id)
        # encoding without normalization is applied to non-stereo only
        assert self.info.get_audio_channels()[track_id] != 2

    @property
    def produced_files(self):
        return [self.encoder.make_tempfile('audio-%d' % self.track_id)]

    def _make_command(self):
        options = self._get_codec_options()
        bitrate = ['-b:a', options.bitrate] if options.bitrate else []
        extra = list(options.extra) if options.extra else []
        return [self.encoder.FFMPEG, '-i', self.media.src,
                '-map', '0:%d:0' % self.track_id, '-vn',
                '-c:a', options.name] + bitrate + extra + ['-y'] + self.produced_files
