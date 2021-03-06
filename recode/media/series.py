import re
import os
import hashlib
import typing

from .base import MediaEntry, UnknownFile, BadParameters, ParameterDescription
from ..helpers import override_fields, list_named_fields

from ..encoder.vp9crf import VP9CRFEncoder, WebmCrfOptions

class SeriesEpisode(MediaEntry):
    extra_options = WebmCrfOptions(target_1080_crf=24, audio_quality=4, speed_first=5, speed_second=2)
    FORCE_NAME = 'series'
    CONTAINER = 'webm'
    STRIP_SUFFIX = True

    def __init__(self, src: str, series: str, season: int, episode: int, name: str):
        MediaEntry.__init__(self, src)
        self.series = series
        self.season = season
        self.episode = episode
        self.name = name
        self.prefix = ''.join('%02x' % ch for ch in hashlib.sha256(series.encode('utf-8')).digest()[:2])

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

    def make_encode_tasks(self, dest, logpath, drop_video):
        return VP9CRFEncoder(self, dest, logpath, drop_video).make_tasks()

    def _get_target_path(self, dest, suffix, ext):
        return os.path.join(dest, self.series, 'S%02d' % self.season, '%s%s.%s' % (self.friendly_name, suffix, ext))

    @classmethod
    def parse(cls, fname: str, fpath: str) -> MediaEntry:
        try:
            series, season, episode, name = re.match(r'(.*)\WS(\d+)E(\d+)(?:E\d+)?\W(.*)$', fname, re.IGNORECASE).groups()
            season, episode = int(season), int(episode)
        except (AttributeError, ValueError):
            raise UnknownFile()
        return cls(fpath, series, season, episode, name)

    @classmethod
    def parse_forced(cls, fname: str, fpath: str, params: dict) -> MediaEntry:
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
        res = cls(fpath, series, season, episode, name)
        try:
            res.extra_options = override_fields(cls.extra_options, params)
        except ValueError:
            raise BadParameters('Got not an integer value trying to override int parameter')
        return res

    @classmethod
    def describe_parameters(cls):
        res = [ParameterDescription(group=cls.CONTAINER, key=key, kind=kind, help='(default: %s)' % value) for (key, kind, value) in list_named_fields(cls.extra_options)]
        res.append(ParameterDescription(group='', key='name', kind='string', help='Series name'))
        return res
