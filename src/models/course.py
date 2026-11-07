"""
Course data model.
"""

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class Course:
    """Course data class representing a university course."""
    
    code: str
    name: str
    slots: Dict[str, List[int]]
    
    def __str__(self):
        """String representation of the course."""
        return f"{self.code} - {self.name}"
    
    def get_slot_display(self) -> str:
        """Get a formatted string of all slots."""
        slot_strings = []
        for slot_type, slot_numbers in self.slots.items():
            slot_strings.append(f"{slot_type}({', '.join(map(str, slot_numbers))})")
        return " | ".join(slot_strings)
