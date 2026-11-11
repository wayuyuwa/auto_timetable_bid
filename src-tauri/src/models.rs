//! Shared data types mirrored between Rust, SQLite and the Vue frontend.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// A course the user wants to register for.
///
/// `slots` maps a class type ("L", "T", "P") to the preferred slot numbers in
/// priority order. A `BTreeMap` keeps the JSON key order stable for the UI.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Course {
    pub code: String,
    pub name: String,
    #[serde(default)]
    pub slots: BTreeMap<String, Vec<i64>>,
}

impl Course {
    /// Class types that actually have preferred slots (empty lists ignored).
    pub fn required_types(&self) -> Vec<String> {
        self.slots
            .iter()
            .filter(|(_, nums)| !nums.is_empty())
            .map(|(t, _)| t.clone())
            .collect()
    }
}

/// Per-course outcome shown in the results table.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CourseResult {
    pub status: String, // "success" | "failed"
    pub label: String,  // "Success" | "Needs attention"
    pub message: String,
}

/// The whole run status the frontend polls with `get_status`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunStatus {
    pub running: bool,
    pub phase: String, // idle | login | bidding | complete | error | cancelled
    pub message: String,
    pub completed: u32,
    pub total: u32,
    pub results: BTreeMap<String, CourseResult>,
}

impl RunStatus {
    pub fn empty() -> Self {
        RunStatus {
            running: false,
            phase: "idle".into(),
            message: "Ready".into(),
            completed: 0,
            total: 0,
            results: BTreeMap::new(),
        }
    }
}

/// Which backend performs the registration.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Method {
    Http,    // reqwest + scraper (the BeautifulSoup equivalent)
    Browser, // chromiumoxide (the Playwright equivalent)
}

impl Method {
    /// Accepts the labels the existing Vue UI sends, plus Rust-native names.
    pub fn parse(value: &str) -> Method {
        match value.trim().to_ascii_lowercase().as_str() {
            "browser" | "playwright" | "chromiumoxide" => Method::Browser,
            _ => Method::Http, // "BeautifulSoup", "http", or anything else
        }
    }
}
