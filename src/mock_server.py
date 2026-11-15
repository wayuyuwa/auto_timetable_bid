"""Deterministic local UTAR-like server for integration testing."""

import argparse
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

SESSION_EXPIRED_PAGE = "<script>window.parent.location.href='sessionExpired.jsp'</script>"
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
SLOT_TYPES = ("L", "T", "P")
CLASH_MESSAGE = (
    "Insert failed, the time of selected units are clashed with the other "
    "registered units, please verify"
)  # exact text the real portal returns in a script alert


def ensure_state(server):
    """Attach mutable mock state to a server (idempotent).

    registered   : {code: {"name", "credit", "classes": {type: group}}}
    full_slots   : {(code, type, group)} rendered with Avail 0 and no checkbox
    slot_times   : {(code, type, group): (day, start_hour, hours)} overrides
    unknown_units: unit codes that return no slots
    """
    if not hasattr(server, "registered"):
        server.registered = {}
        server.full_slots = set()
        server.slot_times = {}
        server.unknown_units = set()
        server.credits = {}
        server.max_credit = 20
        server.state_lock = threading.Lock()
    return server


def reset_state(server):
    """Forget registrations and overrides (use between test cases)."""
    ensure_state(server)
    for name in ("registered", "full_slots", "slot_times", "unknown_units", "credits"):
        getattr(server, name).clear()
    return server


def slot_time(server, code, slot_type, group):
    """(day, start_hour, hours) for a class. Defaults never clash for up to 9
    distinct numeric course suffixes; tests override via server.slot_times."""
    override = ensure_state(server).slot_times.get((code, slot_type, group))
    if override:
        return override
    digits = re.sub(r"\D", "", code)
    course_index = int(digits) % 9 if digits else 0
    index = course_index * 9 + SLOT_TYPES.index(slot_type) * 3 + (group - 1) % 3
    return DAYS[index % 6], 7 + index // 6, 1


def format_time(start_hour, hours):
    def label(hour):
        meridiem = "AM" if hour % 24 < 12 else "PM"
        return f"{(hour - 1) % 12 + 1:02d}:00 {meridiem}"
    return f"{label(start_hour)} - {label(start_hour + hours)}"

# Real sample captcha image so the OCR path runs against a genuine JPEG.
CAPTCHA_IMAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils", "ocr", "Kaptcha.jpg")

# Mirrors the structure of https://unitreg.utar.edu.my/portal/courseRegStu/login.jsp
# (form name/action, field names, relative captcha src, submit/reset buttons, validate()).
LOGIN_PAGE = """<!doctype html>
<html><head><script>
function validate(){{
  with(document.frmParam){{
    if(reqFregkey.value==''){{ alert("Please key in STUDENT ID"); reqFregkey.focus(); return false; }}
    if(reqPassword.value==''){{ alert("Please key in PASSWORD"); reqPassword.focus(); return false; }}
    if(kaptchafield.value!='undefined'){{
      if(kaptchafield.value==''){{ alert("Please key in the CODE shown"); kaptchafield.focus(); return false; }}
    }}
  }}
  document.frmParam._submit.disabled = true;
  return true;
}}
</script></head>
<body>
<form name="frmParam" action="loginProSurvey.jsp" method="post" onSubmit="return validate();">
<input type="hidden" name="preKap" value="mock-prekap">
<table>
<tr><td>Student ID :</td><td><input type="text" name="reqFregkey" maxlength="10" value=""></td></tr>
<tr><td>Password :</td><td><input type="password" name="reqPassword" maxlength="25" value=""></td></tr>
<tr><td>Code :</td><td><img width="170" src="../Kaptcha.jpg?tmp={tmp}">
<br><INPUT type="text" name="kaptchafield" value="" maxlength="5"></td></tr>
<tr><td colspan="2"><input type="submit" value="Login" name="_submit" class="button">
<input type="reset" value="Reset" name="reset" class="button"></td></tr>
</table>
</form>
<div class="red"  style="font-size:11px">{message}</div>
</body></html>"""

# Messages the real portal shows on login.jsp?message=<code> (codes seen in the
# owner's debug logs, 2026-11-13). notConsultAdviser wording is a stand-in.
PORTAL_MESSAGES = {
    "loginError": "Invalid Student ID or Password",
    "notActive": "Your study status is not allowed to access this system, please check with faculty officer",
    "notConsultAdviser": "You have not consulted your academic adviser. Please consult your adviser before registration",
}
SCENARIO_REJECTIONS = {"not-active": "notActive", "not-adviser": "notConsultAdviser"}


class MockHandler(BaseHTTPRequestHandler):
    server_version = "UTARMock/1.0"

    def log_message(self, format_string, *args):
        print(f"[mock] {self.command} {self.path} - {format_string % args}")

    @property
    def mock_server(self):
        return self.server  # type: ignore[attr-defined]

    def _send(self, body, status=200, content_type="text/html; charset=utf-8"):
        encoded = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _form(self):
        length = int(self.headers.get("Content-Length", "0"))
        self._form_lists = parse_qs(self.rfile.read(length).decode())
        return {key: values[0] for key, values in self._form_lists.items()}

    def do_GET(self):
        path = urlparse(self.path).path
        base = self.mock_server.base_path
        if path == f"{base}/login.jsp":
            code = parse_qs(urlparse(self.path).query).get("message", [""])[0]
            self._send(LOGIN_PAGE.format(tmp=int(time.time() * 1000), message=PORTAL_MESSAGES.get(code, "")))
        elif path.endswith("/Kaptcha.jpg"):
            with open(CAPTCHA_IMAGE, "rb") as image:
                self._send(image.read(), content_type="image/jpeg")
        elif path == f"{base}/registration/studentRegistrationSurvey.jsp":
            if self.mock_server.scenario == "closed":
                # Registration closed: login is accepted, then every page answers
                # "session expired" (what the real portal does outside the window).
                self._send(SESSION_EXPIRED_PAGE)
            else:
                self._send(self._home_page(base, unit_lookup=True))
        elif path == f"{base}/registration/registerCourse.jsp":
            self._send(self._home_page(base, register=True))
        else:
            self._send("Not found", status=404)

    def do_POST(self):
        path = urlparse(self.path).path
        base = self.mock_server.base_path
        form = self._form()
        if path == f"{base}/loginProSurvey.jsp":
            if self.mock_server.scenario == "session-expired":
                self._send("<script>window.parent.location.href='sessionExpired.jsp'</script>")
            elif self.mock_server.scenario in SCENARIO_REJECTIONS:
                # Real portal: the account is refused and the browser is sent
                # back to the login page with a reason code.
                code = SCENARIO_REJECTIONS[self.mock_server.scenario]
                self._send(f"<script>location.href='{base}/login.jsp?message={code}'</script>")
            elif form.get("reqFregkey") == "invalid":
                self._send("<div>Invalid Student ID or Password</div>")
            else:
                self._send(self._home_page(base))
        elif path == f"{base}/registration/registerUnitSurvey.jsp":
            self._send(self._unit_page(form.get("reqUnit", "MOCK1001")))
        elif path == f"{base}/registration/registerUnitProSurvey.jsp":
            if self.mock_server.scenario == "timeout":
                # The request hangs and is lost: nothing is registered, so runs
                # stay deterministic however long the client waits.
                time.sleep(self.mock_server.delay)
                self._send("<div class='red'>Mock request timed out</div>")
            elif self.mock_server.scenario == "register-fail":
                self._send("<div class='red'>Mock registration failed</div>")
            else:
                self._send(self._register(form.get("reqUnit", ""), self._form_lists.get("reqMid", [])))
        else:
            self._send("Not found", status=404)

    def _register(self, unit_code, mids):
        """Apply a registration like the real portal: reject full or clashing
        classes, otherwise record it so the registered-courses page shows it."""
        server = ensure_state(self.mock_server)
        classes = {}
        for mid in mids:
            match = re.fullmatch(r"(.+)-([LTP])(\d+)", mid)
            if match and match.group(1) == unit_code:
                classes[match.group(2)] = int(match.group(3))
        if not unit_code or not classes:
            return "<script>alert('Insert failed, no class selected');</script>"
        with server.state_lock:
            for slot_type, group in classes.items():
                if (unit_code, slot_type, group) in server.full_slots:
                    return "<script>alert('Insert failed, the selected class is full');</script>"
            for other_code, other in server.registered.items():
                if other_code == unit_code:
                    continue
                for slot_type, group in classes.items():
                    day, start, hours = slot_time(server, unit_code, slot_type, group)
                    for other_type, other_group in other["classes"].items():
                        o_day, o_start, o_hours = slot_time(server, other_code, other_type, other_group)
                        if day == o_day and start < o_start + o_hours and o_start < start + hours:
                            return f"<script>alert('{CLASH_MESSAGE}');</script>"
            server.registered[unit_code] = {
                "name": f"MOCK COURSE {unit_code}",
                "credit": server.credits.get(unit_code, 3.0),
                "classes": classes,
            }
        return "<div class='red'>success</div>"

    def _registered_table(self):
        """Registered-courses table in the real portal's layout."""
        server = ensure_state(self.mock_server)
        rows = ['<tr align="center"><td>No</td><td>Type</td><td>Group</td><td>Mode</td>'
                '<td>Class Size</td><td>Day</td><td>Time</td><td>Hour</td><td>Week</td>'
                '<td>Room</td><td></td></tr>']
        number = 0
        for index, (code, entry) in enumerate(list(server.registered.items())):
            rows.append(
                f'<tr valign="middle"><td class="normalTbl-sub3header" colspan="9">{code} - {entry["name"]} [MOCK] '
                f'| Credit Hour : {entry["credit"]} | <span class="red"><b>Register - Pending for Billing</b></span></td>'
                f'<td align="right" class="normalTbl-sub3header" colspan="2">Delete :'
                f'<input id="reqRegId" name="reqRegId" type="checkbox" value="{7000000 + index}"></td></tr>'
            )
            for slot_type in SLOT_TYPES:
                if slot_type not in entry["classes"]:
                    continue
                group = entry["classes"][slot_type]
                day, start, hours = slot_time(server, code, slot_type, group)
                number += 1
                rows.append(
                    f'<tr align="center"><td>{number}</td><td>{slot_type}</td><td>{group}</td><td>Physical</td>'
                    f'<td>100</td><td>{day}</td><td>{format_time(start, hours)}</td><td>{float(hours)}</td>'
                    f'<td>1-14</td><td>M{100 + number}</td>'
                    f'<td><img src="ed.gif" onclick="changeClass(\'{7800000 + number}\')"></td></tr>'
                )
        return f'<table class="registered">{"".join(rows)}</table>'

    def _home_page(self, base, register=False, unit_lookup=False):
        server = ensure_state(self.mock_server)
        register_button = '<input name="Register" value="Register Course">' if register else ""
        # Unit lookup form used by the Playwright scraper (input#reqUnit, Enter submits).
        lookup_form = (
            f'<form name="frmUnit" action="{base}/registration/registerUnitSurvey.jsp" method="post">'
            '<input type="text" id="reqUnit" name="reqUnit" value=""></form>'
            if unit_lookup else ""
        )
        total = sum(entry["credit"] for entry in list(server.registered.values()))
        total_text = str(int(total)) if float(total).is_integer() else str(total)
        return f"""<html><body>
<span>Log Out</span>
<table id="tblGrid"><tr align="left"><td>Student ID</td><td>2103370</td></tr>
<tr align="left"><td>Maximum Credit Hour</td><td>{server.max_credit}</td></tr>
<tr align="left"><td>Total Registered Credit Hour</td><td>{total_text}</td></tr></table>
{register_button}{lookup_form}
{self._registered_table()}
</body></html>"""

    def _unit_page(self, unit_code):
        """Slot table with the real columns: No, Type, Group, Mode, Class Size,
        Week, Day, Time, Hour, Room, Reg., Avail, Remark, checkbox."""
        server = ensure_state(self.mock_server)
        base = self.mock_server.base_path
        rows = []
        if unit_code not in server.unknown_units:
            number = 0
            rows.append(f'<tr><td colspan="14">{unit_code} - MOCK COURSE {unit_code}</td></tr>')
            for slot_type in SLOT_TYPES:
                for group in (1, 2, 3):
                    number += 1
                    day, start, hours = slot_time(server, unit_code, slot_type, group)
                    full = (unit_code, slot_type, group) in server.full_slots
                    checkbox = "" if full else (
                        f'<input type="checkbox" name="reqMid" value="{unit_code}-{slot_type}{group}">'
                    )
                    rows.append(
                        f'<tr align="center"><td>{number}</td><td>{slot_type}</td><td>{group}</td>'
                        f'<td>Physical</td><td>30</td><td>1-14</td><td>{day}</td>'
                        f'<td>{format_time(start, hours)}</td><td>{float(hours)}</td><td>M{100 + number}</td>'
                        f'<td>{30 if full else 10}</td><td>{0 if full else 20}</td><td></td><td>{checkbox}</td></tr>'
                    )
        # register-fail: browser submit shows the alert the Playwright scraper treats as failure.
        onsubmit = (
            ' onsubmit="alert(\'Please select a valid class combination\'); return false;"'
            if self.mock_server.scenario == "register-fail" else ""
        )
        header = ('<tr align="center"><td>No</td><td>Type</td><td>Group</td><td>Mode</td><td>Class Size</td>'
                  '<td>Week</td><td>Day</td><td>Time</td><td>Hour</td><td>Room</td><td>Reg.</td>'
                  '<td>Avail</td><td>Remark</td><td></td></tr>')
        return f"""<html><body><form name="frmSummary" action="{base}/registration/registerUnitProSurvey.jsp" method="post"{onsubmit}>
<input type="hidden" name="reqFregkey" value="2103370"><input type="hidden" name="reqPaperType" value="M">
<input type="hidden" name="reqSession" value="202601"><input type="hidden" name="reqSid" value="mock-sid">
<input type="hidden" name="reqWithClass" value="Y"><table>{header}{"".join(rows)}</table>
<input type="hidden" name="reqUnit" value="{unit_code}"><input type="submit" name="Submit" value="Submit">
</form></body></html>"""


def create_server(host="127.0.0.1", port=0, scenario="success", delay=15):
    """Build a configured mock server without starting it."""
    server = ThreadingHTTPServer((host, port), MockHandler)
    server.daemon_threads = True
    server.base_path = "/portal/courseRegStu"
    server.scenario = scenario
    server.delay = delay
    return ensure_state(server)


def run_server(host, port, scenario, delay):
    server = create_server(host, port, scenario, delay)
    print(f"Mock UTAR server: http://{host}:{port}{server.base_path}")
    print(f"Scenario: {scenario}. Set UTAR_BASE_URL to the URL above.")
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="Run a local UTAR mock server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--scenario",
        choices=("success", "register-fail", "timeout", "session-expired", "closed", "not-active", "not-adviser"),
        default="success",
    )
    parser.add_argument("--delay", type=float, default=15, help="Timeout scenario delay in seconds")
    args = parser.parse_args()
    run_server(args.host, args.port, args.scenario, args.delay)


if __name__ == "__main__":
    main()
