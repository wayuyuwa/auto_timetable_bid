"""Deterministic local UTAR-like server for integration testing."""

import argparse
import os
import re
import secrets
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# What the real portal answers when the session is missing or has ended (HTTP 200, short script;
# verified 2026-11-16: it lands on .../courseRegStu/sessionExpiredSurvey.jsp).
SESSION_EXPIRED_PAGE = "<script>window.parent.location.href='/portal/courseRegStu/sessionExpiredSurvey.jsp'</script>"
# Pages that work without a logged-in session; every other page needs one.
OPEN_PAGES = {"login.jsp", "Kaptcha.jpg", "loginProSurvey.jsp", "indexSurvey.jsp", "sessionExpiredSurvey.jsp"}
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
    expire_rules : {path suffix: {"mode", "times"}} one-shot failures, see expire_next()
    sessions     : {JSESSIONID: {"user", "alive", "seen"}}; active_by_user: {student id: JSESSIONID}
    passids      : {token: {"sid", "visits"}} one-time login addresses (indexSurvey.jsp?passid=)
    require_session / single_session / session_timeout: how real the sessions are (see below)
    hits         : Counter of requests per page name (every request, answered or not)
    processed_submits: bids that really reached the registration logic
    """
    if not hasattr(server, "registered"):
        server.registered = {}
        server.full_slots = set()
        server.slot_times = {}
        server.unknown_units = set()
        server.credits = {}
        server.max_credit = 20
        server.expire_rules = {}
        server.sessions = {}
        server.active_by_user = {}
        server.passids = {}
        # Behaviour of the real portal (verified 2026-11-16, see docs/KNOWLEDGE.md): pages need the
        # JSESSIONID cookie of a logged-in session; a second login ends the first session.
        server.require_session = True
        # False: like the real portal while registration is closed (checked 2026-11-17) the registration
        # page and the unit lookup answer with the registered-courses page and no registration form.
        server.registration_open = True
        server.single_session = True
        server.session_timeout = None  # idle seconds before a session ends; the real value is not measured
        server.hits = Counter()
        server.processed_submits = 0
        server.state_lock = threading.Lock()
    return server


def reset_state(server):
    """Forget registrations and overrides (use between test cases)."""
    ensure_state(server)
    for name in ("registered", "full_slots", "slot_times", "unknown_units", "credits", "expire_rules", "hits",
                 "sessions", "active_by_user", "passids"):
        getattr(server, name).clear()
    server.processed_submits = 0
    server.registration_open = True
    return server


def expire_next(server, path_suffix, mode="js", times=1):
    """Make the next `times` requests whose path ends with `path_suffix` fail once.

    js            answer with the portal's "session expired" script (what the real portal does)
    loginpage     answer with the plain login page (HTTP 200, no "session expired" text)
    hang          answer only after server.delay seconds, without processing the request
    apply-then-js process the bid, then answer "session expired" (the answer was lost)
    """
    ensure_state(server).expire_rules[path_suffix] = {"mode": mode, "times": times}


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
    # Seen as the address login.jsp?message=notSupportTab (2026-11-16); the wording is a stand-in.
    "notSupportTab": "Multiple tabs or windows are not supported",
}
SCENARIO_REJECTIONS = {"not-active": "notActive", "not-adviser": "notConsultAdviser"}


class MockHandler(BaseHTTPRequestHandler):
    server_version = "UTARMock/1.0"

    def log_message(self, format_string, *args):
        print(f"[mock] {self.command} {self.path} - {format_string % args}")

    @property
    def mock_server(self):
        return self.server  # type: ignore[attr-defined]

    def _send(self, body, status=200, content_type="text/html; charset=utf-8", cookies=(), location=None):
        encoded = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        if location:
            self.send_header("Location", location)
        for cookie in cookies:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(encoded)

    def _redirect(self, location, cookies=()):
        self._send("", status=302, location=location, cookies=cookies)

    def _session(self):
        """(id, record) of the first live session named by a JSESSIONID cookie, else (None, None)."""
        server = ensure_state(self.mock_server)
        now = time.monotonic()
        ids = [part.split("=", 1)[1].strip() for part in self.headers.get("Cookie", "").split(";")
               if part.strip().startswith("JSESSIONID=")]
        with server.state_lock:
            for sid in ids:
                record = server.sessions.get(sid)
                if not record or not record["alive"]:
                    continue
                if server.session_timeout and now - record["seen"] > server.session_timeout:
                    record["alive"] = False
                    continue
                record["seen"] = now
                return sid, record
        return None, None

    def _blocked(self):
        """True (after answering "session expired") when the page needs a logged-in session and has none."""
        server = ensure_state(self.mock_server)
        path = urlparse(self.path).path
        if not server.require_session or path.rsplit("/", 1)[-1] in OPEN_PAGES:
            return False
        _sid, record = self._session()
        if record is not None and record["user"]:
            return False
        if self.command == "POST":
            self._form()  # read the body before answering
        self._send(SESSION_EXPIRED_PAGE)
        return True

    def _login_success(self, user):
        """Real behaviour: the session cookie is set again after login (scoped to the app folder),
        a second login ends the first session, and the browser follows a one-time passid address."""
        server = ensure_state(self.mock_server)
        base = server.base_path
        sid, record = self._session()
        cookies = []
        with server.state_lock:
            if record is None:
                sid = secrets.token_hex(20)
                record = server.sessions[sid] = {"user": None, "alive": True, "seen": time.monotonic()}
                cookies.append(f"JSESSIONID={sid}; Path=/portal; HttpOnly")
            if server.single_session:
                previous = server.active_by_user.get(user)
                if previous and previous != sid and previous in server.sessions:
                    server.sessions[previous]["alive"] = False
            record["user"] = user
            server.active_by_user[user] = sid
            token = secrets.token_urlsafe(24)
            server.passids[token] = {"sid": sid, "visits": 0}
        cookies.append(f"JSESSIONID={sid}; Path={base}")
        self._redirect(f"{base}/indexSurvey.jsp?passid={token}", cookies)

    def _index_survey(self, token):
        """indexSurvey.jsp?passid=<token>: two redirects right after login; opened again later (for
        example pasted into a second tab) the portal refuses with login.jsp?message=notSupportTab and
        the session behind the token ends too (verified 2026-11-16)."""
        server = ensure_state(self.mock_server)
        base = server.base_path
        with server.state_lock:
            entry = server.passids.get(token)
            visits = 0
            if entry is not None:
                entry["visits"] += 1
                visits = entry["visits"]
                if visits > 2 and entry["sid"] in server.sessions:
                    server.sessions[entry["sid"]]["alive"] = False
        if entry is None:
            self._send(SESSION_EXPIRED_PAGE)
        elif visits == 1:
            self._redirect(f"{base}/indexSurvey.jsp?passid={token}")
        elif visits == 2:
            self._redirect(f"{base}/registration/studentRegistrationSurvey.jsp")
        else:
            self._redirect(f"{base}/login.jsp?message=notSupportTab")

    def _form(self):
        length = int(self.headers.get("Content-Length", "0"))
        self._form_lists = parse_qs(self.rfile.read(length).decode())
        return {key: values[0] for key, values in self._form_lists.items()}

    def _gate(self):
        """Count the request and apply a one-shot test failure (expire_next).
        Returns True when the request was answered here."""
        server = ensure_state(self.mock_server)
        path = urlparse(self.path).path
        with server.state_lock:
            server.hits[path.rsplit("/", 1)[-1]] += 1
            rule = next((r for suffix, r in server.expire_rules.items()
                         if path.endswith(suffix) and r["times"] > 0), None)
            if rule is not None:
                rule["times"] -= 1
        if rule is None:
            return False
        if self.command == "POST":
            self._form()
        mode = rule["mode"]
        if mode == "loginpage":
            self._send(LOGIN_PAGE.format(tmp=0, message=""))
        elif mode == "hang":
            time.sleep(server.delay)
            self._send("<div class='red'>Mock request answered too late</div>")
        else:
            if mode == "apply-then-js":
                form = {key: values[0] for key, values in self._form_lists.items()}
                self._register(form.get("reqUnit", ""), self._form_lists.get("reqMid", []))
            self._send(SESSION_EXPIRED_PAGE)
        return True

    def do_GET(self):
        if not self._gate() and not self._blocked():
            self._handle_get()

    def do_POST(self):
        if not self._gate() and not self._blocked():
            self._handle_post()

    def _handle_get(self):
        path = urlparse(self.path).path
        base = self.mock_server.base_path
        if path == f"{base}/login.jsp":
            code = parse_qs(urlparse(self.path).query).get("message", [""])[0]
            cookies = []
            sid, record = self._session()
            if record is None:  # the portal hands out a session cookie with the login page
                server = ensure_state(self.mock_server)
                sid = secrets.token_hex(20)
                with server.state_lock:
                    server.sessions[sid] = {"user": None, "alive": True, "seen": time.monotonic()}
                cookies.append(f"JSESSIONID={sid}; Path=/portal; HttpOnly")
            self._send(LOGIN_PAGE.format(tmp=int(time.time() * 1000), message=PORTAL_MESSAGES.get(code, "")),
                       cookies=cookies)
        elif path == f"{base}/indexSurvey.jsp":
            self._index_survey(parse_qs(urlparse(self.path).query).get("passid", [""])[0])
        elif path == f"{base}/sessionExpiredSurvey.jsp":
            self._send("<html><body>Your session has expired. Please log in again.</body></html>")
        elif path.endswith("/Kaptcha.jpg"):
            with open(CAPTCHA_IMAGE, "rb") as image:
                self._send(image.read(), content_type="image/jpeg")
        elif path == f"{base}/registration/studentRegistrationSurvey.jsp":
            if self.mock_server.scenario == "closed":
                # Registration closed: login is accepted, then every page answers
                # "session expired" (what the real portal does outside the window).
                self._send(SESSION_EXPIRED_PAGE)
            else:
                self._send(self._home_page(base, unit_lookup=ensure_state(self.mock_server).registration_open))
        elif path == f"{base}/registration/registerCourse.jsp":
            self._send(self._home_page(base, register=True))
        else:
            self._send("Not found", status=404)

    def _handle_post(self):
        path = urlparse(self.path).path
        base = self.mock_server.base_path
        form = self._form()
        if path == f"{base}/loginProSurvey.jsp":
            if self.mock_server.scenario == "session-expired":
                self._send(SESSION_EXPIRED_PAGE)
            elif self.mock_server.scenario in SCENARIO_REJECTIONS:
                # Real portal: the account is refused and the browser is sent
                # back to the login page with a reason code.
                code = SCENARIO_REJECTIONS[self.mock_server.scenario]
                self._send(f"<script>location.href='{base}/login.jsp?message={code}'</script>")
            elif form.get("reqFregkey") == "invalid":
                self._send("<div>Invalid Student ID or Password</div>")
            else:
                self._login_success(form.get("reqFregkey", ""))
        elif path == f"{base}/registration/registerUnitSurvey.jsp":
            if not ensure_state(self.mock_server).registration_open:
                self._send(self._home_page(base))  # closed: no unit form, just the registered courses
            else:
                self._send(self._unit_page(form.get("reqUnit", "MOCK1001")))
        elif path == f"{base}/registration/registerUnitProSurvey.jsp":
            if self.mock_server.scenario == "timeout":
                # The request hangs and is lost: nothing is registered, so runs
                # stay deterministic however long the client waits.
                time.sleep(self.mock_server.delay)
                self._send("<div class='red'>Mock request timed out</div>")
            elif not ensure_state(self.mock_server).registration_open:
                self._send(self._home_page(base))  # closed: nothing is registered
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
        with server.state_lock:
            server.processed_submits += 1
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
    ensure_state(server).registration_open = scenario != "registration-closed"
    return server


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
        choices=("success", "register-fail", "timeout", "session-expired", "closed", "not-active", "not-adviser",
                 "registration-closed"),
        default="success",
    )
    parser.add_argument("--delay", type=float, default=15, help="Timeout scenario delay in seconds")
    args = parser.parse_args()
    run_server(args.host, args.port, args.scenario, args.delay)


if __name__ == "__main__":
    main()
