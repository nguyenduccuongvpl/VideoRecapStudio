"""Protocols and interfaces for Event Publishing and Subscribing."""

from typing import Any, Callable, Protocol, Type, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class EventPublisher(Protocol):
    """Protocol for publishing events to the system event bus."""

    def publish(self, event: BaseModel) -> None:
        """Publish an event.

        Args:
            event: Any Pydantic-based domain event.
        """
        ...


class EventBus(EventPublisher, Protocol):
    """Protocol for an in-process Event Bus supporting subscription and publishing."""

    def subscribe(self, event_type: Type[T], handler: Callable[[T], Any]) -> None:
        """Subscribe a handler function to a specific event type.

        Args:
            event_type: The class of the Pydantic event.
            handler: Callable triggered when event is published.
        """
        ...

    def unsubscribe(self, event_type: Type[T], handler: Callable[[T], Any]) -> None:
        """Remove a subscriber handler from an event type.

        Args:
            event_type: The class of the Pydantic event.
            handler: The registered callable.
        """
        ...
