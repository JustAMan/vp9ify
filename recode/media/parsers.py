from series import SeriesEpisode

class UnhandledMediaType(Exception):
    pass

PARSERS = [SeriesEpisode]
