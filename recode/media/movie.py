import hashlib
import os
import typing

from .base import MediaEntry, UnknownFile, BadParameters, ParameterDescription
from ..helpers import override_fields, list_named_fields
from ..encoder.vp9crf import WebmCrfOptions, VP9CRFEncoder, VP9CRFYTEncoder
from ..encoder.mkvcrf import MkvCrfOptions, MKVCRFEncoder, MKVCRFLowEncoder

class BaseMovie(MediaEntry):
    extra_options = None
    FORCE_NAME = 'basemovie'
    CONTAINER = 'nothing'
    ENCODER = None

    def __init__(self, src: str, name: str):
        MediaEntry.__init__(self, src)
        self.name = name
        self.prefix = ''.join('%02x' % ch for ch in hashlib.sha256(name.encode('utf-8')).digest()[:2])

    @property
    def friendly_name(self):
        return self.name

    @property
    def full_name(self):
        return self.name

    @property
    def unique_name(self):
        return '%s-%s' % (self.name[:20].strip(), self.prefix)

    @property
    def comparing_key(self):
        return self.name.lower()

    def make_encode_tasks(self, dest, logpath, drop_video):
        return self.ENCODER(self, dest, logpath, drop_video).make_tasks() #pylint: disable=not-callable

    def _get_target_path(self, dest, suffix, ext):
        return os.path.join(dest, '%s%s.%s' % (self.friendly_name, suffix, ext))

    @classmethod
    def parse(cls, fname: str, fpath: str) -> MediaEntry:
        return cls(fpath, fname)

    @classmethod
    def parse_forced(cls, fname: str, fpath: str, params: typing.Dict[str, str]) -> MediaEntry:
        res = cls(fpath, params.get('name', fname))
        try:
            res.extra_options = override_fields(cls.extra_options, params)
        except ValueError:
            raise BadParameters('Got not an integer value trying to override int parameter')
        return res

    @classmethod
    def describe_parameters(cls):
        res = [ParameterDescription(group=cls.CONTAINER, key=key, kind=kind, help='(default: %s)' % value) for (key, kind, value) in list_named_fields(cls.extra_options)]
        res.append(ParameterDescription(group='', key='name', kind='string', help='Movie name'))
        return res

    @classmethod
    def parse_parameters(cls, param_str, targets_multiple_sources):
        params = MediaEntry.parse_parameters(param_str, targets_multiple_sources)
        if targets_multiple_sources and 'name' in params:
            raise BadParameters('Can not set "name" when targeting multiple movies')
        return params

class SingleMovie(BaseMovie):
    extra_options = WebmCrfOptions(target_1080_crf=21, audio_quality=5, speed_first=4, speed_second=1)
    FORCE_NAME = 'movie'
    CONTAINER = 'webm'
    ENCODER = VP9CRFEncoder

class HQMovie(BaseMovie):
    extra_options = MkvCrfOptions(crf=20, preset='slower', scale_down=0, audio_quality=5, audio_profile='')
    FORCE_NAME = 'hqmovie'
    CONTAINER = 'mkv'
    ENCODER = MKVCRFEncoder

class LQMovie(BaseMovie):
    extra_options = MkvCrfOptions(crf=30, preset='slow', scale_down=720, audio_quality=2, audio_profile='aac_he_v2')
    FORCE_NAME = 'lqmovie'
    CONTAINER = 'mp4'
    ENCODER = MKVCRFLowEncoder

class YTLike(BaseMovie):
    extra_options = WebmCrfOptions(target_1080_crf=32, audio_quality=4, speed_first=5, speed_second=2)
    FORCE_NAME = 'ytlike'
    CONTAINER = 'webm'
    ENCODER = VP9CRFYTEncoder
