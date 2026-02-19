from dataclasses import dataclass, field
from logging import getLogger

from langchain_core.messages import AnyMessage


from database.models import Player, Character

logger = getLogger(__name__)

class Singleton(type):
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]

@dataclass
class TableTop(metaclass=Singleton):

    # TODO make a redis instance for prod

    player: Player | None = None
    characters: list[Character] = field(default_factory=list)

    messages: list[AnyMessage] = field(default_factory=list)
    location: str = ''

tabletop = TableTop()
