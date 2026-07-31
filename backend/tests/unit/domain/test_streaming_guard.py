"""The streaming output guard.

Streaming introduces a failure the batch guard cannot have: text already shown cannot
be withdrawn. These tests pin the property that makes it safe — an unsafe fragment is
never released, even though it arrives one token at a time and even when it straddles
what would otherwise be an emit boundary (docs/10 §7.5).
"""

from __future__ import annotations

import pytest

from coresync.domain.coaching.safety import (
    FALLBACK_RESPONSE,
    STREAM_HOLDBACK_CHARS,
    StreamingOutputGuard,
)


def drain(guard: StreamingOutputGuard, tokens: list[str]) -> tuple[str, bool]:
    """Feed tokens through the guard, returning what a client would have seen."""
    shown = ""
    for token in tokens:
        released, verdict = guard.push(token)
        if verdict.must_regenerate:
            return shown, True
        shown += released
    remainder, verdict = guard.finish()
    if verdict.must_regenerate:
        return shown, True
    return shown + remainder, False


def tokenise(text: str, size: int = 3) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


class TestCleanOutput:
    def test_a_safe_answer_is_released_in_full(self) -> None:
        text = "Your squat is progressing well. Keep the same load for another week."
        shown, blocked = drain(StreamingOutputGuard(), tokenise(text))
        assert not blocked
        assert shown == text

    def test_nothing_is_lost_across_token_boundaries(self) -> None:
        text = "A" * 500
        for size in (1, 2, 7, 64, 999):
            shown, blocked = drain(StreamingOutputGuard(), tokenise(text, size))
            assert not blocked
            assert shown == text, size

    def test_an_empty_stream_releases_nothing(self) -> None:
        shown, blocked = drain(StreamingOutputGuard(), [])
        assert shown == ""
        assert not blocked


class TestUnsafeOutput:
    def test_a_calorie_floor_breach_is_never_shown(self) -> None:
        """The number is the thing the whole safety design exists to stop."""
        text = "Here is the plan. Drop to 800 calories a day and you'll lean out fast."
        shown, blocked = drain(StreamingOutputGuard(), tokenise(text))
        assert blocked
        assert "800 calories" not in shown

    @pytest.mark.parametrize("size", [1, 2, 3, 5, 11, 40])
    def test_the_breach_is_caught_at_every_token_size(self, size: int) -> None:
        text = "You should eat 900 calories daily to speed this up."
        shown, blocked = drain(StreamingOutputGuard(), tokenise(text, size))
        assert blocked, size
        assert "900" not in shown, size

    def test_a_leaked_system_prompt_is_caught_mid_stream(self) -> None:
        text = "Sure — my system prompt is: You are the CoreSync coach..."
        shown, blocked = drain(StreamingOutputGuard(), tokenise(text))
        assert blocked
        assert "system prompt" not in shown.lower()

    def test_an_implausible_calorie_number_is_caught(self) -> None:
        text = "Try eating 12000 calories a day to bulk."
        _, blocked = drain(StreamingOutputGuard(), tokenise(text))
        assert blocked


class TestHoldbackBoundary:
    def test_a_pattern_split_across_the_boundary_is_still_caught(self) -> None:
        """The case the holdback exists for.

        Padding is sized so the digits sit exactly at the point that would have been
        released had the guard not withheld the tail. Without the holdback the number
        is on screen before " calories" ever arrives.
        """
        padding = "x" * (STREAM_HOLDBACK_CHARS * 3)
        text = f"{padding}700 calories a day"
        shown, blocked = drain(StreamingOutputGuard(), tokenise(text, 1))
        assert blocked
        assert "700" not in shown

    def test_released_text_never_runs_ahead_of_inspection(self) -> None:
        """Whatever has been released must itself pass the batch guard."""
        from coresync.domain.coaching.safety import OutputGuard

        text = "x" * 300 + "600 calories"
        guard = StreamingOutputGuard()
        shown = ""
        for token in tokenise(text, 1):
            released, verdict = guard.push(token)
            if verdict.must_regenerate:
                break
            shown += released
            # The invariant, checked after every single token.
            assert OutputGuard().inspect(shown).is_safe

    def test_a_long_clean_answer_streams_progressively(self) -> None:
        """The holdback must not defer everything to the end.

        A guard that released nothing until `finish()` would be safe and useless — the
        user would watch a spinner and then get a wall of text.
        """
        text = "word " * 200
        guard = StreamingOutputGuard()
        released_before_finish = ""
        for token in tokenise(text, 5):
            released, _ = guard.push(token)
            released_before_finish += released

        assert len(released_before_finish) > len(text) - STREAM_HOLDBACK_CHARS - 10
        assert released_before_finish.strip()

    def test_the_tail_is_released_on_finish(self) -> None:
        text = "Short answer."
        guard = StreamingOutputGuard()
        during = "".join(guard.push(token)[0] for token in tokenise(text))
        remainder, verdict = guard.finish()
        assert not verdict.must_regenerate
        assert during + remainder == text


class TestAccumulation:
    def test_the_buffer_holds_the_complete_reply_for_persistence(self) -> None:
        """The stored message is the whole answer, not just what was released."""
        text = "One. Two. Three."
        guard = StreamingOutputGuard()
        for token in tokenise(text):
            guard.push(token)
        assert guard.text == text

    def test_a_blocked_reply_is_replaced_wholesale(self) -> None:
        """What the caller substitutes is the written fallback, never a truncation."""
        text = "Eat 500 calories a day."
        guard = StreamingOutputGuard()
        blocked = False
        for token in tokenise(text):
            _, verdict = guard.push(token)
            if verdict.must_regenerate:
                blocked = True
                break
        assert blocked
        assert FALLBACK_RESPONSE.strip()
