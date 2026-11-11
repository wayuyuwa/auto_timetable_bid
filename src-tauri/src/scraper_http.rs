//! HTTP scraper: reqwest (with a cookie jar) + scraper for HTML parsing.
//! The Rust equivalent of src/scrapers/beautifulsoup_scraper.py, written to the
//! same endpoint/form contract the mock server (src/mock_server.py) mirrors from
//! the real UTAR portal.

use crate::config::{self, Urls};
use crate::models::Course;
use scraper::{Html, Selector};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

const TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Debug)]
pub enum ScrapeError {
    Cancelled,
    SessionExpired,
    BadCredentials,
    Network(String),
    Other(String),
}

impl std::fmt::Display for ScrapeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ScrapeError::Cancelled => write!(f, "Operation cancelled by user"),
            ScrapeError::SessionExpired => write!(f, "Your session expired. Please log in again."),
            ScrapeError::BadCredentials => {
                write!(f, "Login failed. Please check your credentials.")
            }
            ScrapeError::Network(m) => write!(f, "Network error: {m}"),
            ScrapeError::Other(m) => write!(f, "{m}"),
        }
    }
}

type Result<T> = std::result::Result<T, ScrapeError>;

pub struct HttpScraper {
    client: reqwest::blocking::Client,
    urls: Urls,
    logged_in: bool,
}

impl HttpScraper {
    pub fn new() -> Result<HttpScraper> {
        let client = reqwest::blocking::Client::builder()
            .cookie_store(true)
            .danger_accept_invalid_certs(true) // UTAR serves an incomplete chain
            .timeout(TIMEOUT)
            .user_agent("Mozilla/5.0")
            .build()
            .map_err(|e| ScrapeError::Network(e.to_string()))?;
        Ok(HttpScraper {
            client,
            urls: Urls::load(),
            logged_in: false,
        })
    }

    pub fn is_logged_in(&self) -> bool {
        self.logged_in
    }

    fn check_cancel(cancel: &AtomicBool) -> Result<()> {
        if cancel.load(Ordering::SeqCst) {
            Err(ScrapeError::Cancelled)
        } else {
            Ok(())
        }
    }

    pub fn login(&mut self, student_id: &str, password: &str, cancel: &AtomicBool) -> Result<()> {
        Self::check_cancel(cancel)?;

        // 1. Fetch the login page to read preKap and confirm the captcha exists.
        let login_body = self
            .client
            .get(self.urls.login())
            .send()
            .and_then(|r| r.text())
            .map_err(|e| ScrapeError::Network(e.to_string()))?;
        let prekap = attr(&login_body, "input[name=preKap]", "value").unwrap_or_default();

        // 2. Solve the captcha (or use the test override).
        Self::check_cancel(cancel)?;
        let code = match config::mock_captcha() {
            Some(value) => value,
            None => {
                let image = self
                    .client
                    .get(self.urls.captcha())
                    .send()
                    .and_then(|r| r.bytes())
                    .map_err(|e| ScrapeError::Network(e.to_string()))?;
                crate::ocr::solve(&image).map_err(|e| ScrapeError::Other(e.to_string()))?
            }
        };

        // 3. Submit the login form.
        Self::check_cancel(cancel)?;
        let body = self
            .client
            .post(self.urls.login_process())
            .form(&[
                ("reqFregkey", student_id),
                ("reqPassword", password),
                ("kaptchafield", code.as_str()),
                ("preKap", prekap.as_str()),
            ])
            .send()
            .and_then(|r| r.text())
            .map_err(|e| ScrapeError::Network(e.to_string()))?;

        if body.contains("sessionExpired") {
            return Err(ScrapeError::SessionExpired);
        }
        if body.contains("Invalid") {
            return Err(ScrapeError::BadCredentials);
        }

        // 4. Confirm we reached the logged-in home page.
        Self::check_cancel(cancel)?;
        let home = self
            .client
            .get(self.urls.home())
            .send()
            .and_then(|r| r.text())
            .map_err(|e| ScrapeError::Network(e.to_string()))?;
        if !home.contains("Log Out") {
            return Err(ScrapeError::BadCredentials);
        }
        self.logged_in = true;
        Ok(())
    }

    /// Register one course. Returns (message, success).
    pub fn register_course(
        &self,
        course: &Course,
        cancel: &AtomicBool,
    ) -> Result<(String, bool)> {
        Self::check_cancel(cancel)?;

        // Fetch the unit page (hidden fields + one row per class slot).
        let page = self
            .client
            .post(self.urls.register_unit())
            .form(&[("reqUnit", course.code.as_str())])
            .send()
            .and_then(|r| r.text())
            .map_err(|e| ScrapeError::Network(e.to_string()))?;

        let doc = Html::parse_document(&page);
        let hidden = |name: &str| -> String {
            let sel = Selector::parse(&format!("input[name={name}]")).unwrap();
            doc.select(&sel)
                .next()
                .and_then(|e| e.value().attr("value"))
                .unwrap_or_default()
                .to_string()
        };
        let req_sid = hidden("reqSid");
        let req_session = hidden("reqSession");
        let req_fregkey = hidden("reqFregkey");
        let req_paper_type = hidden("reqPaperType");
        let req_with_class = hidden("reqWithClass");

        // Pick the first available reqMid for each required class type, in the
        // user's preferred slot order.
        let chosen = self.choose_slots(&doc, course);
        let required = course.required_types();
        if chosen.len() < required.len() {
            return Ok((format!("No available slots for {}", course.code), false));
        }

        Self::check_cancel(cancel)?;

        // Submit the bidding request. reqMid repeats once per chosen slot.
        let mut form: Vec<(&str, String)> = vec![
            ("reqUnit", course.code.clone()),
            ("reqSid", req_sid),
            ("reqSession", req_session),
            ("reqFregkey", req_fregkey),
            ("reqPaperType", req_paper_type),
            ("reqWithClass", req_with_class),
            ("act", "insert".to_string()),
        ];
        for mid in &chosen {
            form.push(("reqMid", mid.clone()));
        }

        let resp = self
            .client
            .post(self.urls.register_unit_pro())
            .form(&form)
            .send()
            .map_err(|e| ScrapeError::Network(e.to_string()))?;
        let final_url = resp.url().to_string();
        let body = resp.text().map_err(|e| ScrapeError::Network(e.to_string()))?;

        if body.contains("sessionExpired") {
            return Err(ScrapeError::SessionExpired);
        }

        let red = text_of(&body, "div.red").unwrap_or_default().to_lowercase();
        let success = final_url.contains("insert-success") || red.contains("success");
        if success {
            Ok((format!("Registered {}", course.code), true))
        } else if !red.is_empty() {
            Ok((red, false))
        } else {
            Ok(("Bidding request submitted, but status unclear".to_string(), false))
        }
    }

    /// For each required class type, the first reqMid whose (type, number)
    /// matches a preferred slot, in preference order.
    fn choose_slots(&self, doc: &Html, course: &Course) -> Vec<String> {
        let row_sel = Selector::parse("tr").unwrap();
        let td_sel = Selector::parse("td").unwrap();
        let mid_sel = Selector::parse("input[name=reqMid]").unwrap();

        let mut chosen = Vec::new();
        for (class_type, numbers) in &course.slots {
            if numbers.is_empty() {
                continue;
            }
            'slot: for &number in numbers {
                for row in doc.select(&row_sel) {
                    let cols: Vec<String> = row
                        .select(&td_sel)
                        .map(|c| c.text().collect::<String>().trim().to_string())
                        .collect();
                    if cols.len() < 3 {
                        continue;
                    }
                    if &cols[1] == class_type && cols[2] == number.to_string() {
                        if let Some(mid) = row
                            .select(&mid_sel)
                            .next()
                            .and_then(|e| e.value().attr("value"))
                        {
                            chosen.push(mid.to_string());
                            break 'slot; // first available slot for this type
                        }
                    }
                }
            }
        }
        chosen
    }
}

fn attr(html: &str, selector: &str, attr: &str) -> Option<String> {
    let doc = Html::parse_document(html);
    let sel = Selector::parse(selector).ok()?;
    doc.select(&sel)
        .next()
        .and_then(|e| e.value().attr(attr))
        .map(|s| s.to_string())
}

fn text_of(html: &str, selector: &str) -> Option<String> {
    let doc = Html::parse_document(html);
    let sel = Selector::parse(selector).ok()?;
    doc.select(&sel)
        .next()
        .map(|e| e.text().collect::<String>().trim().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;
    use std::net::TcpStream;
    use std::process::{Child, Command};
    use std::sync::atomic::AtomicBool;
    use std::time::{Duration, Instant};

    struct Mock {
        child: Child,
    }
    impl Drop for Mock {
        fn drop(&mut self) {
            let _ = self.child.kill();
        }
    }

    fn start_mock(port: u16, scenario: &str) -> Mock {
        let child = Command::new("../venv/Scripts/python.exe")
            .args([
                "-m", "src.mock_server", "--host", "127.0.0.1", "--port",
                &port.to_string(), "--scenario", scenario, "--delay", "12",
            ])
            .current_dir("..")
            .spawn()
            .expect("spawn mock server");
        let deadline = Instant::now() + Duration::from_secs(15);
        while Instant::now() < deadline {
            if TcpStream::connect(("127.0.0.1", port)).is_ok() {
                break;
            }
            std::thread::sleep(Duration::from_millis(150));
        }
        Mock { child }
    }

    fn mock_course() -> Course {
        let mut slots = BTreeMap::new();
        slots.insert("L".to_string(), vec![1]);
        slots.insert("T".to_string(), vec![2]);
        Course { code: "MOCK1001".into(), name: "Mock".into(), slots }
    }

    #[test]
    fn http_login_and_register_success() {
        let port = 8799;
        let _mock = start_mock(port, "success");
        std::env::set_var("UTAR_BASE_URL", format!("http://127.0.0.1:{port}/portal/courseRegStu"));
        std::env::set_var("UTAR_MOCK_CAPTCHA", "mock");

        let cancel = AtomicBool::new(false);
        let mut scraper = HttpScraper::new().expect("build client");
        scraper.login("2103370", "pw", &cancel).expect("login");
        assert!(scraper.is_logged_in());
        let (msg, ok) = scraper.register_course(&mock_course(), &cancel).expect("register");
        assert!(ok, "expected success, got: {msg}");
    }

    #[test]
    fn http_rejects_invalid_credentials() {
        let port = 8800;
        let _mock = start_mock(port, "success");
        std::env::set_var("UTAR_BASE_URL", format!("http://127.0.0.1:{port}/portal/courseRegStu"));
        std::env::set_var("UTAR_MOCK_CAPTCHA", "mock");

        let cancel = AtomicBool::new(false);
        let mut scraper = HttpScraper::new().expect("build client");
        let err = scraper.login("invalid", "pw", &cancel).unwrap_err();
        assert!(matches!(err, ScrapeError::BadCredentials), "got {err:?}");
    }
}
