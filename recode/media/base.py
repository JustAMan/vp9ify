from .info import MediaInfo

class MediaEntry(object):
    LUFS_LEVEL = -14
    AUDIO_FREQ = 48000
    AUDIO_BITRATE = '192k'
    AUDIO_QUALITY = 5
    SPEED_FIRST = 4
    SPEED_SECOND = 1

    # Value of -crf for VP9 *if* video would be 1080p (recalculated according to video size)
    TARGET_1080_QUALITY = 23

    class UnknownFile(Exception):
        pass
    class UnhandledMediaType(Exception):
        pass

    def __init__(self, src):
        self.src = src
        self.info = MediaInfo.parse(src)
        self.tempfiles = []

    def get_target_video_path(self, dest):
        raise NotImplementedError()

    def get_target_subtitles_path(self, dest, lang):
        raise NotImplementedError()
    
    @property
    def friendly_name(self):
        raise NotImplementedError()

    @property
    def short_name(self):
        raise NotImplementedError()

    @property
    def comparing_key(self):
        raise NotImplementedError()

    def __eq__(self, other):
        if not isinstance(other, MediaEntry):
            return NotImplemented
        return self.comparing_key == other.comparing_key

    @classmethod
    def parse(cls, fname, fpath):
        raise NotImplementedError()
