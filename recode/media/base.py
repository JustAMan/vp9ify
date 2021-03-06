import re
import collections
import typing

from .info import MediaInfo
from ..helpers import input_numbers, confirm_yesno

ParameterDescription = collections.namedtuple('ParameterDescription', 'group key kind help')

class UnknownFile(Exception):
    pass
class BadParameters(Exception):
    def __init__(self, msg):
        Exception.__init__(self)
        self.msg = msg

class MediaEntry(object):
    LUFS_LEVEL = -14
    AUDIO_FREQ = 48000
    FORCE_NAME = None
    CONTAINER = 'mkv'
    STRIP_SUFFIX = False

    def __init__(self, src: str):
        self.src = src
        self.info = MediaInfo.parse(src)
        self.ignored_audio_tracks = set()

    def _get_target_path(self, dest, suffix, ext):
        raise NotImplementedError()

    def get_target_video_path(self, dest: str, suffix :str='', container: str=None) -> str:
        if suffix:
            suffix = ' [%s]' % suffix
        return self._get_target_path(dest, suffix, container or self.CONTAINER)

    def get_target_subtitles_path(self, dest: str, lang: str) -> str:
        return self._get_target_path(dest, '', '%s.srt' % lang)

    def get_target_scriptized_path(self, dest: str, suffix: str='') -> str:
        return self._get_target_path(dest, suffix, 'sh')

    @property
    def friendly_name(self) -> str:
        raise NotImplementedError()

    @property
    def full_name(self) -> str:
        return self.friendly_name

    @property
    def unique_name(self) -> str:
        raise NotImplementedError()

    @property
    def comparing_key(self):
        raise NotImplementedError()

    def make_encode_tasks(self, dest: str, logpath: str, drop_video: bool=False):
        raise NotImplementedError()

    def __eq__(self, other):
        if not isinstance(other, MediaEntry):
            return False
        return self.comparing_key == other.comparing_key

    def __ne__(self, other):
        return not (self == other)

    @classmethod
    def parse(cls, fname: str, fpath: str):
        raise NotImplementedError()

    @classmethod
    def parse_forced(cls, fname: str, fpath: str, params: dict):
        raise NotImplementedError()

    @classmethod
    def parse_parameters(cls, param_str: str, targets_multiple_sources: bool) -> dict:
        result = {}
        while param_str:
            try:
                key, value, rest = re.match(r'[:\s]*(\w+)\s*=\s*(.*?)(?<!\\)(:.*|)$', param_str).groups()
            except AttributeError:
                raise BadParameters('Parameters should be in "foo=bar:baz=qux" form')
            result[key.lower()] = value.replace('\\\\', '\\').strip()
            param_str = rest
        return result

    @classmethod
    def describe_parameters(cls) -> typing.List[ParameterDescription]:
        raise NotImplementedError()

    def interact(self):
        audio = sorted(self.info.get_audio_tracks(), key=lambda ainfo: ainfo.track_id)
        if audio:
            print('Audio tracks available in "%s":' % self.friendly_name)
            for idx, ainfo in enumerate(audio):
                print('  % 2d. [%s] %s (%d channels)' % (idx + 1, ainfo.language, ainfo.name, ainfo.channels))
            while True:
                to_keep = input_numbers('Input track numbers to keep', 1, len(audio))
                print('Tracks to keep')
                for idx in to_keep:
                    print('  [%s] %s (%d channels)' % (audio[idx - 1].language, audio[idx - 1].name, audio[idx - 1].channels))
                if confirm_yesno('Are tracks selected correctly?'):
                    break
        keep_ids = set(audio[idx - 1].track_id for idx in to_keep)
        self.ignored_audio_tracks = set(ainfo.track_id for ainfo in audio) - keep_ids
