class Options(object):
    __slots__ = ['debug', 'logpath']

    def __init__(self):
        self.debug = False
        self.logpath = None

OPTIONS = Options()
del Options
