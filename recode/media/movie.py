import hashlib
import os

from .base import MediaEntry, UnknownFile, BadParameters
from ..helpers import override_int_fields
from ..encoder.vp9crf import WebmCrfOptions, VP9CRFEncoder

class SingleMovie(MediaEntry):
    webm_options = WebmCrfOptions(target_1080_crf=21, audio_quality=5, speed_first=4, speed_second=1)
    FORCE_NAME = 'movie'
    CONTAINER = 'webm'

    def __init__(self, src, name):
        MediaEntry.__init__(self, src)
        self.name = name
        self.prefix = ''.join('%02x' % ord(ch) for ch in hashlib.sha256(name).digest()[:2])

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

    def make_encode_tasks(self, dest, logpath):
        return VP9CRFEncoder(self, dest, logpath).make_tasks()

    def _get_target_path(self, dest, suffix, ext):
        return os.path.join(dest, '%s%s.%s' % (self.friendly_name, suffix, ext))

    @classmethod
    def parse(cls, fname, fpath):
        return cls(fpath, fname)

    @classmethod
    def parse_forced(cls, fname, fpath, params):
        res = cls(fpath, params.get('name', fname))
        try:
            res.webm_options = override_int_fields(cls.webm_options, params)
        except ValueError:
            raise BadParameters('Got not an integer value trying to override int parameter')
        return res

