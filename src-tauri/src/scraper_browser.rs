//! Browser scraper using chromiumoxide (Chrome DevTools Protocol). The Rust
//! equivalent of src/scrapers/playwright_scraper.py. Drives a headless (or
//! visible) Chromium/Edge through the same login and registration flow.

use crate::config::{self, Urls};
use crate::models::Course;
use chromiumoxide::browser::{Browser, BrowserConfig};
use chromiumoxide::cdp::browser_protocol::page::CaptureScreenshotFormat;
use chromiumoxide::error::CdpError;
use chromiumoxide::page::Page;
use futures::StreamExt;
use std::path::PathBuf;
use std::time::Duration;
use tokio::task::JoinHandle;

#[derive(Debug)]
pub enum BrowserError {
    Launch(String),
    Cdp(String),
    LoginFailed,
}

impl std::fmt::Display for BrowserError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            BrowserError::Launch(m) => write!(f, "Could not launch a browser: {m}"),
            BrowserError::Cdp(m) => write!(f, "Browser error: {m}"),
            BrowserError::LoginFailed => write!(f, "Login failed. Please check your credentials."),
        }
    }
}

impl From<CdpError> for BrowserError {
    fn from(e: CdpError) -> Self {
        BrowserError::Cdp(e.to_string())
    }
}

type Result<T> = std::result::Result<T, BrowserError>;

pub struct BrowserScraper {
    browser: Browser,
    _handler: JoinHandle<()>,
    page: Page,
    urls: Urls,
}

impl BrowserScraper {
    pub async fn new(headless: bool) -> Result<BrowserScraper> {
        let mut builder = BrowserConfig::builder();
        if let Some(path) = find_browser() {
            builder = builder.chrome_executable(path);
        }
        if !headless {
            builder = builder.with_head();
        }
        let config = builder.build().map_err(BrowserError::Launch)?;

        let (browser, mut handler) = Browser::launch(config)
            .await
            .map_err(|e| BrowserError::Launch(e.to_string()))?;
        // Drive the CDP event loop in the background. Keep polling even if an
        // individual event errors; only stop when the stream ends (browser gone).
        let _handler = tokio::spawn(async move { while handler.next().await.is_some() {} });

        let page = browser.new_page("about:blank").await?;
        Ok(BrowserScraper {
            browser,
            _handler,
            page,
            urls: Urls::load(),
        })
    }

    pub async fn login(&self, student_id: &str, password: &str) -> Result<()> {
        self.page.goto(self.urls.login()).await?;
        self.page.wait_for_navigation().await?;

        self.page
            .find_element("input[name=reqFregkey]")
            .await?
            .click()
            .await?
            .type_str(student_id)
            .await?;
        self.page
            .find_element("input[name=reqPassword]")
            .await?
            .click()
            .await?
            .type_str(password)
            .await?;

        // Solve the captcha from a screenshot of its image (or a test override).
        let code = match config::mock_captcha() {
            Some(value) => value,
            None => {
                let img = self.page.find_element("img[src*='Kaptcha']").await?;
                let png = img.screenshot(CaptureScreenshotFormat::Png).await?;
                crate::ocr::solve(&png).map_err(|e| BrowserError::Cdp(e.to_string()))?
            }
        };
        self.page
            .find_element("input[name=kaptchafield]")
            .await?
            .click()
            .await?
            .type_str(&code)
            .await?;

        // Submit and wait for the logged-in home page (shows "Log Out").
        self.page.find_element("input[name=_submit]").await?.click().await?;
        if !self.wait_for_text("Log Out", 8).await {
            return Err(BrowserError::LoginFailed);
        }
        Ok(())
    }

    /// Register one course. Returns (message, success).
    pub async fn register_course(&self, course: &Course) -> Result<(String, bool)> {
        self.page.goto(self.urls.home()).await?;
        self.page.wait_for_navigation().await?;

        // Enter the course code in the unit lookup and submit it.
        self.page
            .find_element("input#reqUnit")
            .await?
            .click()
            .await?
            .type_str(&course.code)
            .await?;
        self.page.find_element("form[name=frmUnit]").await?;
        self.submit_unit_lookup(course).await?;

        // Wait for the slot summary form.
        if !self.wait_for_selector("form[name=frmSummary]", 8).await {
            return Ok((format!("No slot summary for {}", course.code), false));
        }

        let chosen = self.choose_slots(course).await?;
        let required = course.required_types();
        if chosen < required.len() {
            return Ok((format!("No available slots for {}", course.code), false));
        }

        // Accept any alert the submit raises (invalid-combination message).
        let dialog = self.capture_next_dialog();
        self.page.find_element("input[name=Submit]").await?.click().await?;
        tokio::time::sleep(Duration::from_millis(500)).await;

        if let Some(message) = dialog.await.ok().flatten() {
            let lower = message.to_lowercase();
            if lower.contains("valid class combination") {
                return Ok(("Invalid timetable".to_string(), false));
            }
        }

        let body = self.page.content().await?;
        let lower = body.to_lowercase();
        if lower.contains("sessionexpired") {
            return Ok(("Your session expired. Please log in again.".to_string(), false));
        }
        let success = self.page.url().await?.unwrap_or_default().contains("insert-success")
            || lower.contains(">success<")
            || lower.contains("class='red'>success")
            || lower.contains("class=\"red\">success");
        Ok(if success {
            (format!("Registered {}", course.code), true)
        } else {
            ("Bidding request submitted, but status unclear".to_string(), false)
        })
    }

    async fn submit_unit_lookup(&self, _course: &Course) -> Result<()> {
        // Press Enter in the unit field (real portal) and also submit the form.
        self.page
            .evaluate("document.forms['frmUnit'] && document.forms['frmUnit'].submit()")
            .await
            .ok();
        Ok(())
    }

    /// Check the first matching reqMid checkbox per required type; returns count.
    async fn choose_slots(&self, course: &Course) -> Result<usize> {
        let mut chosen = 0usize;
        for (class_type, numbers) in &course.slots {
            if numbers.is_empty() {
                continue;
            }
            for &number in numbers {
                let js = format!(
                    r#"(() => {{
                        const rows = document.querySelectorAll("form[name=frmSummary] tr");
                        for (const r of rows) {{
                            const td = r.querySelectorAll('td');
                            if (td.length < 3) continue;
                            if (td[1].innerText.trim() === "{t}" && td[2].innerText.trim() === "{n}") {{
                                const cb = r.querySelector("input[name=reqMid]");
                                if (cb) {{ cb.checked = true; return true; }}
                            }}
                        }}
                        return false;
                    }})()"#,
                    t = class_type,
                    n = number
                );
                let hit = self
                    .page
                    .evaluate(js)
                    .await?
                    .into_value::<bool>()
                    .unwrap_or(false);
                if hit {
                    chosen += 1;
                    break;
                }
            }
        }
        Ok(chosen)
    }

    /// Listen for the next JS dialog and return its message, accepting it.
    fn capture_next_dialog(&self) -> JoinHandle<Option<String>> {
        let page = self.page.clone();
        tokio::spawn(async move {
            use chromiumoxide::cdp::browser_protocol::page::{
                EventJavascriptDialogOpening, HandleJavaScriptDialogParams,
            };
            let mut events = match page.event_listener::<EventJavascriptDialogOpening>().await {
                Ok(e) => e,
                Err(_) => return None,
            };
            match tokio::time::timeout(Duration::from_secs(3), events.next()).await {
                Ok(Some(ev)) => {
                    let message = ev.message.clone();
                    page.execute(HandleJavaScriptDialogParams::new(true)).await.ok();
                    Some(message)
                }
                _ => None,
            }
        })
    }

    async fn wait_for_selector(&self, selector: &str, secs: u64) -> bool {
        let deadline = std::time::Instant::now() + Duration::from_secs(secs);
        while std::time::Instant::now() < deadline {
            if self.page.find_element(selector).await.is_ok() {
                return true;
            }
            tokio::time::sleep(Duration::from_millis(200)).await;
        }
        false
    }

    async fn wait_for_text(&self, needle: &str, secs: u64) -> bool {
        let deadline = std::time::Instant::now() + Duration::from_secs(secs);
        while std::time::Instant::now() < deadline {
            if let Ok(body) = self.page.content().await {
                if body.contains(needle) {
                    return true;
                }
            }
            tokio::time::sleep(Duration::from_millis(200)).await;
        }
        false
    }

    pub async fn close(mut self) {
        self.browser.close().await.ok();
        self.browser.wait().await.ok();
    }
}

/// Locate a Chromium-based browser: env override, Playwright's Chromium, or Edge.
fn find_browser() -> Option<PathBuf> {
    if let Ok(p) = std::env::var("UTAR_BROWSER_PATH") {
        let p = PathBuf::from(p);
        if p.exists() {
            return Some(p);
        }
    }
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Some(local) = std::env::var_os("LOCALAPPDATA") {
        let base = PathBuf::from(local).join("ms-playwright");
        if let Ok(entries) = std::fs::read_dir(&base) {
            for e in entries.flatten() {
                let name = e.file_name().to_string_lossy().to_string();
                if name.starts_with("chromium-") {
                    // Playwright layout changed from chrome-win to chrome-win64.
                    candidates.push(e.path().join("chrome-win64").join("chrome.exe"));
                    candidates.push(e.path().join("chrome-win").join("chrome.exe"));
                }
            }
        }
    }
    candidates.push(PathBuf::from(
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ));
    candidates.push(PathBuf::from(
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ));
    candidates.into_iter().find(|p| p.exists())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::Course;
    use std::collections::BTreeMap;
    use std::net::TcpStream;
    use std::process::{Child, Command};
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
                &port.to_string(), "--scenario", scenario,
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

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn browser_login_and_register_success() {
        if find_browser().is_none() {
            eprintln!("no Chromium/Edge found; skipping browser test");
            return;
        }
        let port = 8810;
        let _mock = start_mock(port, "success");
        std::env::set_var("UTAR_BASE_URL", format!("http://127.0.0.1:{port}/portal/courseRegStu"));
        std::env::set_var("UTAR_MOCK_CAPTCHA", "mock");

        let scraper = BrowserScraper::new(true).await.expect("launch browser");
        scraper.login("2103370", "pw").await.expect("login");
        let (msg, ok) = scraper.register_course(&mock_course()).await.expect("register");
        scraper.close().await;
        assert!(ok, "expected success, got: {msg}");
    }
}
