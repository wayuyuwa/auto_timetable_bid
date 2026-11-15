import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from src.scrapers.html_parser import extract_student_data, parse_home_page


SAMPLE_ROOT = Path(r"F:\utar")
LOGIN_PAGE = SAMPLE_ROOT / "unitreg" / "unitreg" / "unitreg.utar.edu.my" / "portal" / "courseRegStu" / "login.html"
HOME_PAGE = SAMPLE_ROOT / "unitreg_website" / "unitreg_websites" / "unitreg.utar.edu.my" / "portal" / "courseRegStu" / "registration" / "studentRegistration.html"
UNIT_PAGE = SAMPLE_ROOT / "unitreg_website" / "unitreg_websites" / "unitreg.utar.edu.my" / "portal" / "courseRegStu" / "registration" / "registerUnit.html"


@unittest.skipUnless(SAMPLE_ROOT.exists(), "The supplied F:\\utar sample is not available")
class UtarHtmlParserTests(unittest.TestCase):
    def test_login_page_has_expected_playwright_locators(self):
        soup = BeautifulSoup(LOGIN_PAGE.read_text(encoding="utf-8", errors="ignore"), "html.parser")
        self.assertIsNotNone(soup.select_one("form[name=frmParam]"))
        self.assertIsNotNone(soup.select_one("input[name=reqFregkey]"))
        self.assertIsNotNone(soup.select_one("input[name=reqPassword]"))
        self.assertIsNotNone(soup.select_one("input[name=kaptchafield]"))

    def test_unit_page_extracts_registration_values(self):
        data = extract_student_data(UNIT_PAGE.read_text(encoding="utf-8", errors="ignore"))
        self.assertEqual(data["student_id"], "2103370")
        self.assertEqual(data["paper_type"], "M")
        self.assertEqual(data["req_session"], "202401")
        self.assertEqual(data["reqsid"], "18016")

    def test_home_page_extracts_saved_student_data(self):
        data = parse_home_page(HOME_PAGE.read_text(encoding="utf-8", errors="ignore"))
        self.assertTrue(data)
        self.assertIn("Total Registered Credit Hour", data)
        self.assertEqual(data["Total Registered Credit Hour"], "18")


if __name__ == "__main__":
    unittest.main()
