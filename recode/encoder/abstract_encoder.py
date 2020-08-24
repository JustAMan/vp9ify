from ..helpers import which
from ..media.info import MediaInfo
from ..media.base import MediaEntry


class AbstractEncoder(object):
    FFMPEG = which('ffmpeg', 'FFMPEG_PATH')
    FFMPEG_NORM = which('ffmpeg-normalize', 'FFMPEG_NORM_PATH')
    MKVEXTRACT = which('mkvextract')

    def __init__(self, media: MediaEntry, dest: str, stdout: str=None, drop_video: bool=False):
        self.media = media
        self.src = media.src
        self.info = MediaInfo.parse(self.src)
        self.tempfiles = []
        self.patterns = []
        self.dest = dest
        self.stdout = stdout or None
        self.drop_video = drop_video
