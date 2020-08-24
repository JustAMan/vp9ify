import tempfile
import os
import logging
import typing

from ..helpers import which, ensuredir, chop_tail
from ..media.info import MediaInfo, AudioInfo
from ..media.base import MediaEntry

from .abstract_encoder import AbstractEncoder
from .base_tasks import EncoderTask, RemoveScriptTask, RemuxTask, ExtractSubtitlesTask, CleanupTempfiles
from .audio import AudioBaseTask, ExtractStereoAudioTask, DownmixToStereoTask, NormalizeStereoTask, AudioEncodeTask

class BaseEncoder(AbstractEncoder):
    NormalizeStereo = NormalizeStereoTask
    AudioEncode = AudioEncodeTask
    ExtractSubtitles = ExtractSubtitlesTask
    Remux = RemuxTask

    def __eq__(self, other):
        if not isinstance(other, BaseEncoder):
            return False
        return self.media == other.media

    def __ne__(self, other):
        return not (self == other)

    def _get_tmp_prefix(self):
        return chop_tail(self.__class__.__name__, 'Encoder').lower()

    def make_tempfile(self, suffix: str='', ext: str='mkv', glob_suffix: str=None) -> str:
        tmpdir = tempfile.gettempdir()
        ensuredir(tmpdir)
        path = os.path.join(tmpdir, '%s-%s.%s.%s' % (self._get_tmp_prefix(), self.media.unique_name, suffix, ext))
        if path not in self.tempfiles:
            self.tempfiles.append(path)
        if glob_suffix:
            pattern = path + glob_suffix
            if pattern not in self.patterns:
                self.patterns.append(pattern)
        return path

    def _make_video_tasks(self) -> typing.List[EncoderTask]:
        raise NotImplementedError()

    def _make_audio_track_tasks(self, audio_info: AudioInfo) -> typing.Tuple[typing.List[AudioBaseTask], typing.List[AudioBaseTask]]:
        intermediate, output = [], []
        if audio_info.channels <= 2:
            prepare_2ch_task = ExtractStereoAudioTask(self, audio_info.track_id)
        else:
            prepare_2ch_task = DownmixToStereoTask(self, audio_info.track_id)
        output.append(self.NormalizeStereo(self, audio_info.track_id, prepare_2ch_task))
        if audio_info.channels > 2 and self.AudioEncode:
            output.append(self.AudioEncode(self, audio_info.track_id))
        intermediate.append(prepare_2ch_task)
        return intermediate, output

    def _make_audio_tasks(self) -> typing.Tuple[typing.List[AudioBaseTask], typing.List[AudioBaseTask]]:
        intermediate, output = [], []
        for audio_info in self.info.get_audio_tracks():
            if audio_info.track_id in self.media.ignored_audio_tracks:
                logging.info('Skipping audio track %d in "%s"' % (audio_info.track_id, self.media.friendly_name))
                continue
            track_intermediate, track_output = self._make_audio_track_tasks(audio_info)
            intermediate.extend(track_intermediate)
            output.extend(track_output)
        return intermediate, output

    def make_tasks(self) -> typing.List[EncoderTask]:
        video_tasks = self._make_video_tasks() if not self.drop_video else []
        audio_tasks_intermediate, audio_tasks_output = self._make_audio_tasks()
        remux_task = self.Remux(self, video_tasks, audio_tasks_output)
        extract_subs = [self.ExtractSubtitles(self)] if self.ExtractSubtitles else []
        return [RemoveScriptTask(self)] + video_tasks + audio_tasks_intermediate + \
                audio_tasks_output + [remux_task] + extract_subs + [CleanupTempfiles(self, remux_task)]
