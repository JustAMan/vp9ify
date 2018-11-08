import re
import os

from .base import MediaEntry

class SeriesEpisode(MediaEntry):
    TARGET_1080_QUALITY = 24
    AUDIO_QUALITY = 4
    AUDIO_BITRATE = '128k'
    SPEED_FIRST = 5
    SPEED_SECOND = 2

    def __init__(self, src, series, season, episode, name):
        MediaEntry.__init__(self, src)
        self.series = series
        self.season = season
        self.episode = episode
        self.name = name

    @property
    def friendly_name(self):
        return 'S%02dE%02d - %s' % (self.season, self.episode, self.name)

    @property
    def short_name(self):
        return '%02dx%02d' % (self.season, self.episode)

    @property
    def comparing_key(self):
        return (self.series, self.season, self.episode)

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
            raise cls.UnknownFile()
        return cls(fpath, series, season, episode, name.decode('utf8').encode('ascii', 'backslashreplace'))
