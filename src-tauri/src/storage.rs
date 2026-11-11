//! SQLite storage. Mirrors src/storage/database.py so the same data/app.db
//! works across the Python (pywebview) and Rust (Tauri) versions.

use crate::models::Course;
use anyhow::{Context, Result};
use rusqlite::Connection;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

pub struct Database {
    path: PathBuf,
}

impl Database {
    /// Opens (creating if needed) the database at `path` and ensures the schema.
    pub fn open(path: impl AsRef<Path>) -> Result<Database> {
        let path = path.as_ref().to_path_buf();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).ok();
        }
        let db = Database { path };
        db.initialize()?;
        Ok(db)
    }

    fn connect(&self) -> Result<Connection> {
        Connection::open(&self.path).with_context(|| format!("opening {}", self.path.display()))
    }

    fn initialize(&self) -> Result<()> {
        let conn = self.connect()?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS app_settings (
                 key TEXT PRIMARY KEY,
                 value TEXT NOT NULL
             );
             CREATE TABLE IF NOT EXISTS courses (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 code TEXT NOT NULL UNIQUE,
                 name TEXT NOT NULL,
                 slots_json TEXT NOT NULL,
                 sort_order INTEGER NOT NULL DEFAULT 0
             );",
        )?;
        Ok(())
    }

    pub fn list_courses(&self) -> Result<Vec<Course>> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare(
            "SELECT code, name, slots_json FROM courses ORDER BY sort_order ASC, id ASC",
        )?;
        let rows = stmt.query_map([], |row| {
            let code: String = row.get(0)?;
            let name: String = row.get(1)?;
            let slots_json: String = row.get(2)?;
            Ok((code, name, slots_json))
        })?;

        let mut courses = Vec::new();
        for row in rows {
            let (code, name, slots_json) = row?;
            let slots: BTreeMap<String, Vec<i64>> =
                serde_json::from_str(&slots_json).unwrap_or_default();
            courses.push(Course { code, name, slots });
        }
        Ok(courses)
    }

    pub fn replace_courses(&self, courses: &[Course]) -> Result<()> {
        let mut conn = self.connect()?;
        let tx = conn.transaction()?;
        tx.execute("DELETE FROM courses", [])?;
        for (index, course) in courses.iter().enumerate() {
            let slots_json = serde_json::to_string(&course.slots)?;
            tx.execute(
                "INSERT INTO courses(code, name, slots_json, sort_order) VALUES (?1, ?2, ?3, ?4)",
                rusqlite::params![course.code, course.name, slots_json, index as i64],
            )?;
        }
        tx.commit()?;
        Ok(())
    }

    /// One-time import of a legacy data/courses.json if the table is empty.
    pub fn migrate_from_json(&self, courses_file: impl AsRef<Path>) -> Result<()> {
        let file = courses_file.as_ref();
        if !file.exists() {
            return Ok(());
        }
        if !self.list_courses()?.is_empty() {
            return Ok(());
        }
        let text = std::fs::read_to_string(file)?;
        if let Ok(courses) = serde_json::from_str::<Vec<Course>>(&text) {
            self.replace_courses(&courses)?;
        }
        Ok(())
    }
}
