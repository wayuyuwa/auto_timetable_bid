import re
from Course import Course

def readCourse(course: list[str]):
    # Read course code
    course_code = course[0].strip()
    course_name = course[1].strip()

    slots = {}
    # Read the slots
    for i in range(2, 5):
        # Get slot type and slot number with regex
        slot = re.search(r'(L|T|P)\((.*)\) -', course[i])
        if not slot:
            continue

        slot_type = slot.group(1)
        slot_nums = list(
            # Convert the map to list
            map(
                # Convert each item in the list to number
                lambda num : int(num),
                # Split the numbers with " or ", this produce a list
                slot.group(2).split(" or ")
            )
        )

        slots[slot_type] = slot_nums

    return Course(course_code, course_name, slots)

def readTimetable(filename: str):
    # Open file
    file = open(filename, "r")
    # Read all lines that are not empty
    lines = list(filter(lambda line: line!='\n', file.readlines()))[3:]

    courses = [] # List of courses

    # Read courses
    for i in range(0, len(lines), 5):
        course = readCourse(lines[i:i+5])
        courses.append(course)

    return courses

if __name__ == "__main__":
    courses = readTimetable("MyTimetable.txt")

    print("=====================================")
    for course in courses:
        print(course)
        print("=====================================")