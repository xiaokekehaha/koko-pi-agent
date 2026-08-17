from __future__ import annotations

import pytest

from koko_pi_agent.runtime import (
    RunControl,
    RunControlState,
    RunInputClosedError,
    RunInputKind,
)


def test_enqueue_returns_kind_local_positions_and_unique_ids() -> None:
    control = RunControl()

    first = control.enqueue(RunInputKind.STEERING, "first")
    second = control.enqueue(RunInputKind.STEERING, "second")
    follow_up = control.enqueue(RunInputKind.FOLLOW_UP, "later")

    assert first.position == 1
    assert second.position == 2
    assert follow_up.position == 1
    assert len({first.item.input_id, second.item.input_id, follow_up.item.input_id}) == 3
    assert control.pending_count == 3


def test_before_first_turn_only_drains_steering_in_fifo_order() -> None:
    control = RunControl()
    steering = [
        control.enqueue(RunInputKind.STEERING, text).item
        for text in ("first", "second")
    ]
    follow_up = control.enqueue(RunInputKind.FOLLOW_UP, "after work").item

    assert control.before_first_turn() == tuple(steering)
    assert control.before_first_turn() == ()

    directive = control.after_turn(would_stop=True)
    assert directive.continue_run is True
    assert directive.reason == "follow_up"
    assert directive.deliveries == (follow_up,)


def test_steering_has_priority_over_follow_up_at_natural_stop() -> None:
    control = RunControl()
    follow_up = control.enqueue(RunInputKind.FOLLOW_UP, "later").item
    steering = control.enqueue(RunInputKind.STEERING, "change direction").item

    first = control.after_turn(would_stop=True)
    second = control.after_turn(would_stop=True)
    final = control.after_turn(would_stop=True)

    assert first.deliveries == (steering,)
    assert first.reason == "steering"
    assert second.deliveries == (follow_up,)
    assert second.reason == "follow_up"
    assert final.continue_run is False
    assert final.reason == "natural"
    assert control.state is RunControlState.SEALED


def test_tool_continuation_does_not_consume_follow_up() -> None:
    control = RunControl()
    follow_up = control.enqueue(RunInputKind.FOLLOW_UP, "after tools").item

    tool_turn = control.after_turn(would_stop=False)
    natural_turn = control.after_turn(would_stop=True)

    assert tool_turn.continue_run is True
    assert tool_turn.reason == "tool_calls"
    assert tool_turn.deliveries == ()
    assert natural_turn.deliveries == (follow_up,)


def test_retry_continuation_reports_retry_reason() -> None:
    control = RunControl()

    directive = control.after_turn(
        would_stop=False,
        continue_reason="retry",
    )

    assert directive.continue_run is True
    assert directive.reason == "retry"


@pytest.mark.parametrize("reason", ["cancelled", "terminate", "failed"])
def test_hard_stop_preserves_undelivered_inputs_in_enqueue_order(reason: str) -> None:
    control = RunControl()
    queued = [
        control.enqueue(kind, text).item
        for kind, text in (
            (RunInputKind.FOLLOW_UP, "one"),
            (RunInputKind.STEERING, "two"),
            (RunInputKind.FOLLOW_UP, "three"),
        )
    ]

    directive = control.after_turn(would_stop=False, hard_stop=reason)  # type: ignore[arg-type]

    assert directive.continue_run is False
    assert directive.reason == reason
    assert directive.deliveries == ()
    assert control.recover_undelivered() == tuple(queued)
    assert control.recover_undelivered() == ()


def test_turn_limit_only_overrides_natural_completion_when_more_work_exists() -> None:
    completed = RunControl()
    natural = completed.after_turn(
        would_stop=True,
        continuation_allowed=False,
    )

    pending = RunControl()
    queued = pending.enqueue(RunInputKind.FOLLOW_UP, "continue").item
    limited = pending.after_turn(
        would_stop=True,
        continuation_allowed=False,
    )

    assert natural.reason == "natural"
    assert limited.reason == "max_turns"
    assert pending.recover_undelivered() == (queued,)


def test_sealed_control_rejects_new_input() -> None:
    control = RunControl()
    control.seal("cancelled")

    with pytest.raises(RunInputClosedError, match="no longer accepts"):
        control.enqueue(RunInputKind.STEERING, "too late")

    assert control.after_turn(would_stop=True).reason == "cancelled"


def test_empty_input_is_rejected_without_changing_state() -> None:
    control = RunControl()

    with pytest.raises(ValueError, match="must not be empty"):
        control.enqueue(RunInputKind.STEERING, "   ")

    assert control.state is RunControlState.OPEN
    assert control.pending_count == 0
