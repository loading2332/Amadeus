"""Fixture proving terminate failures cannot interrupt host cleanup."""

from amadeus.plugin import Plugin


class TerminateFail(Plugin):
    async def terminate(self) -> None:
        raise RuntimeError("terminate failure fixture")
