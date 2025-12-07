from dataclasses import dataclass

from gtools.core.eventbus import EventMixin


@dataclass
class UpdateServerData(EventMixin):
    server: str
    port: int
