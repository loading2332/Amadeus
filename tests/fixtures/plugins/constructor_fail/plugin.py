"""Invalid fixture: construction must fail closed."""

from amadeus.plugin import Plugin


class ConstructorFail(Plugin):
    def __init__(self) -> None:
        raise RuntimeError("constructor failure fixture")
