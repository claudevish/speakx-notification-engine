"""Notification strategy engine that maps user states to notification themes and priorities.

This module defines the core strategy logic: given a user's current learning state,
it determines which notification themes are appropriate, the priority level, and
daily caps. It also handles theme selection per time slot while avoiding recently
sent themes.
"""

import random

from app.notifications.schemas import NotificationStrategy, NotificationTheme


class NotificationStrategyEngine:
    """Engine that resolves notification strategies based on user learning state.

    Maintains two class-level mappings:
    - ``STATE_STRATEGIES``: maps each user state string to a ``NotificationStrategy``
      describing applicable themes, priority, and daily caps.
    - ``SLOT_THEME_PREFERENCES``: maps each time-slot index (1-6) to an ordered list
      of preferred themes for that slot.
    """
    STATE_STRATEGIES: dict[str, NotificationStrategy] = {
        "new_unstarted": NotificationStrategy(
            user_state="new_unstarted",
            applicable_themes=[NotificationTheme.motivational, NotificationTheme.story_teaser],
            priority="high", max_daily_for_state=2,
        ),
        "onboarding": NotificationStrategy(
            user_state="onboarding",
            applicable_themes=[NotificationTheme.tip, NotificationTheme.challenge, NotificationTheme.story_teaser],
            priority="high", max_daily_for_state=3,
        ),
        "progressing_active": NotificationStrategy(
            user_state="progressing_active",
            applicable_themes=[
                NotificationTheme.milestone, NotificationTheme.streak,
                NotificationTheme.story_teaser, NotificationTheme.challenge, NotificationTheme.wotd,
            ],
            priority="medium", max_daily_for_state=4, suppress_if_active=True,
        ),
        "progressing_slow": NotificationStrategy(
            user_state="progressing_slow",
            applicable_themes=[NotificationTheme.motivational, NotificationTheme.story_teaser, NotificationTheme.tip],
            priority="medium", max_daily_for_state=3,
        ),
        "struggling": NotificationStrategy(
            user_state="struggling",
            applicable_themes=[
                NotificationTheme.motivational, NotificationTheme.tip,
                NotificationTheme.appreciation, NotificationTheme.humor,
            ],
            priority="high", max_daily_for_state=3,
        ),
        "bored_skimming": NotificationStrategy(
            user_state="bored_skimming",
            applicable_themes=[
                NotificationTheme.challenge, NotificationTheme.click_bait,
                NotificationTheme.quiz, NotificationTheme.fomo,
            ],
            priority="high", max_daily_for_state=3,
        ),
        "chapter_transition": NotificationStrategy(
            user_state="chapter_transition",
            applicable_themes=[
                NotificationTheme.story_teaser, NotificationTheme.fomo, NotificationTheme.click_bait,
            ],
            priority="high", max_daily_for_state=2,
        ),
        "dormant_short": NotificationStrategy(
            user_state="dormant_short",
            applicable_themes=[
                NotificationTheme.fomo, NotificationTheme.story_teaser,
                NotificationTheme.relationship, NotificationTheme.social_proof,
            ],
            priority="high", max_daily_for_state=2,
        ),
        "dormant_long": NotificationStrategy(
            user_state="dormant_long",
            applicable_themes=[
                NotificationTheme.fomo, NotificationTheme.relationship,
                NotificationTheme.recap, NotificationTheme.motivational,
            ],
            priority="high", max_daily_for_state=1,
        ),
        "churned": NotificationStrategy(
            user_state="churned",
            applicable_themes=[
                NotificationTheme.story_teaser, NotificationTheme.fomo, NotificationTheme.recap,
            ],
            priority="low", max_daily_for_state=1,
        ),
        "completing": NotificationStrategy(
            user_state="completing",
            applicable_themes=[
                NotificationTheme.milestone, NotificationTheme.motivational, NotificationTheme.streak,
            ],
            priority="medium", max_daily_for_state=2,
        ),
        "completed": NotificationStrategy(
            user_state="completed",
            applicable_themes=[NotificationTheme.appreciation, NotificationTheme.social_proof],
            priority="low", max_daily_for_state=1,
        ),
    }

    SLOT_THEME_PREFERENCES: dict[int, list[NotificationTheme]] = {
        1: [NotificationTheme.wotd, NotificationTheme.motivational, NotificationTheme.tip],
        2: [NotificationTheme.challenge, NotificationTheme.quiz],
        3: [NotificationTheme.story_teaser, NotificationTheme.fomo],
        4: [NotificationTheme.streak, NotificationTheme.milestone],
        5: [NotificationTheme.recap, NotificationTheme.social_proof],
        6: [],
    }

    def get_strategy(self, user_state: str) -> NotificationStrategy:
        """Look up the notification strategy for a given user state.

        Args:
            user_state: The user's current learning state identifier
                (e.g. ``"new_unstarted"``, ``"progressing_active"``).

        Returns:
            The ``NotificationStrategy`` for the state, or a conservative default
            strategy (motivational theme, low priority, max 1/day) if the state
            is not recognised.
        """
        return self.STATE_STRATEGIES.get(
            user_state,
            NotificationStrategy(
                user_state=user_state,
                applicable_themes=[NotificationTheme.motivational],
                priority="low",
                max_daily_for_state=1,
            ),
        )

    def select_theme(
        self,
        strategy: NotificationStrategy,
        slot: int,
        recent_themes: list[str],
    ) -> NotificationTheme:
        """Select the best notification theme for a strategy and time slot.

        Filters out recently used themes, then prefers slot-specific themes.
        Falls back to a random choice from the remaining applicable themes.

        Args:
            strategy: The resolved ``NotificationStrategy`` for the user.
            slot: The time-slot index (1-6) within the day.
            recent_themes: Theme value strings that were recently sent to this
                user and should be deprioritised.

        Returns:
            The chosen ``NotificationTheme`` enum member.
        """
        available = [t for t in strategy.applicable_themes if t.value not in recent_themes]

        if not available:
            available = list(strategy.applicable_themes)

        slot_prefs = self.SLOT_THEME_PREFERENCES.get(slot, [])
        for pref in slot_prefs:
            if pref in available:
                return pref

        return random.choice(available)
