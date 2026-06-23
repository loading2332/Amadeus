"""Invalid fixture: one entry point must not register multiple Plugin classes."""

from amadeus.plugin import Plugin


class First(Plugin):
    pass


class Second(Plugin):
    pass
