"""Event processor — routes progress and profile events to the state engine."""

import time

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import ConfigManager
from app.events.schemas import ProfileEvent, ProgressEvent
from app.state_engine.transitions import StateTransitionManager

logger = structlog.get_logger()


class EventProcessor:
    """Dispatches incoming events to the state transition manager.

    Logs processing time and triggers async notification generation
    when a state transition occurs.
    """

    def __init__(self, db_session: AsyncSession, config_manager: ConfigManager) -> None:
        self.db = db_session
        self.config = config_manager
        self.transition_manager = StateTransitionManager(db_session, config_manager)

    async def process(self, event: ProgressEvent | ProfileEvent) -> None:
        """Process a single event, triggering state transitions and notifications."""
        start_time = time.monotonic()

        if isinstance(event, ProgressEvent):
            new_state = await self.transition_manager.process_event(event)
            elapsed_ms = (time.monotonic() - start_time) * 1000

            if new_state is not None:
                from workers.notification_worker import generate_event_notification

                generate_event_notification.delay(
                    event.user_id, event.journey_id, new_state,
                )

            logger.info(
                "Progress event processed",
                event_id=event.event_id,
                event_type=event.event_type,
                user_id=event.user_id,
                state_changed=new_state is not None,
                new_state=new_state,
                processing_time_ms=round(elapsed_ms, 2),
            )

        elif isinstance(event, ProfileEvent):
            await self.transition_manager.process_profile_event(event)
            elapsed_ms = (time.monotonic() - start_time) * 1000

            logger.info(
                "Profile event processed",
                event_id=event.event_id,
                event_type=event.event_type,
                user_id=event.user_id,
                processing_time_ms=round(elapsed_ms, 2),
            )
