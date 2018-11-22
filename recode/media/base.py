from .info import MediaInfo
from ..helpers import input_numbers, confirm_yesno

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

    def __init__(self, src):
        self.src = src
        self.info = MediaInfo.parse(src)
        self.ignored_audio_tracks = set()

    def get_target_video_path(self, dest, suffix='', container='mkv'):
        raise NotImplementedError()

    def get_target_subtitles_path(self, dest, lang):
        raise NotImplementedError()

    def get_target_scriptized_path(self, dest):
        raise NotImplementedError()
    
    @property
    def friendly_name(self):
        raise NotImplementedError()

    @property
    def full_name(self):
        return self.friendly_name

    @property
    def unique_name(self):
        raise NotImplementedError()

    @property
    def comparing_key(self):
        raise NotImplementedError()

    def make_encode_tasks(self, dest, logpath):
        raise NotImplementedError()

    def __eq__(self, other):
        if not isinstance(other, MediaEntry):
            return False
        return self.comparing_key == other.comparing_key

    def __ne__(self, other):
        return not (self == other)

    @classmethod
    def parse(cls, fname, fpath):
        raise NotImplementedError()

    @classmethod
    def parse_forced(cls, fname, fpath, params):
        raise NotImplementedError()

    @classmethod
    def parse_parameters(cls, param_str):
        raise NotImplementedError()

    def interact(self):
        audio = sorted(self.info.get_audio_tracks(), key=lambda ainfo: ainfo.track_id)
        if audio:
            print 'Audio tracks available in "%s":' % self.friendly_name
            for idx, ainfo in enumerate(audio):
                print '  % 2d. [%s] %s (%d channels)' % (idx + 1, ainfo.language, ainfo.name, ainfo.channels)
            while True:
                to_keep = input_numbers('Input track numbers to keep', 1, len(audio))
                print 'Tracks to keep'
                for idx in to_keep:
                    print '  [%s] %s (%d channels)' % (audio[idx - 1].language, audio[idx - 1].name, audio[idx - 1].channels)
                if confirm_yesno('Are tracks selected correctly?'):
                    break
        keep_ids = set(audio[idx - 1].track_id for idx in to_keep)
        self.ignored_audio_tracks = set(ainfo.track_id for ainfo in audio) - keep_ids
