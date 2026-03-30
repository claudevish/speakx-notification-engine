"""Segment-based notification strategy engine.

Maps 4 engagement segments to their default top-3 Octolysis themes.
Replaces the old 12-state strategy model with a simpler segment × theme matrix
designed for bulk template generation.
"""

from __future__ import annotations

import random

from app.notifications.schemas import (
    EngagementSegment,
    NotificationStrategy,
    NotificationTheme,
    SegmentThemeConfig,
)

# ── Default Segment → Theme Mapping ──
# These are the defaults; Vishal/Paawan override per journey based on CTR analysis.

DEFAULT_SEGMENT_THEMES: dict[EngagementSegment, list[NotificationTheme]] = {
    EngagementSegment.E_eq_0: [
        NotificationTheme.epic_meaning,
        NotificationTheme.unpredictability,
        NotificationTheme.social_influence,
    ],
    EngagementSegment.E_lt_40: [
        NotificationTheme.empowerment,
        NotificationTheme.accomplishment,
        NotificationTheme.unpredictability,
    ],
    EngagementSegment.E_lt_70: [
        NotificationTheme.accomplishment,
        NotificationTheme.ownership,
        NotificationTheme.social_influence,
    ],
    EngagementSegment.E_gte_70: [
        NotificationTheme.accomplishment,
        NotificationTheme.ownership,
        NotificationTheme.loss_avoidance,
    ],
}

# ── Theme Psychology Reference ──
# Brief description of each theme's psychological lever for the UI reference panel.

THEME_PSYCHOLOGY: dict[str, str] = {
    "epic_meaning": "\"I'm part of something bigger\" — Connect learning to career transformation, community, and purpose.",
    "accomplishment": "\"I'm making real progress\" — Celebrate milestones, streaks, badges, and measurable growth.",
    "empowerment": "\"I can figure this out\" — Give choices, customization, and a sense of control over the journey.",
    "ownership": "\"This is mine to build\" — Reference accumulated assets: streaks, vocabulary, badges, progress.",
    "social_influence": "\"Others are doing this too\" — Social proof, peer comparison, community momentum.",
    "scarcity": "\"I might miss out\" — Time-limited content, expiring offers, exclusive access windows.",
    "unpredictability": "\"What happens next?\" — Surprise rewards, mystery content, story cliffhangers, curiosity gaps.",
    "loss_avoidance": "\"I don't want to lose my streak\" — Protect progress, prevent fade, save what's been earned.",
}


class NotificationStrategyEngine:
    """Engine that resolves notification themes for engagement segments.

    Provides the default segment → theme mapping, plus utility methods
    for theme selection during bulk generation.
    """

    def get_themes_for_segment(
        self,
        segment: EngagementSegment,
        override: dict[str, list[str]] | None = None,
    ) -> list[NotificationTheme]:
        """Get the top-3 themes for a segment, with optional override.

        Args:
            segment: The engagement segment to look up.
            override: Optional dict mapping segment values to theme value lists.

        Returns:
            List of NotificationTheme enum members (up to 3).
        """
        if override and segment.value in override:
            theme_values = override[segment.value]
            return [NotificationTheme(v) for v in theme_values[:3]]
        return list(DEFAULT_SEGMENT_THEMES.get(segment, [NotificationTheme.epic_meaning]))

    def get_default_config(self) -> list[SegmentThemeConfig]:
        """Return the full default segment → theme config for all 4 segments."""
        return [
            SegmentThemeConfig(segment=seg, themes=themes)
            for seg, themes in DEFAULT_SEGMENT_THEMES.items()
        ]

    # ── Legacy compatibility ──
    # Keep old STATE_STRATEGIES and SLOT_THEME_PREFERENCES for any code that still references them.

    STATE_STRATEGIES: dict[str, NotificationStrategy] = {
        "new_unstarted": NotificationStrategy(
            user_state="new_unstarted",
            applicable_themes=[NotificationTheme.epic_meaning, NotificationTheme.unpredictability],
            priority="high", max_daily_for_state=2,
        ),
        "onboarding": NotificationStrategy(
            user_state="onboarding",
            applicable_themes=[NotificationTheme.empowerment, NotificationTheme.accomplishment, NotificationTheme.unpredictability],
            priority="high", max_daily_for_state=3,
        ),
        "progressing_active": NotificationStrategy(
            user_state="progressing_active",
            applicable_themes=[
                NotificationTheme.accomplishment, NotificationTheme.ownership,
                NotificationTheme.unpredictability, NotificationTheme.empowerment,
            ],
            priority="medium", max_daily_for_state=4, suppress_if_active=True,
        ),
        "progressing_slow": NotificationStrategy(
            user_state="progressing_slow",
            applicable_themes=[NotificationTheme.epic_meaning, NotificationTheme.empowerment, NotificationTheme.loss_avoidance],
            priority="medium", max_daily_for_state=3,
        ),
        "struggling": NotificationStrategy(
            user_state="struggling",
            applicable_themes=[
                NotificationTheme.epic_meaning, NotificationTheme.empowerment,
                NotificationTheme.accomplishment, NotificationTheme.unpredictability,
            ],
            priority="high", max_daily_for_state=3,
        ),
        "bored_skimming": NotificationStrategy(
            user_state="bored_skimming",
            applicable_themes=[
                NotificationTheme.empowerment, NotificationTheme.scarcity,
                NotificationTheme.unpredictability, NotificationTheme.social_influence,
            ],
            priority="high", max_daily_for_state=3,
        ),
        "chapter_transition": NotificationStrategy(
            user_state="chapter_transition",
            applicable_themes=[
                NotificationTheme.unpredictability, NotificationTheme.scarcity, NotificationTheme.accomplishment,
            ],
            priority="high", max_daily_for_state=2,
        ),
        "dormant_short": NotificationStrategy(
            user_state="dormant_short",
            applicable_themes=[
                NotificationTheme.loss_avoidance, NotificationTheme.scarcity,
                NotificationTheme.social_influence, NotificationTheme.unpredictability,
            ],
            priority="high", max_daily_for_state=2,
        ),
        "dormant_long": NotificationStrategy(
            user_state="dormant_long",
            applicable_themes=[
                NotificationTheme.loss_avoidance, NotificationTheme.social_influence,
                NotificationTheme.ownership, NotificationTheme.epic_meaning,
            ],
            priority="high", max_daily_for_state=1,
        ),
        "churned": NotificationStrategy(
            user_state="churned",
            applicable_themes=[
                NotificationTheme.scarcity, NotificationTheme.loss_avoidance, NotificationTheme.ownership,
            ],
            priority="low", max_daily_for_state=1,
        ),
        "completing": NotificationStrategy(
            user_state="completing",
            applicable_themes=[
                NotificationTheme.accomplishment, NotificationTheme.epic_meaning, NotificationTheme.loss_avoidance,
            ],
            priority="medium", max_daily_for_state=2,
        ),
        "completed": NotificationStrategy(
            user_state="completed",
            applicable_themes=[NotificationTheme.accomplishment, NotificationTheme.social_influence],
            priority="low", max_daily_for_state=1,
        ),
    }

    SLOT_THEME_PREFERENCES: dict[int, list[NotificationTheme]] = {
        1: [NotificationTheme.epic_meaning, NotificationTheme.empowerment],
        2: [NotificationTheme.empowerment, NotificationTheme.unpredictability],
        3: [NotificationTheme.scarcity, NotificationTheme.social_influence],
        4: [NotificationTheme.accomplishment, NotificationTheme.ownership],
        5: [NotificationTheme.loss_avoidance, NotificationTheme.ownership],
        6: [],
    }

    def get_strategy(self, user_state: str) -> NotificationStrategy:
        """Legacy: Look up strategy for a user state."""
        return self.STATE_STRATEGIES.get(
            user_state,
            NotificationStrategy(
                user_state=user_state,
                applicable_themes=[NotificationTheme.epic_meaning],
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
        """Legacy: Select theme for a strategy and time slot."""
        available = [t for t in strategy.applicable_themes if t.value not in recent_themes]
        if not available:
            available = list(strategy.applicable_themes)
        slot_prefs = self.SLOT_THEME_PREFERENCES.get(slot, [])
        for pref in slot_prefs:
            if pref in available:
                return pref
        return random.choice(available)
