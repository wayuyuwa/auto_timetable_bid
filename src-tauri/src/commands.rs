//! Tauri commands exposed to the Vue frontend. These mirror the method names
//! the existing pywebview `DesktopApi` exposed, so the frontend bridge can call
//! them unchanged.

use crate::models::{Course, Method, RunStatus};
use crate::state::AppState;
use crate::timetable;
use std::sync::atomic::Ordering;
use tauri::State;

#[tauri::command]
pub fn get_courses(state: State<AppState>) -> Vec<Course> {
    state.courses.lock().clone()
}

#[tauri::command]
pub fn save_courses(state: State<AppState>, courses: Vec<Course>) -> Result<Vec<Course>, String> {
    state.db().replace_courses(&courses).map_err(|e| e.to_string())?;
    *state.courses.lock() = courses;
    Ok(state.courses.lock().clone())
}

#[tauri::command]
pub fn import_courses(
    state: State<AppState>,
    filename: String,
    content: String,
) -> Result<Vec<Course>, String> {
    let courses = timetable::parse(&filename, &content).map_err(|e| e.to_string())?;
    state.db().replace_courses(&courses).map_err(|e| e.to_string())?;
    *state.courses.lock() = courses;
    Ok(state.courses.lock().clone())
}

#[tauri::command]
pub fn start(
    state: State<AppState>,
    student_id: String,
    password: String,
    method: String,
    headless: bool,
) -> Result<RunStatus, String> {
    if state.is_running() {
        return Err("A registration run is already in progress".into());
    }
    let courses = state.courses.lock().clone();
    let shared = state.shared.clone();

    shared.cancel.store(false, Ordering::SeqCst);
    shared.update(|s| {
        *s = RunStatus::empty();
        s.running = true;
        s.phase = "login".into();
        s.message = "Preparing login...".into();
        s.total = courses.len() as u32;
    });

    let method = Method::parse(&method);
    let worker = std::thread::spawn(move || {
        crate::bidding::run(method, student_id, password, headless, courses, shared);
    });
    *state.worker.lock() = Some(worker);

    Ok(state.shared.snapshot())
}

#[tauri::command]
pub fn cancel(state: State<AppState>) -> RunStatus {
    state.shared.cancel.store(true, Ordering::SeqCst);
    state.shared.snapshot()
}

#[tauri::command]
pub fn get_status(state: State<AppState>) -> RunStatus {
    state.shared.snapshot()
}
