import re
import os
import hashlib

from .base import MediaEntry, UnknownFile

from ..encoder.vp9crf import VP9CRFEncoder, WebmCrfOptions

class SeriesEpisode(MediaEntry):
    webm_options = WebmCrfOptions(target_1080_crf=24, audio_quality=24, speed_first=5, speed_second=2)

    def __init__(self, src, series, season, episode, name):
        MediaEntry.__init__(self, src)
        self.series = series
        self.season = season
        self.episode = episode
        self.name = name
        self.prefix = ''.join('%02x' % ord(ch) for ch in hashlib.sha256(series).digest()[:2])

    @property
    def friendly_name(self):
        return 'S%02dE%02d - %s' % (self.season, self.episode, self.name)

    @property
    def unique_name(self):
        return '%s-%02dx%02d' % (self.prefix, self.season, self.episode)

    @property
    def comparing_key(self):
        return (self.series, self.season, self.episode)

    def make_encode_tasks(self, dest, logpath):
        return VP9CRFEncoder(self, dest, logpath).make_tasks()

    def __get_target_path(self, dest, ext):
        return os.path.join(dest, self.series, 'S%02d' % self.season, '%s.%s' % (self.friendly_name, ext))

    def get_target_video_path(self, dest):
        return self.__get_target_path(dest, 'webm')

    def get_target_subtitles_path(self, dest, lang):
        return self.__get_target_path(dest, '%s.srt' % lang)

    def get_target_scriptized_path(self, dest):
        return self.__get_target_path(dest, 'sh')

    @classmethod
    def parse(cls, fname, fpath):
        try:
            series, season, episode, name = re.match(r'(.*)\WS(\d+)E(\d+)(?:E\d+)?\W(.*)$', fname).groups()
            season, episode = int(season), int(episode)
        except (AttributeError, ValueError):
            raise UnknownFile()
        return cls(fpath, series, season, episode, name.decode('utf8').encode('ascii', 'backslashreplace'))
