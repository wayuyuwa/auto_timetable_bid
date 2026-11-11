//! Orchestrates a registration run on the worker thread: log in, then bid each
//! course, updating shared status and honouring cancellation. Mirrors
//! src/services/bidding_service.py, including the "stop safely" behaviour (a
//! cancelled run ends as `cancelled`, never overwritten by a completion).

use crate::models::{Course, CourseResult, Method};
use crate::scraper_http::{HttpScraper, ScrapeError};
use crate::state::Shared;
use std::sync::Arc;

pub fn run(
    method: Method,
    student_id: String,
    password: String,
    headless: bool,
    courses: Vec<Course>,
    shared: Arc<Shared>,
) {
    match method {
        Method::Http => run_http(&student_id, &password, &courses, &shared),
        Method::Browser => run_browser(&student_id, &password, headless, &courses, &shared),
    }
}

fn run_http(student_id: &str, password: &str, courses: &[Course], shared: &Arc<Shared>) {
    shared.update(|s| {
        s.phase = "login".into();
        s.message = "Connecting to UTAR course registration system...".into();
    });

    let mut scraper = match HttpScraper::new() {
        Ok(s) => s,
        Err(e) => return error(shared, &format!("Login error: {e}")),
    };

    if shared.is_cancelled() {
        return cancelled(shared);
    }

    match scraper.login(student_id, password, &shared.cancel) {
        Ok(()) => {}
        Err(ScrapeError::Cancelled) => return cancelled(shared),
        Err(e @ ScrapeError::BadCredentials) => return error(shared, &e.to_string()),
        Err(e @ ScrapeError::SessionExpired) => return error(shared, &e.to_string()),
        Err(e) => return error(shared, &format!("Login error: {e}")),
    }

    if shared.is_cancelled() {
        return cancelled(shared);
    }

    let total = courses.len() as u32;
    shared.update(|s| {
        s.phase = "bidding".into();
        s.total = total;
        s.message = "Login successful. Starting course registration...".into();
    });

    bid_loop(courses, shared, |course| {
        scraper.register_course(course, &shared.cancel)
    });
}

/// Shared bidding loop used by both methods; `register` performs one course.
fn bid_loop<F>(courses: &[Course], shared: &Arc<Shared>, mut register: F)
where
    F: FnMut(&Course) -> Result<(String, bool), ScrapeError>,
{
    let total = courses.len() as u32;
    let mut all_ok = true;

    for (i, course) in courses.iter().enumerate() {
        if shared.is_cancelled() {
            return cancelled(shared);
        }
        shared.update(|s| {
            s.phase = "bidding".into();
            s.completed = i as u32;
            s.total = total;
            s.message = format!("Bidding {} - {}", course.code, course.name);
        });

        let outcome = register(course);

        // A stop requested mid-request ends the run as cancelled, never failed.
        if shared.is_cancelled() {
            return cancelled(shared);
        }

        let (status, label, message, ok) = match outcome {
            Ok((_, true)) => (
                "success",
                "Success",
                "Successfully registered".to_string(),
                true,
            ),
            Ok((msg, false)) => ("failed", "Needs attention", msg, false),
            Err(ScrapeError::Cancelled) => return cancelled(shared),
            Err(ScrapeError::SessionExpired) => {
                return error(shared, &ScrapeError::SessionExpired.to_string())
            }
            Err(e) => ("failed", "Needs attention", e.to_string(), false),
        };

        all_ok = all_ok && ok;
        shared.update(|s| {
            s.results.insert(
                course.code.clone(),
                CourseResult {
                    status: status.into(),
                    label: label.into(),
                    message: message.clone(),
                },
            );
            s.completed = s.results.len() as u32;
            s.message = message.clone();
        });
    }

    shared.update(|s| {
        s.running = false;
        s.phase = if all_ok { "complete" } else { "error" }.into();
        s.completed = s.results.len() as u32;
        s.message = if all_ok {
            "All courses registered successfully.".into()
        } else {
            "Registration finished with items needing attention.".into()
        };
    });
}

fn run_browser(
    _student_id: &str,
    _password: &str,
    _headless: bool,
    _courses: &[Course],
    shared: &Arc<Shared>,
) {
    // Implemented in milestone 3 (chromiumoxide).
    error(
        shared,
        "The browser method (chromiumoxide) arrives in milestone 3.",
    );
}

fn error(shared: &Arc<Shared>, message: &str) {
    shared.update(|s| {
        s.running = false;
        s.phase = "error".into();
        s.message = message.to_string();
    });
}

fn cancelled(shared: &Arc<Shared>) {
    shared.update(|s| {
        s.running = false;
        s.phase = "cancelled".into();
        s.message = "Registration cancelled safely.".into();
    });
}
