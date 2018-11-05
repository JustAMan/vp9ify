import collections
import sys
import subprocess
import json
import math

from ..helpers import which

SubtitleInfo = collections.namedtuple('SubtitleInfo', 'track_id name language')

class MediaInfo:
    def __init__(self, path, info, tracks):
        self.path = path
        self.info = info
        self.tracks = tracks
    
    @classmethod
    def parse(cls, path):
        if sys.platform == 'win32':
            out = u'{"attachments":[],"chapters":[],"container":{"properties":{"container_type":17,"date_local":"2001-01-01T03:00:00+03:00","date_utc":"2001-01-01T00:00:00Z","duration":31141000000,"is_providing_timecodes":true,"muxing_application":"Lavf57.56.101","segment_uid":"942fb317ab2287c02b79c8008e699b40","writing_application":"Lavf57.56.101"},"recognized":true,"supported":true,"type":"Matroska"},"errors":[],"file_name":"30sec.mkv","global_tags":[{"num_entries":1}],"identification_format_version":6,"track_tags":[],"tracks":[{"codec":"MPEG-4p10/AVC/h.264","id":0,"properties":{"codec_id":"V_MPEG4/ISO/AVC","codec_private_data":"01640028ffe1001a67640028acd940780227e5c04400000301f400005daa3c60c65801000668e938233c8f","codec_private_length":43,"default_duration":41708375,"default_track":true,"display_dimensions":"1920x1080","enabled_track":true,"forced_track":false,"language":"eng","minimum_timestamp":4948000000,"number":1,"packetizer":"mpeg4_p10_video","pixel_dimensions":"1920x1080","uid":1},"type":"video"},{"codec":"AC-3/E-AC-3","id":1,"properties":{"audio_channels":2,"audio_sampling_frequency":48000,"codec_id":"A_AC3","codec_private_length":0,"default_track":true,"enabled_track":true,"forced_track":true,"language":"rus","minimum_timestamp":0,"number":2,"track_name":"track1","uid":2},"type":"audio"},{"codec":"AC-3/E-AC-3","id":2,"properties":{"audio_channels":6,"audio_sampling_frequency":48000,"codec_id":"A_AC3","codec_private_length":0,"default_track":false,"enabled_track":true,"forced_track":false,"language":"rus","minimum_timestamp":0,"number":3,"track_name":"track2","uid":3},"type":"audio"},{"codec":"DTS","id":3,"properties":{"audio_channels":6,"audio_sampling_frequency":48000,"codec_id":"A_DTS","codec_private_length":0,"default_track":false,"enabled_track":true,"forced_track":false,"language":"eng","minimum_timestamp":10000000,"number":4,"uid":4},"type":"audio"},{"codec":"HDMV PGS","id":4,"properties":{"codec_id":"S_HDMV/PGS","codec_private_length":0,"default_track":false,"enabled_track":true,"forced_track":false,"language":"rus","minimum_timestamp":235000000,"number":5,"track_name":"subs1","uid":5},"type":"subtitles"},{"codec":"SubRip/SRT","id":5,"properties":{"codec_id":"S_TEXT/UTF8","codec_private_length":0,"default_track":false,"enabled_track":true,"forced_track":false,"language":"eng","minimum_timestamp":485000000,"number":6,"text_subtitles":true,"uid":6},"type":"subtitles"}],"warnings":[]}'.encode('utf8')
        else:
            try:
                out = subprocess.check_output([which('mkvmerge'), '-J', path])
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

    def get_subtitles(self):
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

    def get_audio_channels(self):
        result = {}
        for track in self.tracks:
            if int(track.get('properties', {}).get('audio_channels', -1)) != -1:
                result[int(track['id'])] = int(track['properties']['audio_channels'])
        return result

    def get_video_diagonal(self):
        for track in self.tracks:
            if 'pixel_dimensions' in track.get('properties'):
                try:
                    width, height = [int(x) for x in track['properties']['pixel_dimensions'].split('x')]
                except ValueError:
                    continue
                return math.hypot(width, height)
        raise ValueError('Bad media "%s" - cannot get its diagonal' % self.path)
