//! UTAR Course Bidding — Tauri + Rust backend.

mod bidding;
mod commands;
mod config;
mod models;
mod ocr;
mod scraper_browser;
mod scraper_http;
mod state;
mod storage;
mod timetable;

/// Build and run the Tauri application.
pub fn run() {
    tauri::Builder::default()
        .manage(state::AppState::new())
        .invoke_handler(tauri::generate_handler![
            commands::get_courses,
            commands::save_courses,
            commands::import_courses,
            commands::start,
            commands::cancel,
            commands::get_status,
        ])
        .run(tauri::generate_context!())
        .expect("error while running the UTAR Course Bidding app");
}
