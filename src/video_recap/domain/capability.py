"""Domain models for capability verification."""

from typing import List
from pydantic import BaseModel


class CapabilityItem(BaseModel):
    """Represents a single system or package capability check."""

    name: str
    status: str  # "SUCCESS", "WARNING", "FAILED"
    required: bool
    details: str


class CapabilityReport(BaseModel):
    """Represents the compiled capability report for the system."""

    items: List[CapabilityItem]

    @property
    def is_valid(self) -> bool:
        """Verify if all required capabilities are satisfied.

        Returns:
            True if all required capabilities have status 'SUCCESS', False otherwise.
        """
        return all(item.status == "SUCCESS" for item in self.items if item.required)
