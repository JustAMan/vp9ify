import re
import os
import hashlib

from .base import MediaEntry, UnknownFile, BadParameters

from ..encoder.vp9crf import VP9CRFEncoder, WebmCrfOptions

class SeriesEpisode(MediaEntry):
    webm_options = WebmCrfOptions(target_1080_crf=24, audio_quality=4, speed_first=5, speed_second=2)
    FORCE_NAME = 'series'
    CONTAINER = 'webm'
    STRIP_SUFFIX = True

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
    def full_name(self):
        return '%s - S%02dE%02d - %s' % (self.series, self.season, self.episode, self.name)

    @property
    def unique_name(self):
        return '%s-%02dx%02d' % (self.prefix, self.season, self.episode)

    @property
    def comparing_key(self):
        return (self.series, self.season, self.episode)

    def make_encode_tasks(self, dest, logpath):
        return VP9CRFEncoder(self, dest, logpath).make_tasks()

    def _get_target_path(self, dest, suffix, ext):
        return os.path.join(dest, self.series, 'S%02d' % self.season, '%s%s.%s' % (self.friendly_name, suffix, ext))

    @classmethod
    def parse(cls, fname, fpath):
        try:
            series, season, episode, name = re.match(r'(.*)\WS(\d+)E(\d+)(?:E\d+)?\W(.*)$', fname).groups()
            season, episode = int(season), int(episode)
        except (AttributeError, ValueError):
            raise UnknownFile()
        return cls(fpath, series, season, episode, name.decode('utf8').encode('ascii', 'backslashreplace'))

    @classmethod
    def parse_forced(cls, fname, fpath, params):
        try:
            parsed = cls.parse(fname, fpath)
        except UnknownFile:
            try:
                series, season, episode, name = re.match(r'(.*)(\d+)[^\d]+(\d+)(.*)$', fname).groups()
                season, episode = int(season), int(episode)
            except (AttributeError, ValueError):
                raise UnknownFile()
        else:
            series, season, episode, name = parsed.series, parsed.season, parsed.episode, parsed.name
        series = params.get('name', series)
        return cls(fpath, series, season, episode, name.decode('utf8').encode('ascii', 'backslashreplace'))
