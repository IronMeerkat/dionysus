from dataclasses import dataclass, field
from logging import getLogger

from langchain_core.messages import AnyMessage

from hephaestus.helpers import Singleton
from hephaestus.settings import settings

from database.models import Player, Character, Conversation
from utils.prompts import placeholder_location, placeholder_scenario

logger = getLogger(__name__)

@dataclass
class TableTop(metaclass=Singleton):

    # TODO make a redis instance for prod

    player: Player | None = None
    characters: list[Character] = field(default_factory=list)

    messages: list[AnyMessage] = field(default_factory=list)
    location: str = placeholder_location
    story_background: str = placeholder_scenario
    lore_world: str = settings.PLACEHOLDER_LORE_WORLD
    conversation: Conversation = None

    def create_conversation(self):
        if self.conversation is None:
            self.conversation = Conversation.create(self.player, self.characters)
        return self.conversation

tabletop = TableTop()
