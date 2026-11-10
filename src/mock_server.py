"""Deterministic local UTAR-like server for integration testing."""

import argparse
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


LOGIN_PAGE = """<!doctype html>
<html><body>
<form name="frmParam" action="{base}/loginProSurvey.jsp" method="post">
<input type="hidden" name="preKap" value="mock-prekap">
<input name="reqFregkey" value="">
<input name="reqPassword" value="" type="password">
<img src="Kaptcha.jpg" alt="captcha">
<input name="kaptchafield" value="">
</form>
</body></html>"""


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
        return {key: values[0] for key, values in parse_qs(self.rfile.read(length).decode()).items()}

    def do_GET(self):
        path = urlparse(self.path).path
        base = self.mock_server.base_path
        if path == f"{base}/login.jsp":
            self._send(LOGIN_PAGE.format(base=base))
        elif path.endswith("/Kaptcha.jpg"):
            self._send(b"mock-captcha", content_type="image/jpeg")
        elif path == f"{base}/registration/studentRegistrationSurvey.jsp":
            self._send(self._home_page(base))
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
            elif form.get("reqFregkey") == "invalid":
                self._send("<div>Invalid Student ID or Password</div>")
            else:
                self._send(self._home_page(base))
        elif path == f"{base}/registration/registerUnitSurvey.jsp":
            self._send(self._unit_page(form.get("reqUnit", "MOCK1001")))
        elif path == f"{base}/registration/registerUnitProSurvey.jsp":
            if self.mock_server.scenario == "timeout":
                time.sleep(self.mock_server.delay)
            if self.mock_server.scenario == "register-fail":
                self._send("<div class='red'>Mock registration failed</div>")
            else:
                self._send("<div class='red'>success</div>")
        else:
            self._send("Not found", status=404)

    def _home_page(self, base, register=False):
        register_button = '<input name="Register" value="Register Course">' if register else ""
        return f"""<html><body>
<span>Log Out</span>
<table id="tblGrid"><tr align="left"><td>Student ID</td><td>2103370</td></tr>
<tr align="left"><td>Total Registered Credit Hour</td><td>18</td></tr></table>
{register_button}
</body></html>"""

    def _unit_page(self, unit_code):
        rows = "".join(
            f'<tr align="center"><td>{unit_code}</td><td>{slot_type}</td><td>{number}</td>'
            f'<td><input name="reqMid" value="{unit_code}-{slot_type}{number}"></td></tr>'
            for slot_type in ("L", "T", "P")
            for number in (1, 2, 3)
        )
        return f"""<html><body><form name="frmSummary">
<input name="reqFregkey" value="2103370"><input name="reqPaperType" value="M">
<input name="reqSession" value="202601"><input name="reqSid" value="mock-sid">
<input name="reqWithClass" value="Y">{rows}<input name="Submit" value="Submit">
</form></body></html>"""


def run_server(host, port, scenario, delay):
    server = ThreadingHTTPServer((host, port), MockHandler)
    server.daemon_threads = True
    server.base_path = "/portal/courseRegStu"
    server.scenario = scenario
    server.delay = delay
    print(f"Mock UTAR server: http://{host}:{port}{server.base_path}")
    print(f"Scenario: {scenario}. Set UTAR_BASE_URL to the URL above.")
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="Run a local UTAR mock server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--scenario",
        choices=("success", "register-fail", "timeout", "session-expired"),
        default="success",
    )
    parser.add_argument("--delay", type=float, default=15, help="Timeout scenario delay in seconds")
    args = parser.parse_args()
    run_server(args.host, args.port, args.scenario, args.delay)


if __name__ == "__main__":
    main()
