"""🔒 Tests for the DM turn stream pump.

These pin the exact Socket.IO emissions produced for a given LangGraph stream.
Most were captured against the pre-refactor ``SocketStreamHandler`` and must not
change; the ones marked as such encode deliberate fixes.

The central invariant: **every bubble streams under the id its database row is
persisted under.** Narrator and OOC nodes mint that id before calling the model
and announce it on the run metadata, so the client never needs an after-the-fact
id remap.
"""
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, SystemMessage, ToolMessageChunk

from agents.dungeon_master.schemas import STREAM_MESSAGE_ID_KEY, STREAM_SPEAKER_KEY
from tests.conftest import FakeSocket, as_stream, failing_stream

NARRATOR = "Narrator"


def make_pump(sio: FakeSocket, sid: str = "sid-1"):
    from agents.dungeon_master.pump import TurnStreamPump
    from api.sinks import SocketTurnSink

    return TurnStreamPump(SocketTurnSink(sio, sid))


def chunk(node: str, content: str, message_id: str | None = "mid-1") -> tuple[Any, Any]:
    """A live token from a model call inside ``node``.

    A chunk's own id is the LangChain run id, so the message id travels on the
    run metadata under ``STREAM_MESSAGE_ID_KEY``.
    """
    metadata: dict[str, Any] = {"langgraph_node": node}
    if message_id is not None:
        metadata[STREAM_MESSAGE_ID_KEY] = message_id
    return ((), (AIMessageChunk(content=content), metadata))


def message(node: str, content: str, message_id: str = "mid-1") -> tuple[Any, Any]:
    """A node's state update: authoritative content, and the persisted id."""
    return (
        (),
        (AIMessage(content=content, name=NARRATOR, id=message_id), {"langgraph_node": node}),
    )


async def run(sio: FakeSocket, items: list[Any]) -> None:
    await make_pump(sio).process(as_stream(items))


# ---------------------------------------------------------------------------
# The core invariant: streamed id == persisted id
# ---------------------------------------------------------------------------


async def test_bubble_uses_the_node_minted_id_not_a_fresh_one() -> None:
    """The bubble id comes from run metadata, so it matches the persisted row."""
    sio = FakeSocket()
    await run(sio, [chunk("dm_narrator_opening", "The gate ", message_id="persisted-7")])

    assert {p["messageId"] for _e, p, _to in sio.emissions} == {"persisted-7"}


async def test_streamed_narration_closes_with_authoritative_content() -> None:
    """Tokens stream live, then the state update supplies the cleaned text.

    Raw tokens can contain retry attempts; the node's returned message is the
    authoritative version, so it is sent as ``stream_end`` content.
    """
    sio = FakeSocket()
    await run(sio, [
        chunk("dm_narrator_opening", "The gate ", message_id="m7"),
        chunk("dm_narrator_opening", "groans open.", message_id="m7"),
        message("dm_narrator_opening", "Narrator: The gate groans open.", message_id="m7"),
    ])

    assert sio.events() == ["stream_start", "stream_token", "stream_token", "stream_end"]
    assert sio.emissions[0][1] == {"messageId": "m7", "name": NARRATOR}
    # One bubble only -- the state update must not open a second one.
    assert sio.emissions[3][1] == {"messageId": "m7", "content": "The gate groans open."}


async def test_authoritative_content_has_the_speaker_prefix_stripped() -> None:
    """Stored content keeps a "Narrator: " prefix; the client must never see it.

    The REST history load strips it too (``api/routes/session.py``), so a
    reloaded conversation and a live turn render identically.
    """
    sio = FakeSocket()
    await run(sio, [
        chunk("dm_narrator_opening", "x", message_id="m1"),
        message("dm_narrator_opening", "Narrator: The hall is cold.", message_id="m1"),
    ])

    assert sio.emissions[-1][1]["content"] == "The hall is cold."


# ---------------------------------------------------------------------------
# Fix: narration that makes no model call used to be invisible
# ---------------------------------------------------------------------------


async def test_narration_without_a_model_call_still_reaches_the_client() -> None:
    """DELIBERATE FIX, not a captured behaviour.

    ``narration._direct`` returns prose with no model call, so it emits only a
    state update and no tokens. The old pump handled ``AIMessageChunk`` only and
    dropped it, which meant every closing narration and any single-beat opening
    narration never appeared until the page was reloaded.
    """
    sio = FakeSocket()
    await run(sio, [message("dm_narrator_closing", "Narrator: The door shuts.", message_id="m9")])

    assert sio.events() == ["stream_start", "stream_token", "stream_end"]
    assert sio.emissions[0][1] == {"messageId": "m9", "name": NARRATOR}
    # The full text is sent as one token so the bubble has content to show.
    assert sio.emissions[1][1] == {"messageId": "m9", "token": "The door shuts."}
    assert sio.emissions[2][1] == {"messageId": "m9", "content": "The door shuts."}


async def test_a_message_with_no_id_is_reported_not_streamed() -> None:
    """Fail-secure: without an id there is no way to keep client and DB in sync."""
    sio = FakeSocket()
    await run(sio, [((), (AIMessage(content="x", name=NARRATOR), {"langgraph_node": "ooc_responder"}))])

    assert sio.emissions == []


# ---------------------------------------------------------------------------
# Captured behaviour: attribution, bubble lifecycle, filtering
# ---------------------------------------------------------------------------


async def test_every_streamable_node_speaks_as_the_narrator() -> None:
    for node in ("dm_narrator_opening", "dm_narrator_closing", "ooc_responder"):
        sio = FakeSocket()
        await run(sio, [chunk(node, "hi")])
        assert sio.emissions[0][1]["name"] == NARRATOR, node


async def test_node_switch_closes_the_previous_bubble() -> None:
    sio = FakeSocket()
    await run(sio, [
        chunk("dm_narrator_opening", "You step inside.", message_id="m1"),
        chunk("dm_narrator_closing", "The door shuts.", message_id="m2"),
    ])

    assert sio.events() == [
        "stream_start", "stream_token",
        "stream_end", "stream_start", "stream_token",
        "stream_end",
    ]
    assert sio.emissions[0][1]["messageId"] == "m1"
    # Closed with no content key: the streamed text stands.
    assert sio.emissions[2][1] == {"messageId": "m1"}
    assert sio.emissions[3][1]["messageId"] == "m2"


async def test_repeated_chunks_from_same_node_do_not_reopen_the_bubble() -> None:
    sio = FakeSocket()
    await run(sio, [chunk("dm_narrator_opening", f"t{i}") for i in range(5)])

    assert sio.events().count("stream_start") == 1
    assert sio.events().count("stream_end") == 1
    assert sio.events().count("stream_token") == 5


async def test_empty_content_chunk_still_opens_a_bubble() -> None:
    sio = FakeSocket()
    await run(sio, [chunk("dm_narrator_opening", "")])

    assert sio.events() == ["stream_start", "stream_end"]


async def test_tokens_are_forwarded_verbatim() -> None:
    """Token text is never rewritten in flight.

    Prefix handling happens upstream (the model is prefilled with "Narrator: "
    so its tokens exclude it) and on the authoritative content at close. A pump
    that also stripped tokens would corrupt narration that legitimately begins
    with the narrator's name.
    """
    sio = FakeSocket()
    await run(sio, [chunk("dm_narrator_opening", "Narrator: The hall is cold.")])

    tokens = [p["token"] for e, p, _to in sio.emissions if e == "stream_token"]
    assert tokens == ["Narrator: The hall is cold."]


async def test_internal_nodes_are_not_streamed() -> None:
    """Internal reasoning and router nodes are ignored by the pump."""
    sio = FakeSocket()
    await run(sio, [
        chunk("npc_router", "Sera"),
        chunk("use_tools", "{}"),
        chunk("dm_planner", "internal reasoning"),
    ])

    assert sio.emissions == []


async def test_npc_narrator_streams_with_speaker_and_validator_retracts() -> None:
    """NPC nodes stream under their character name, and nudged_agent validator retracts rejected attempts."""
    sio = FakeSocket()
    await run(sio, [
        ((), (AIMessageChunk(content="bad"), {"langgraph_node": "npc_narrator", STREAM_MESSAGE_ID_KEY: "m-bad", STREAM_SPEAKER_KEY: "Sera"})),
        ((), (AIMessage(content="Sera: bad", name="Sera", id="m-bad"), {"langgraph_node": "npc_narrator"})),
        ((), (SystemMessage(content="nudge", id="n-1"), {"langgraph_node": "validator_node"})),
        ((), (AIMessageChunk(content="Well met."), {"langgraph_node": "npc_narrator", STREAM_MESSAGE_ID_KEY: "m-good", STREAM_SPEAKER_KEY: "Sera"})),
        ((), (AIMessage(content="Sera: Well met.", name="Sera", id="m-good"), {"langgraph_node": "npc_narrator"})),
    ])

    assert sio.emissions[0][1] == {"messageId": "m-bad", "name": "Sera"}
    assert ("stream_end", {"messageId": "m-bad", "content": ""}, "sid-1") in sio.emissions
    assert sio.emissions[-1][1] == {"messageId": "m-good", "content": "Well met."}


async def test_tool_chunks_are_not_streamed() -> None:
    sio = FakeSocket()
    await run(sio, [((), (ToolMessageChunk(content="✅ Saved", tool_call_id="t1"),
                          {"langgraph_node": "dm_narrator_opening"}))])
    assert sio.emissions == []


async def test_unknown_message_types_are_ignored() -> None:
    sio = FakeSocket()
    await run(sio, [((), ("not-a-message", {"langgraph_node": "dm_narrator_opening"}))])
    assert sio.emissions == []


async def test_empty_stream_emits_nothing() -> None:
    sio = FakeSocket()
    await run(sio, [])
    assert sio.emissions == []


# ---------------------------------------------------------------------------
# Degradation
# ---------------------------------------------------------------------------


async def test_missing_stream_id_metadata_still_narrates() -> None:
    """Fail-secure: narrate under a provisional id rather than lose the turn.

    The mismatch with the persisted row is logged as an error, since editing
    such a bubble client-side would target an id the server does not know.
    """
    sio = FakeSocket()
    await run(sio, [chunk("dm_narrator_opening", "The gate opens.", message_id=None)])

    assert sio.events() == ["stream_start", "stream_token", "stream_end"]
    assert sio.emissions[0][1]["messageId"]


async def test_stream_failure_reports_an_error_and_closes_the_bubble() -> None:
    """A mid-stream exception is caught, reported, and the open bubble closed."""
    sio = FakeSocket()
    await make_pump(sio).process(failing_stream(
        [chunk("dm_narrator_opening", "The floor gives w", message_id="m1")],
        RuntimeError("model exploded"),
    ))

    assert sio.events() == ["stream_start", "stream_token", "error", "stream_end"]
    assert set(sio.emissions[2][1]) == {"message"}
    # No content key, so the partial text the player already saw survives.
    assert sio.emissions[3][1] == {"messageId": "m1"}


async def test_failure_before_any_bubble_only_reports_the_error() -> None:
    sio = FakeSocket()
    await make_pump(sio).process(failing_stream([], RuntimeError("boom")))

    assert sio.events() == ["error"]


async def test_missing_langgraph_node_metadata_is_an_error_not_a_crash() -> None:
    sio = FakeSocket()
    await make_pump(sio).process(as_stream([((), (AIMessageChunk(content="x"), {}))]))

    assert sio.events() == ["error"]
