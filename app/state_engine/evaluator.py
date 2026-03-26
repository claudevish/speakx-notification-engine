"""Behavioral signal evaluator for learner journey state decisions.

Analyses a sliding window of recent activity metrics (scores, retry
counts, completion speed) to produce discrete behavioural signal labels
such as ``"struggling"``, ``"bored"``, or ``"near_completion"``.  These
signals drive the state-machine transitions in
:class:`StateTransitionManager`.
"""

from typing import Optional

import structlog

from app.config.manager import ConfigManager
from app.events.schemas import ProgressEvent
from app.models.user import UserJourneyState

logger = structlog.get_logger()


class BehavioralEvaluator:
    """Evaluates learner activity metrics to produce behavioral signals.

    Uses configurable thresholds (via :class:`ConfigManager`) and a
    rolling window of recent scores, retries, and speeds stored on the
    ``UserJourneyState`` to classify the learner's current engagement
    pattern.

    Attributes:
        config: The runtime configuration manager providing thresholds.
    """

    def __init__(self, config_manager: ConfigManager) -> None:
        """Initialise the evaluator with a configuration source.

        Args:
            config_manager: Provides runtime-configurable thresholds for
                signal detection (e.g. struggling retry rate, boredom
                speed percentage).
        """
        self.config = config_manager

    async def evaluate_signals(
        self, user_state: UserJourneyState, event: ProgressEvent,
    ) -> list[str]:
        """Evaluate the user's recent activity and return behavioral signals.

        Updates the sliding window with the latest event data, then checks
        each signal condition against configurable thresholds.

        Args:
            user_state: The persisted journey state containing rolling
                window aggregates and chapter progress.
            event: The current progress event supplying score, retry count,
                and time spent values.

        Returns:
            A list of signal label strings.  Possible values are
            ``"struggling"``, ``"bored"``, and ``"near_completion"``.
        """
        self.update_sliding_window(
            user_state,
            score=event.score,
            retry_count=event.retry_count,
            time_spent=event.time_spent_seconds,
        )

        signals: list[str] = []

        retry_threshold = await self.config.get("struggling_retry_rate_threshold", 0.5)
        score_threshold = await self.config.get("struggling_avg_score_threshold", 60)

        retry_rate = user_state.retry_count_window / 5.0 if user_state.retry_count_window else 0.0
        is_struggling = retry_rate > retry_threshold or (
            user_state.avg_score_window > 0 and user_state.avg_score_window < score_threshold
        )
        if is_struggling:
            signals.append("struggling")

        speed_pct = await self.config.get("bored_speed_threshold_pct", 0.3)
        completion_threshold = await self.config.get("bored_completion_rate_threshold", 0.9)
        expected_speed = 300.0
        is_bored = (
            user_state.avg_completion_speed > 0
            and user_state.avg_completion_speed < speed_pct * expected_speed
            and self._calc_completion_rate(user_state) > completion_threshold
        )
        if is_bored:
            signals.append("bored")

        near_pct = await self.config.get("near_completion_progress_pct", 70)
        if self._is_near_completion(user_state, near_pct):
            signals.append("near_completion")

        logger.debug(
            "Behavioral signals evaluated",
            user_id=event.user_id,
            signals=signals,
            retry_rate=retry_rate,
            avg_score=user_state.avg_score_window,
            avg_speed=user_state.avg_completion_speed,
        )

        return signals

    def update_sliding_window(
        self,
        user_state: UserJourneyState,
        score: Optional[float],
        retry_count: Optional[int],
        time_spent: Optional[float],
    ) -> None:
        """Append latest activity metrics to the rolling window and recompute aggregates.

        Maintains fixed-size (5-element) sliding windows for scores, retry
        counts, and completion speeds in the user state's metadata.  After
        appending, recalculates the aggregate fields on ``user_state``.

        Args:
            user_state: The persisted journey state whose window aggregates
                and metadata will be updated in place.
            score: The activity score (0--100), or ``None`` if not applicable.
            retry_count: Number of retries for the activity, or ``None``.
            time_spent: Time spent in seconds on the activity, or ``None``.
        """
        meta = user_state.metadata_ or {}
        scores: list[float] = meta.get("score_window", [])
        retries: list[int] = meta.get("retry_window", [])
        speeds: list[float] = meta.get("speed_window", [])

        if score is not None:
            scores.append(score)
            scores = scores[-5:]

        if retry_count is not None:
            retries.append(retry_count)
            retries = retries[-5:]

        if time_spent is not None:
            speeds.append(time_spent)
            speeds = speeds[-5:]

        avg_score = (
            sum(scores) / len(scores) if scores else 0.0
        )
        user_state.avg_score_window = max(0.0, min(100.0, avg_score))
        user_state.retry_count_window = max(0, sum(retries))
        avg_speed = (
            sum(speeds) / len(speeds) if speeds else 0.0
        )
        user_state.avg_completion_speed = max(0.0, avg_speed)

        meta["score_window"] = scores
        meta["retry_window"] = retries
        meta["speed_window"] = speeds
        user_state.metadata_ = meta

    @staticmethod
    def _calc_completion_rate(user_state: UserJourneyState) -> float:
        """Calculate the overall completion rate across all chapters.

        Args:
            user_state: The journey state containing ``chapter_progress``.

        Returns:
            A float between 0.0 and 1.0 representing the ratio of completed
            items to total items.  Returns 0.0 if no items are tracked.
        """
        progress = user_state.chapter_progress or {}
        total_completed = 0
        total_items = 0
        for _ch, data in progress.items():
            if isinstance(data, dict):
                total_completed += data.get("completed", 0)
                total_items += data.get("total", 0)
        if total_items == 0:
            return 0.0
        return total_completed / total_items

    @staticmethod
    def _is_near_completion(user_state: UserJourneyState, threshold_pct: int) -> bool:
        """Check whether the user is near completing their journey.

        Looks at the last (highest-sorted) chapter in ``chapter_progress``
        and returns ``True`` if it is marked as the final chapter and its
        completion percentage meets or exceeds the threshold.

        Args:
            user_state: The journey state containing ``chapter_progress``.
            threshold_pct: The minimum completion percentage (0--100) in the
                final chapter required to consider the user near completion.

        Returns:
            ``True`` if the user's progress in the final chapter meets the
            threshold, ``False`` otherwise.
        """
        progress = user_state.chapter_progress or {}
        if not progress:
            return False
        sorted_chapters = sorted(progress.keys())
        if not sorted_chapters:
            return False
        last_chapter = sorted_chapters[-1]
        ch_data = progress[last_chapter]
        if not isinstance(ch_data, dict):
            return False
        completed = ch_data.get("completed", 0)
        total = ch_data.get("total", 1)
        is_final = ch_data.get("is_final", False)
        pct = (completed / total) * 100 if total > 0 else 0
        return pct >= threshold_pct and is_final
