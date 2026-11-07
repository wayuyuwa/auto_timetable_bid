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
