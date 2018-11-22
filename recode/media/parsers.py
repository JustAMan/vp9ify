from series import SeriesEpisode

class UnknownFile(Exception):
    pass
class UnhandledMediaType(Exception):
    pass

PARSERS = [SeriesEpisode]
