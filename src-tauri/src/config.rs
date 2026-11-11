//! URL configuration. Mirrors src/utils/config.py.
//!
//! Set `UTAR_BASE_URL` to point every request at the local mock server
//! (src/mock_server.py) instead of the real UTAR portal.

const DEFAULT_BASE_URL: &str = "https://unitreg.utar.edu.my/portal/courseRegStu";

pub struct Urls {
    pub base: String,
}

impl Urls {
    pub fn load() -> Urls {
        let base = std::env::var("UTAR_BASE_URL")
            .ok()
            .filter(|v| !v.trim().is_empty())
            .map(|v| v.trim_end_matches('/').to_string())
            .unwrap_or_else(|| DEFAULT_BASE_URL.to_string());
        Urls { base }
    }

    pub fn login(&self) -> String {
        format!("{}/login.jsp", self.base)
    }
    pub fn login_process(&self) -> String {
        format!("{}/loginProSurvey.jsp", self.base)
    }
    pub fn home(&self) -> String {
        format!("{}/registration/studentRegistrationSurvey.jsp", self.base)
    }
    pub fn register_unit(&self) -> String {
        format!("{}/registration/registerUnitSurvey.jsp", self.base)
    }
    pub fn register_unit_pro(&self) -> String {
        format!("{}/registration/registerUnitProSurvey.jsp", self.base)
    }
    /// The captcha image lives one directory above the portal base.
    pub fn captcha(&self) -> String {
        let parent = self.base.rsplit_once('/').map(|(p, _)| p).unwrap_or(&self.base);
        format!("{}/Kaptcha.jpg", parent)
    }
}

/// Captcha override for tests: when `UTAR_MOCK_CAPTCHA` is set, the OCR step is
/// skipped and this value is submitted instead (mirrors the Python scrapers).
pub fn mock_captcha() -> Option<String> {
    std::env::var("UTAR_MOCK_CAPTCHA").ok().filter(|v| !v.is_empty())
}
