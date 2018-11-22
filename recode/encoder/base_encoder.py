import tempfile
import os
import logging

from ..helpers import which, ensuredir
from ..media.info import MediaInfo

from .base_tasks import RemoveScriptTask, RemuxTask, ExtractSubtitlesTask, CleanupTempfiles
from .audio import ExtractStereoAudioTask, DownmixToStereoTask, NormalizeStereoTask, AudioEncodeTask

class MediaEncoder(object):
    FFMPEG = which('ffmpeg', 'FFMPEG_PATH')
    FFMPEG_NORM = which('ffmpeg-normalize', 'FFMPEG_NORM_PATH')
    MKVEXTRACT = which('mkvextract')

    def __init__(self, media, dest, stdout=None):
        self.media = media
        self.src = media.src
        self.info = MediaInfo.parse(self.src)
        self.tempfiles = []
        self.patterns = []
        self.dest = dest
        self.stdout = stdout or None

    def __eq__(self, other):
        if not isinstance(other, MediaEncoder):
            return False
        return self.media == other.media

    def __ne__(self, other):
        return not (self == other)

    def make_tempfile(self, suffix='', ext='mkv', glob_suffix=None):
        tmpdir = tempfile.gettempdir()
        ensuredir(tmpdir)
        path = os.path.join(tmpdir, '%s.%s.%s' % (self.media.friendly_name, suffix, ext))
        if path not in self.tempfiles:
            self.tempfiles.append(path)
        if glob_suffix:
            pattern = path + glob_suffix
            if pattern not in self.patterns:
                self.patterns.append(pattern)
        return path

    def _make_video_tasks(self):
        raise NotImplementedError()

    def _make_audio_tasks(self):
        audio_tasks = []
        for track_id, channel_count in self.info.get_audio_channels().items():
            if track_id in self.media.ignored_audio_tracks:
                logging.info('Skipping audio track %d in "%s"' % (track_id, self.media.friendly_name))
                continue

            if channel_count == 2:
                prepare_2ch_task = ExtractStereoAudioTask(self, track_id)
            else:
                prepare_2ch_task = DownmixToStereoTask(self, track_id)
                audio_tasks.append(AudioEncodeTask(self, track_id))
            audio_tasks.extend([prepare_2ch_task, NormalizeStereoTask(self, track_id, prepare_2ch_task)])
        return audio_tasks

    def make_tasks(self):
        video_tasks = self._make_video_tasks()
        audio_tasks = self._make_audio_tasks()
        remux_task = RemuxTask(self, video_tasks, audio_tasks)
        return [RemoveScriptTask(self)] + video_tasks + audio_tasks + [remux_task,
                ExtractSubtitlesTask(self), CleanupTempfiles(self, remux_task)]
