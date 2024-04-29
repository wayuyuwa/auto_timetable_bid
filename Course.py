class Course:
    code: str
    name: str
    slots: dict[str, list[int]]

    def __init__(self, code: str, name: str, slots: dict[str, list[int]]):
        self.code = code
        self.name = name
        self.slots = slots

    def __str__(self):
        return f"Course Code: {self.code}\n" \
            f"Course Name: {self.name}\n" \
            f"Slots: {self.slots}"

if __name__ == "__main__":
    course = Course("CSC1001", "Programming", {"L": [1, 2], "T": [3, 4]})
    print(course)
    # Output:
    # Course Code: CSC1001
    # Course Name: Programming
    # Slots: {'L': [1, 2], 'T': [3, 4]}