"""Finite state machine defining the learner journey lifecycle.

Defines the ``JourneyStateMachine`` which models every state a user can
occupy within a learning journey -- from first launch through active
progression, dormancy, and eventual completion or churn.  Transitions
between states are triggered by the :class:`StateTransitionManager` in
``transitions.py`` based on behavioral signals and temporal scans.
"""

import structlog
from statemachine import State, StateMachine

logger = structlog.get_logger()

ACTIVE_STATES: frozenset[str] = frozenset({
    "onboarding",
    "progressing_active",
    "progressing_slow",
    "struggling",
    "bored_skimming",
    "chapter_transition",
})
"""States in which the user is considered actively engaged."""

ALL_STATES: frozenset[str] = frozenset({
    "new_unstarted",
    "onboarding",
    "progressing_active",
    "progressing_slow",
    "struggling",
    "bored_skimming",
    "chapter_transition",
    "dormant_short",
    "dormant_long",
    "churned",
    "completing",
    "completed",
})
"""Complete enumeration of every valid journey state."""


class JourneyStateMachine(StateMachine):
    """State machine representing a user's learning-journey lifecycle.

    States progress from ``new_unstarted`` through engagement states
    (onboarding, progressing, struggling, etc.), dormancy tiers, and
    finally ``completed``.  The machine is instantiated per-evaluation;
    the ``initial_state`` parameter allows resuming from the user's
    persisted state.
    """

    # --- States ---
    new_unstarted = State(initial=True)
    onboarding = State()
    progressing_active = State()
    progressing_slow = State()
    struggling = State()
    bored_skimming = State()
    chapter_transition = State()
    dormant_short = State()
    dormant_long = State()
    churned = State()
    completing = State()
    completed = State(final=True)

    # --- Transitions ---
    start_journey = new_unstarted.to(onboarding)

    complete_onboarding = onboarding.to(progressing_active)

    slow_down = progressing_active.to(progressing_slow)
    speed_up = progressing_slow.to(progressing_active)

    start_struggling = (
        progressing_active.to(struggling)
        | progressing_slow.to(struggling)
    )

    stop_struggling = struggling.to(progressing_active)

    start_skimming = (
        progressing_active.to(bored_skimming)
        | progressing_slow.to(bored_skimming)
    )

    stop_skimming = bored_skimming.to(progressing_active)

    enter_chapter_transition = (
        progressing_active.to(chapter_transition)
        | progressing_slow.to(chapter_transition)
        | struggling.to(chapter_transition)
        | bored_skimming.to(chapter_transition)
    )

    resume_from_transition = chapter_transition.to(progressing_active)

    go_dormant_short = (
        onboarding.to(dormant_short)
        | progressing_active.to(dormant_short)
        | progressing_slow.to(dormant_short)
        | struggling.to(dormant_short)
        | bored_skimming.to(dormant_short)
        | chapter_transition.to(dormant_short)
    )

    go_dormant_long = dormant_short.to(dormant_long)

    churn = dormant_long.to(churned)

    reactivate = (
        dormant_short.to(progressing_active)
        | dormant_long.to(progressing_active)
        | churned.to(progressing_active)
    )

    near_completion = progressing_active.to(completing)

    finish = completing.to(completed)

    def __init__(self, initial_state: str = "new_unstarted") -> None:
        """Initialise the state machine, optionally resuming from a persisted state.

        Args:
            initial_state: The state identifier to start from.  Defaults to
                ``"new_unstarted"`` which uses the machine's declared initial
                state.  Any other value sets the machine's starting position
                directly via ``start_value``.
        """
        self._user_id: str = ""
        self._journey_id: str = ""
        if initial_state != "new_unstarted":
            super().__init__(start_value=initial_state)
        else:
            super().__init__()

    def set_context(self, user_id: str, journey_id: str) -> None:
        """Attach user and journey identifiers used in transition logging.

        Args:
            user_id: The unique identifier of the learner.
            journey_id: The unique identifier of the learning journey.
        """
        self._user_id = user_id
        self._journey_id = journey_id

    def on_enter_state(self, source: State, target: State, event: str) -> None:
        """Callback invoked automatically whenever a state transition occurs.

        Logs the transition details including source state, target state, and
        the triggering event name.

        Args:
            source: The state being exited (may be ``None`` on initial entry).
            target: The state being entered.
            event: The name of the transition event that was sent.
        """
        logger.info(
            "State transition",
            user_id=self._user_id,
            journey_id=self._journey_id,
            from_state=source.id if source else "none",
            to_state=target.id,
            trigger=event,
        )
