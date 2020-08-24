from .series import SeriesEpisode
from .movie import SingleMovie, HQMovie, LQMovie, YTLike

PARSERS = [SeriesEpisode, SingleMovie, HQMovie, LQMovie, YTLike]
UPCAST = {
    SingleMovie.FORCE_NAME: {
        'default': [SingleMovie],
        'lq': [LQMovie],
        'hq': [HQMovie],
        'both': [LQMovie, HQMovie],
        'yt': [YTLike],
    }
}