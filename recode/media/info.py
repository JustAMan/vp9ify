import collections
import sys
import subprocess
import json
import math
import typing

from ..helpers import which

SubtitleInfo = collections.namedtuple('SubtitleInfo', 'track_id name language')
AudioInfo = collections.namedtuple('AudioInfo', 'track_id name language channels')

class MediaInfo:
    def __init__(self, path: str, info: dict, tracks: list):
        self.path = path
        self.info = info
        self.tracks = tracks
    
    @classmethod
    def parse(cls, path: str):
        if sys.platform == 'win32':
            out = r'''{"errors": [], "container": {"supported": true, "type": "Matroska", "properties": {"writing_application": "Lavf57.56.101", "segment_uid": "942fb317ab2287c02b79c8008e699b40", "muxing_application": "Lavf57.56.101", "container_type": 17, "date_utc": "2001-01-01T00:00:00Z", "date_local": "2001-01-01T03:00:00+03:00", "is_providing_timecodes": true, "duration": 31141000000}, "recognized": true}, "attachments": [], "warnings": [], "file_name": "30sec.mkv", "identification_format_version": 6, "chapters": [], "global_tags": [{"num_entries": 1}], "track_tags": [], "tracks": [{"codec": "MPEG-4p10/AVC/h.264", "type": "video", "id": 0, "properties": {"packetizer": "mpeg4_p10_video", "forced_track": false, "uid": 1, "language": "eng", "number": 1, "enabled_track": true, "pixel_dimensions": "1920x1080", "display_dimensions": "1920x1080", "codec_id": "V_MPEG4/ISO/AVC", "codec_private_data": "01640028ffe1001a67640028acd940780227e5c04400000301f400005daa3c60c65801000668e938233c8f", "codec_private_length": 43, "default_track": true, "minimum_timestamp": 4948000000, "default_duration": 41708375}}, {"codec": "AC-3/E-AC-3", "type": "audio", "id": 1, "properties": {"audio_channels": 2, "uid": 2, "language": "rus", "track_name": "\u0434\u043e\u0440\u043e\u0436\u043a\u04301", "number": 2, "enabled_track": true, "forced_track": true, "codec_id": "A_AC3", "codec_private_length": 0, "audio_sampling_frequency": 48000, "default_track": true, "minimum_timestamp": 0}}, {"codec": "AC-3/E-AC-3", "type": "audio", "id": 2, "properties": {"audio_channels": 6, "uid": 3, "language": "rus", "track_name": "track2", "number": 3, "enabled_track": true, "forced_track": false, "codec_id": "A_AC3", "codec_private_length": 0, "audio_sampling_frequency": 48000, "default_track": false, "minimum_timestamp": 0}}, {"codec": "DTS", "type": "audio", "id": 3, "properties": {"audio_channels": 6, "uid": 4, "language": "eng", "number": 4, "enabled_track": true, "forced_track": false, "codec_id": "A_DTS", "codec_private_length": 0, "audio_sampling_frequency": 48000, "default_track": false, "minimum_timestamp": 10000000}}, {"codec": "HDMV PGS", "type": "subtitles", "id": 4, "properties": {"forced_track": false, "uid": 5, "language": "rus", "number": 5, "enabled_track": true, "track_name": "subs1", "codec_id": "S_HDMV/PGS", "codec_private_length": 0, "default_track": false, "minimum_timestamp": 235000000}}, {"codec": "SubRip/SRT", "type": "subtitles", "id": 5, "properties": {"forced_track": false, "uid": 6, "language": "eng", "number": 6, "enabled_track": true, "text_subtitles": true, "codec_id": "S_TEXT/UTF8", "codec_private_length": 0, "default_track": false, "minimum_timestamp": 485000000}}]}'''
        else:
            try:
                out = subprocess.check_output([which('mkvmerge'), '-J', path]).decode()
            except subprocess.CalledProcessError as err:
                raise ValueError('Cannot get MKV info for "%s": "%s" ("%r")' % (path, err, err))
        info = json.loads(out)
        try:
            tracks = info['tracks']
        except KeyError:
            raise ValueError('Missing required entry in movie info for "%s"' % path)

        return cls(path, info, tracks)

    @staticmethod
    def __get_unique_name(name, seen):
        if name in seen:
            idx = 1
            while '%s_%d' % (name, idx) in seen:
                idx += 1
            name = '%s_%d' % (name, idx)
        seen.add(name)
        return name

    def get_subtitles(self) -> typing.List[SubtitleInfo]:
        result = []
        seen_names, seen_langs = set(), set()
        for track in self.tracks:
            if track['codec'] == 'SubRip/SRT':
                lang = track['properties']['language']
                name = track['properties'].get('track_name', lang)
                lang = self.__get_unique_name(lang, seen_langs)
                name = self.__get_unique_name(name, seen_names)
                result.append(SubtitleInfo(track_id=track['id'],
                                           name=name, language=lang))
        return result

    def get_audio_channels(self) -> typing.Dict[int, int]:
        '''
        Maps track id to channels count
        '''
        result = {}
        for track in self.tracks:
            if int(track.get('properties', {}).get('audio_channels', -1)) != -1:
                result[int(track['id'])] = int(track['properties']['audio_channels'])
        return result

    def get_audio_tracks(self) -> typing.List[AudioInfo]:
        result = []
        for track in self.tracks:
            if int(track.get('properties', {}).get('audio_channels', -1)) != -1:
                #AudioInfo = collections.namedtuple('AudioInfo', 'track_id name language channels')
                result.append(AudioInfo(track_id=int(track['id']),
                                        name=track['properties'].get('track_name', 'unnamed'),
                                        language=track['properties'].get('language', 'unknown'),
                                        channels=int(track['properties']['audio_channels'])))
        return result

    def get_video_dimensions(self) -> typing.Tuple[int, int]:
        for track in self.tracks:
            if 'pixel_dimensions' in track.get('properties'):
                try:
                    width, height = [int(x) for x in track['properties']['pixel_dimensions'].split('x')]
                except ValueError:
                    continue
                return width, height
        raise ValueError('Bad media "%s" - cannot get video dimensions' % self.path)

    def get_video_diagonal(self) -> float:
        width, height = self.get_video_dimensions()
        return math.hypot(width, height)
