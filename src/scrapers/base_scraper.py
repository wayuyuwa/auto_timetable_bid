"""
Shared scraper interface.
"""

from abc import ABC, abstractmethod
from typing import List

from ..utils.timetable_reader import Course


class BaseScraper(ABC):
    @abstractmethod
    def login(self, student_id: str, password: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def register_courses(self, courses: List[Course]):
        raise NotImplementedError

    @abstractmethod
    def cancel(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def reset_cancellation(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def cleanup(self) -> None:
        raise NotImplementedError
