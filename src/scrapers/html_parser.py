"""Pure HTML parsing helpers shared by browser and HTTP scrapers."""

from bs4 import BeautifulSoup


def extract_student_data(html: str) -> dict:
    """Extract registration form values from a UTAR unit page."""
    soup = BeautifulSoup(html, "html.parser")

    def value(name: str, required: bool = True) -> str:
        field = soup.find("input", {"name": name})
        if not field or (required and not field.get("value")):
            raise ValueError(f"Missing required field: {name}")
        return field.get("value", "")

    return {
        "student_id": value("reqFregkey"),
        "paper_type": value("reqPaperType"),
        "req_session": value("reqSession"),
        "reqsid": value("reqSid"),
        "req_with_class": value("reqWithClass", required=False),
    }


def find_course_value(html: str, group_code: str) -> str | None:
    """Find the hidden request value for a class group such as ``L1``."""
    soup = BeautifulSoup(html, "html.parser")
    for row in soup.find_all("tr", align="center"):
        columns = row.find_all("td")
        if len(columns) < 3:
            continue
        actual_code = f"{columns[1].get_text(strip=True)}{columns[2].get_text(strip=True)}"
        checkbox = row.find("input", {"name": "reqMid"})
        if actual_code == group_code and checkbox and checkbox.get("value"):
            return checkbox["value"]
    return None


def parse_home_page(html: str) -> dict:
    """Extract the key/value table from the logged-in registration page."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "tblGrid"})
    if not table:
        return {}

    data = {}
    for row in table.find_all("tr", align="left"):
        columns = row.find_all("td")
        if len(columns) < 2:
            continue
        data[columns[0].get_text(strip=True)] = columns[1].get_text(strip=True)
        if len(columns) == 4:
            data[columns[2].get_text(strip=True)] = columns[3].get_text(strip=True)
    return data


# --------------------------------------------------------------------------
# Registered-courses page ("My Course Registration") and unit slot page.
# Structure taken from real UTAR pages:
#   course header row : "CODE - NAME [FAC] | Credit Hour : 4.0 | <status>"
#                       plus a reqRegId checkbox (delete)
#   class rows        : No, Type, Group, Mode, Class Size, Day, Time, Hour,
#                       Week, Room, edit icon -> changeClass('<rgsid>')
#   a class meeting twice a week continues on a short row (Day, Time, ...)
# --------------------------------------------------------------------------

import re

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_HEADER_RE = re.compile(
    r"^(?P<code>[A-Z0-9]+)\s*-\s*(?P<name>.*?)\s*(?:\[[^\]]*\])?\s*"
    r"\|\s*Credit Hour\s*:\s*(?P<credit>[\d.]+)\s*(?:\|\s*(?P<status>.*))?$",
    re.S,
)
_RGSID_RE = re.compile(r"changeClass\('?(\d+)'?\)")
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*([AP]M)\s*-\s*(\d{1,2}):(\d{2})\s*([AP]M)", re.I)


def _text(cell) -> str:
    return re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()


def parse_time_range(text: str):
    """'09:00 AM - 10:30 AM' -> (540, 630) minutes from midnight, or None."""
    match = _TIME_RE.search(text or "")
    if not match:
        return None

    def minutes(hour, minute, meridiem):
        hour = int(hour) % 12 + (12 if meridiem.upper() == "PM" else 0)
        return hour * 60 + int(minute)

    return minutes(*match.group(1, 2, 3)), minutes(*match.group(4, 5, 6))


def _session(day, time_text, hours="", weeks="", room=""):
    span = parse_time_range(time_text)
    return {
        "day": day,
        "time": time_text,
        "start": span[0] if span else None,
        "end": span[1] if span else None,
        "hours": hours,
        "weeks": weeks,
        "room": room,
    }


def _day_index(cells):
    for index, value in enumerate(cells):
        if value in _DAYS:
            return index
    return -1


def parse_registered_courses(html: str) -> list:
    """Courses currently registered, with their classes and meeting times."""
    soup = BeautifulSoup(html, "html.parser")
    courses = []
    for checkbox in soup.find_all("input", {"name": "reqRegId"}):
        header_row = checkbox.find_parent("tr")
        if header_row is None:
            continue
        header_cell = header_row.find("td")
        match = _HEADER_RE.match(_text(header_cell)) if header_cell else None
        if not match:
            continue
        course = {
            "code": match.group("code"),
            "name": match.group("name").strip(),
            "credit_hours": float(match.group("credit")),
            "status": (match.group("status") or "").strip(),
            "reg_id": checkbox.get("value", ""),
            "classes": [],
        }
        for row in header_row.find_next_siblings("tr"):
            if row.find("input", {"name": "reqRegId"}):
                break  # next course
            cells = [_text(cell) for cell in row.find_all("td")]
            day_at = _day_index(cells)
            if day_at < 0:
                continue
            if day_at >= 5:  # full class row: No, Type, Group, Mode, Size, Day, Time, Hour, Week, Room
                rgsid = _RGSID_RE.search(str(row))
                try:
                    group = int(cells[2])
                except ValueError:
                    continue
                course["classes"].append({
                    "type": cells[1],
                    "group": group,
                    "mode": cells[3],
                    "class_size": cells[4],
                    "rgsid": rgsid.group(1) if rgsid else "",
                    "sessions": [_session(cells[day_at], *cells[day_at + 1:day_at + 5])],
                })
            elif course["classes"]:  # continuation row: Day, Time, Hour, Week, Room
                course["classes"][-1]["sessions"].append(
                    _session(cells[day_at], *cells[day_at + 1:day_at + 5])
                )
        courses.append(course)
    return courses


def parse_unit_slots(html: str) -> list:
    """Class slots offered for a unit, with timing and availability.

    Real columns: No, Type, Group, Mode, Class Size, Week, Day, Time, Hour,
    Room, Reg., Avail, Remark, checkbox. A full slot has no reqMid checkbox.
    """
    soup = BeautifulSoup(html, "html.parser")
    slots = []
    for row in soup.find_all("tr", align="center"):
        cells = [_text(cell) for cell in row.find_all("td")]
        day_at = _day_index(cells)
        if day_at < 0:
            continue
        if day_at >= 5:  # full slot row
            try:
                group = int(cells[2])
            except (ValueError, IndexError):
                continue
            checkbox = row.find("input", {"name": "reqMid"})

            def number(index):
                try:
                    return int(cells[index])
                except (ValueError, IndexError):
                    return None

            slots.append({
                "type": cells[1],
                "group": group,
                "mode": cells[3],
                "class_size": cells[4],
                "registered": number(day_at + 4),
                "available": number(day_at + 5),
                "mid": checkbox.get("value") if checkbox else None,
                "selectable": bool(checkbox) and not checkbox.has_attr("disabled"),
                "sessions": [_session(cells[day_at], cells[day_at + 1], cells[day_at + 2],
                                      cells[day_at - 1], cells[day_at + 3])],
            })
        elif slots:  # continuation row for a second weekly meeting
            extra = cells[day_at:day_at + 4] + [""] * 4
            slots[-1]["sessions"].append(
                _session(extra[0], extra[1], extra[2], slots[-1]["sessions"][0]["weeks"], extra[3])
            )
    return slots


def sessions_clash(first: list, second: list) -> bool:
    """True if any two meetings fall on the same day with overlapping times."""
    for a in first:
        for b in second:
            if a["day"] != b["day"] or None in (a["start"], a["end"], b["start"], b["end"]):
                continue
            if a["start"] < b["end"] and b["start"] < a["end"]:
                return True
    return False
