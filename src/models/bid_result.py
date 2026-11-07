"""
Bid result data model.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
from datetime import datetime


class BidStatus(Enum):
    """Status of a course bidding attempt."""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SESSION_EXPIRED = "session_expired"
    ALREADY_REGISTERED = "already_registered"
    FULL = "full"
    CANCELLED = "cancelled"


@dataclass
class BidResult:
    """Result of a course bidding attempt."""
    
    course_code: str
    course_name: str
    status: BidStatus
    message: str
    timestamp: datetime = None
    error_details: Optional[str] = None
    
    def __post_init__(self):
        """Initialize timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now()
    
    def is_successful(self) -> bool:
        """Check if the bid was successful."""
        return self.status == BidStatus.SUCCESS
    
    def __str__(self):
        """String representation of the result."""
        time_str = self.timestamp.strftime("%H:%M:%S")
        return f"[{time_str}] {self.course_code}: {self.status.value} - {self.message}"
