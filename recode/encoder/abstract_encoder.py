import os
import tempfile

from ..helpers import which, chop_tail, ensuredir
from ..media.info import MediaInfo
from ..media.base import MediaEntry


class AbstractEncoder(object):
    FFMPEG = which('ffmpeg', 'FFMPEG_PATH')
    FFMPEG_NORM = which('ffmpeg-normalize', 'FFMPEG_NORM_PATH')
    MKVEXTRACT = which('mkvextract')
    SUFFIX = ''

    def __init__(self, media: MediaEntry, dest: str, stdout: str=None, drop_video: bool=False):
        self.media = media
        self.src = media.src
        self.info = MediaInfo.parse(self.src)
        self.tempfiles = []
        self.patterns = []
        self.dest = dest
        self.stdout = stdout or None
        self.drop_video = drop_video

    def _get_tmp_prefix(self):
        return chop_tail(self.__class__.__name__, 'Encoder').lower()

    def make_tempfile(self, suffix: str='', ext: str='mkv', glob_suffix: str=None) -> str:
        tmpdir = tempfile.gettempdir()
        ensuredir(tmpdir)
        if self.SUFFIX:
            suffix = '%s[%s]' % (suffix, self.SUFFIX)
        path = os.path.join(tmpdir, '%s-%s.%s.%s' % (self._get_tmp_prefix(), self.media.unique_name, suffix, ext))
        if path not in self.tempfiles:
            self.tempfiles.append(path)
        if glob_suffix:
            pattern = path + glob_suffix
            if pattern not in self.patterns:
                self.patterns.append(pattern)
        return path