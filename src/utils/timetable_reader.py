"""
Timetable reading utility.
"""

import re
from dataclasses import dataclass
from typing import Dict, List

@dataclass
class Course:
    """Course data class."""
    code: str
    name: str
    slots: Dict[str, List[int]]

class TimetableReader:
    """Timetable reader utility."""
    
    @staticmethod
    def read_course(course_lines: List[str]) -> Course:
        """
        Read course information from lines.
        
        Args:
            course_lines (List[str]): List of lines containing course information
            
        Returns:
            Course: Course object with parsed information
        """
        # Read course code and name
        course_code = course_lines[0].strip()
        course_name = course_lines[1].strip()

        slots = {}
        # Read the slots
        for i in range(2, 5):
            # Get slot type and slot number with regex
            slot = re.search(r'(L|T|P)\((.*)\) -', course_lines[i])
            if not slot:
                continue

            slot_type = slot.group(1)
            slot_nums = list(
                # Convert the map to list
                map(
                    # Convert each item in the list to number
                    lambda num: int(num),
                    # Split the numbers with " or ", this produce a list
                    slot.group(2).split(" or ")
                )
            )

            slots[slot_type] = slot_nums

        return Course(course_code, course_name, slots)

    @staticmethod
    def read_timetable(filename: str) -> List[Course]:
        """
        Read timetable from file.
        
        Args:
            filename (str): Path to timetable file
            
        Returns:
            List[Course]: List of courses
        """
        # Open file
        with open(filename, "r") as file:
            # Read all lines that are not empty
            lines = list(filter(lambda line: line != '\n', file.readlines()))[3:]

        courses = []  # List of courses

        # Read courses
        for i in range(0, len(lines), 5):
            course = TimetableReader.read_course(lines[i:i+5])
            courses.append(course)

        return courses 