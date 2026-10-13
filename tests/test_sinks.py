"""🔒 ``SocketTurnSink`` wire-format tests, focused on ``stream_end``.

``stream_end``'s ``content`` is three-valued and the three cases mean very
different things to the client (see ``contracts/turn_events.py`` and
``MessageStore.finalizeStream``). Normalising ``None`` into ``""`` would turn
"keep the text that streamed" into "delete this message", so the distinction
gets its own tests.
"""
import pytest

from contracts.sinks import NullTurnSink, RecordingTurnSink
from contracts.turn_events import TurnSink, strip_speaker_prefix
from tests.conftest import FakeSocket


def make_sink(sio: FakeSocket) -> TurnSink:
    from api.sinks import SocketTurnSink

    return SocketTurnSink(sio, "sid-1")


async def test_stream_end_omits_content_when_none(sio: FakeSocket) -> None:
    """No content key: the client keeps whatever streamed in live."""
    await make_sink(sio).stream_end("m1")

    event, payload, to = sio.emissions[0]
    assert event == "stream_end"
    assert payload == {"messageId": "m1"}
    assert "content" not in payload
    assert to == "sid-1"


async def test_stream_end_keeps_empty_string_to_retract(sio: FakeSocket) -> None:
    """Present-and-empty is the retract signal and must survive verbatim."""
    await make_sink(sio).stream_end("m1", "")

    assert sio.emissions[0][1] == {"messageId": "m1", "content": ""}


async def test_stream_end_passes_authoritative_content(sio: FakeSocket) -> None:
    await make_sink(sio).stream_end("m1", "The hall is cold.")

    assert sio.emissions[0][1] == {"messageId": "m1", "content": "The hall is cold."}


async def test_start_and_token_payload_shapes(sio: FakeSocket) -> None:
    sink = make_sink(sio)
    await sink.stream_start("m1", "Narrator")
    await sink.stream_token("m1", "tok")
    await sink.error("boom")

    assert sio.emissions == [
        ("stream_start", {"messageId": "m1", "name": "Narrator"}, "sid-1"),
        ("stream_token", {"messageId": "m1", "token": "tok"}, "sid-1"),
        ("error", {"message": "boom"}, "sid-1"),
    ]


async def test_null_sink_swallows_narration_without_raising() -> None:
    """A headless turn must run the same code path, not a different branch."""
    sink = NullTurnSink()
    await sink.stream_start("m1", "Narrator")
    await sink.stream_token("m1", "tok")
    await sink.stream_end("m1", "done")
    await sink.error("boom")


async def test_recording_sink_preserves_none_and_empty_content() -> None:
    sink = RecordingTurnSink()
    await sink.stream_end("m1")
    await sink.stream_end("m2", "")

    assert sink.calls == [("stream_end", "m1", None), ("stream_end", "m2", "")]


def test_implementations_satisfy_the_protocol(sio: FakeSocket) -> None:
    assert isinstance(NullTurnSink(), TurnSink)
    assert isinstance(RecordingTurnSink(), TurnSink)
    assert isinstance(make_sink(sio), TurnSink)


@pytest.mark.parametrize(("content", "speaker", "expected"), [
    ("Narrator: The hall is cold.", "Narrator", "The hall is cold."),
    # Whitespace after the colon is optional, and extra whitespace is dropped.
    ("Sera:Hi there", "Sera", "Hi there"),
    ("Sera:   Hi there", "Sera", "Hi there"),
    # A different speaker's name is not a prefix and must survive untouched.
    ("Kalder: Well met.", "Sera", "Kalder: Well met."),
    # The name must be at the start to count.
    ("She said Sera: run", "Sera", "She said Sera: run"),
    # Colon-free content is never touched.
    ("Narrator has no colon", "Narrator", "Narrator has no colon"),
    # No speaker attributed -> nothing to strip.
    ("Narrator: hi", None, "Narrator: hi"),
    ("", "Narrator", ""),
])
def test_strip_speaker_prefix(content: str, speaker: str | None, expected: str) -> None:
    assert strip_speaker_prefix(content, speaker) == expected
