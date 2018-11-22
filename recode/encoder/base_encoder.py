import tempfile
import os
import logging

from ..helpers import which, ensuredir, chop_tail
from ..media.info import MediaInfo

from .base_tasks import RemoveScriptTask, RemuxTask, ExtractSubtitlesTask, CleanupTempfiles
from .audio import ExtractStereoAudioTask, DownmixToStereoTask, NormalizeStereoTask, AudioEncodeTask

class BaseEncoder(object):
    FFMPEG = which('ffmpeg', 'FFMPEG_PATH')
    FFMPEG_NORM = which('ffmpeg-normalize', 'FFMPEG_NORM_PATH')
    MKVEXTRACT = which('mkvextract')

    NormalizeStereo = NormalizeStereoTask
    AudioEncode = AudioEncodeTask
    ExtractSubtitles = ExtractSubtitlesTask
    Remux = RemuxTask

    def __init__(self, media, dest, stdout=None):
        self.media = media
        self.src = media.src
        self.info = MediaInfo.parse(self.src)
        self.tempfiles = []
        self.patterns = []
        self.dest = dest
        self.stdout = stdout or None

    def __eq__(self, other):
        if not isinstance(other, BaseEncoder):
            return False
        return self.media == other.media

    def __ne__(self, other):
        return not (self == other)

    def _get_tmp_prefix(self):
        return chop_tail(self.__class__.__name__, 'Encoder').lower()

    def make_tempfile(self, suffix='', ext='mkv', glob_suffix=None):
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

    def _make_video_tasks(self):
        raise NotImplementedError()

    def _make_audio_track_tasks(self, audio_info):
        audio_tasks = []
        if audio_info.channels == 2:
            prepare_2ch_task = ExtractStereoAudioTask(self, audio_info.track_id)
        else:
            prepare_2ch_task = DownmixToStereoTask(self, audio_info.track_id)
            if self.AudioEncode:
                audio_tasks.append(self.AudioEncode(self, audio_info.track_id))
        audio_tasks.extend([prepare_2ch_task, self.NormalizeStereo(self, audio_info.track_id, prepare_2ch_task)])
        return audio_tasks

    def _make_audio_tasks(self):
        audio_tasks = []
        for audio_info in self.info.get_audio_tracks():
            if audio_info.track_id in self.media.ignored_audio_tracks:
                logging.info('Skipping audio track %d in "%s"' % (audio_info.track_id, self.media.friendly_name))
                continue
            audio_tasks.extend(self._make_audio_track_tasks(audio_info))
        return audio_tasks

    def make_tasks(self):
        video_tasks = self._make_video_tasks()
        audio_tasks = self._make_audio_tasks()
        remux_task = self.Remux(self, video_tasks, audio_tasks)
        extract_subs = [self.ExtractSubtitles(self)] if self.ExtractSubtitles else []
        return [RemoveScriptTask(self)] + video_tasks + audio_tasks + [remux_task] + \
                extract_subs + [CleanupTempfiles(self, remux_task)]
