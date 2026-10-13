"""📡 The turn-streaming vocabulary, as a transport-agnostic contract.

A DM turn produces exactly three kinds of client-facing signal: a bubble
opens, tokens arrive, the bubble closes. ``TurnSink`` is that vocabulary with
no mention of Socket.IO, so graph nodes can narrate a turn without knowing
whether the far end is a browser, a message bus, or nothing at all.

Mirror of ``dionysus-frontend/src/types/socket.ts``. The one subtlety worth
preserving carefully is ``stream_end``'s three-valued ``content``:

- ``None``  -> the key is omitted on the wire; the client keeps whatever
  streamed in live.
- ``""``    -> the message is RETRACTED and the client drops the bubble.
- non-empty -> authoritative content replacing whatever streamed in live.

Collapsing ``None`` into ``""`` would silently delete messages, so
implementations must distinguish the two rather than normalising them.
"""
from typing import Protocol, runtime_checkable

# Speaker label for the dice line the planner announces. Wire-level value:
# the frontend shows it as the bubble's author.
DICE_SPEAKER = "Dice"


def strip_speaker_prefix(content: str, speaker: str | None) -> str:
    """✂️ Drop a leading ``"{speaker}:"`` from persisted content.

    Messages are stored WITH a speaker prefix (the models are prefilled with it
    to hold voice), but the client renders ``name`` separately and must never
    see the prefix in the body. Every path to the client applies this: the REST
    history load, the NPC executor's live bubbles, and the turn pump's
    authoritative content.

    Whitespace after the colon is optional, so a model that emits ``"Sera:Hi"``
    is handled as well as ``"Sera: Hi"``.
    """
    if not speaker:
        return content
    prefix = f"{speaker}:"
    if not content.startswith(prefix):
        return content
    return content[len(prefix):].lstrip()


@runtime_checkable
class TurnSink(Protocol):
    """Where a turn's narration goes. One instance per turn, per client."""

    async def stream_start(self, message_id: str, speaker: str) -> None:
        """Open a bubble attributed to ``speaker``."""
        ...

    async def stream_end(self, message_id: str, content: str | None = None) -> None:
        """Close a bubble. See the module docstring on ``content``'s tri-state."""
        ...

    async def stream_token(self, message_id: str, token: str) -> None:
        """Append a token to an open bubble."""
        ...

    async def error(self, message: str) -> None:
        """Report a turn-level failure to the client."""
        ...
