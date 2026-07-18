"""The streamed-text helpers do the fiddly work of turning a token stream into
clean, speakable sentences — worth pinning down before anyone refactors them."""

from backend.brain.streaming import (
    EmotionTagFilter,
    SentenceBuffer,
    clean_for_speech,
    ends_with_question,
    looks_like_empty_promise,
)


def _run_filter(filt: EmotionTagFilter, chunks: list[str]) -> tuple[str, list[str]]:
    out, felt = "", []
    for c in chunks:
        text, f = filt.feed(c)
        out += text
        felt += f
    out += filt.flush()
    return out, felt


def test_emotion_tag_stripped_and_reported():
    f = EmotionTagFilter({"joy", "curious"})
    out, felt = _run_filter(f, ["[joy] It worked!"])
    assert out == "It worked!"
    assert felt == ["joy"]


def test_tag_split_across_chunks():
    f = EmotionTagFilter({"joy"})
    out, felt = _run_filter(f, ["Hel", "lo [jo", "y] there"])
    assert out == "Hello there"
    assert felt == ["joy"]


def test_unknown_tag_dropped_silently():
    f = EmotionTagFilter({"joy"})
    out, felt = _run_filter(f, ["[unknown] hi"])
    assert "unknown" not in out
    assert felt == []


def test_non_tag_bracket_preserved():
    f = EmotionTagFilter({"joy"})
    out, _ = _run_filter(f, ["array[0] is fine"])
    assert "array[0]" in out


def test_unclosed_bracket_at_end_is_released():
    f = EmotionTagFilter({"joy"})
    out, _ = _run_filter(f, ["wait ["])
    assert out == "wait ["


def test_sentence_buffer_splits_on_terminators():
    b = SentenceBuffer()
    assert b.feed("Hello there. How are") == ["Hello there."]
    assert b.feed(" you? Fine") == ["How are you?"]
    assert b.flush() == ["Fine"]


def test_clean_for_speech_strips_stage_directions_and_markup():
    assert clean_for_speech("*laughs* Found it!") == "Found it!"
    assert "#" not in clean_for_speech("## Heading")
    assert clean_for_speech("   ") == ""


def test_promise_detection():
    assert looks_like_empty_promise("hold on, let me check that")
    assert looks_like_empty_promise("I'll look into it")
    assert not looks_like_empty_promise("the answer is 42")


def test_ends_with_question():
    assert ends_with_question("Want me to dig deeper?")
    assert ends_with_question('So... shall I open it?"')  # trailing quote ignored
    assert not ends_with_question("Found three headlines.")
    assert not ends_with_question("Is it? Let me check.")  # question isn't the end
