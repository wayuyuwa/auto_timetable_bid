import re

def readCourse(course: list[str]):
    # Read course code
    course_code = course[0].strip()

    slots = {}
    # Read the slots
    for i in range(2, 5):
        slot = re.search(r'(L|T|P)\((.*)\) -', course[i])
        if not slot:
            continue

        slot_type = slot.group(1)
        slot_nums = slot.group(2).split(" or ")

        slots[slot_type] = slot_nums

    return {course_code: slots}

def readTimetable(filename: str):
    # Open file
    file = open(filename, "r")
    # Read all lines that are not empty
    lines = list(filter(lambda line: line!='\n', file.readlines()))[3:]

    courses = []
    for i in range(0, len(lines), 5):
        course = readCourse(lines[i:i+5])
        courses.append(course)

    return courses

if __name__ == "__main__":
    courses = readTimetable("MyTimetable.txt")

    print("=" * 40)
    for course in courses:
        for key, value in course.items():
            print(f"Course code: {key}")
            for key2, value2 in value.items():
                print(f"Slot type: {key2}, Slot nums: {value2}")
            print("=" * 40)