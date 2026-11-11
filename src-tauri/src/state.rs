//! Shared application state held by Tauri and mutated by the worker thread.

use crate::models::{Course, RunStatus};
use crate::storage::Database;
use parking_lot::Mutex;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::JoinHandle;

/// State shared with the background bidding thread.
pub struct Shared {
    pub status: Mutex<RunStatus>,
    pub cancel: AtomicBool,
}

impl Shared {
    pub fn new() -> Arc<Shared> {
        Arc::new(Shared {
            status: Mutex::new(RunStatus::empty()),
            cancel: AtomicBool::new(false),
        })
    }

    pub fn is_cancelled(&self) -> bool {
        self.cancel.load(Ordering::SeqCst)
    }

    /// Mutate the status in place under the lock.
    pub fn update<F: FnOnce(&mut RunStatus)>(&self, f: F) {
        let mut status = self.status.lock();
        f(&mut status);
    }

    pub fn snapshot(&self) -> RunStatus {
        self.status.lock().clone()
    }
}

/// Tauri-managed application state.
pub struct AppState {
    pub db_path: PathBuf,
    pub courses_file: PathBuf,
    pub courses: Mutex<Vec<Course>>,
    pub shared: Arc<Shared>,
    pub worker: Mutex<Option<JoinHandle<()>>>,
}

impl AppState {
    pub fn new() -> AppState {
        let base = resolve_data_dir();
        let db_path = std::env::var("UTAR_DB_PATH")
            .map(PathBuf::from)
            .unwrap_or_else(|_| base.join("app.db"));
        let courses_file = base.join("courses.json");

        let db = Database::open(&db_path).expect("open database");
        db.migrate_from_json(&courses_file).ok();
        let courses = db.list_courses().unwrap_or_default();

        AppState {
            db_path,
            courses_file,
            courses: Mutex::new(courses),
            shared: Shared::new(),
            worker: Mutex::new(None),
        }
    }

    pub fn db(&self) -> Database {
        Database::open(&self.db_path).expect("open database")
    }

    /// True if a bidding run is currently in progress.
    pub fn is_running(&self) -> bool {
        self.worker
            .lock()
            .as_ref()
            .map(|h| !h.is_finished())
            .unwrap_or(false)
    }
}

/// data/ directory next to the executable in release, or the dev working dir.
fn resolve_data_dir() -> PathBuf {
    let dir = std::env::current_dir()
        .unwrap_or_else(|_| PathBuf::from("."))
        .join("data");
    std::fs::create_dir_all(&dir).ok();
    dir
}
