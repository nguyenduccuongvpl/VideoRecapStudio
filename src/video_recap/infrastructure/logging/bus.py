"""In-process thread-safe event bus with subscriber exception isolation and event throttling."""

import logging
import threading
import time
from collections import defaultdict
from typing import Any, Callable, Dict, List, Type, TypeVar
from pydantic import BaseModel
from video_recap.application.events import EventBus
from video_recap.domain.events import StageProgress

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger("EventBus")


class InProcessEventBus(EventBus):
    """Thread-safe event bus with subscriber isolation and progress throttling."""

    def __init__(self, throttling_interval_sec: float = 0.05) -> None:
        """Initialize event bus.

        Args:
            throttling_interval_sec: Minimum time in seconds between intermediate StageProgress events.
        """
        self._lock = threading.Lock()
        self._subscribers: Dict[Type[BaseModel], List[Callable[[Any], Any]]] = defaultdict(list)
        self._throttling_interval = throttling_interval_sec
        # Map: (job_id, stage_name) -> last published time
        self._last_progress_time: Dict[tuple, float] = {}

    def subscribe(self, event_type: Type[T], handler: Callable[[T], Any]) -> None:
        """Subscribe a handler to an event type (thread-safe)."""
        with self._lock:
            if handler not in self._subscribers[event_type]:
                self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: Type[T], handler: Callable[[T], Any]) -> None:
        """Unsubscribe a handler from an event type (thread-safe)."""
        with self._lock:
            if handler in self._subscribers[event_type]:
                self._subscribers[event_type].remove(handler)

    def publish(self, event: BaseModel) -> None:
        """Publish an event to all subscribers with exception isolation and throttling."""
        # 1. Check for progress throttling
        if isinstance(event, StageProgress):
            key = (event.job_id, event.stage.value)
            now = time.time()
            last_time = self._last_progress_time.get(key, 0.0)

            # Do not throttle boundaries (exactly 0.0 or exactly 1.0)
            if 0.0 < event.progress < 1.0:
                if (now - last_time) < self._throttling_interval:
                    return  # Throttled!
                self._last_progress_time[key] = now

        # 2. Get copy of handlers under lock to avoid holding lock during execution
        with self._lock:
            # Match direct subscribers of this class type
            handlers = list(self._subscribers[type(event)])

        # 3. Dispatch to handlers with subscriber isolation
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                # Log exception with full chain, isolating other subscribers
                logger.error(
                    f"Subscriber error in handler '{handler.__name__ if hasattr(handler, '__name__') else handler}' "
                    f"during event '{type(event).__name__}': {e}",
                    exc_info=True,
                )
