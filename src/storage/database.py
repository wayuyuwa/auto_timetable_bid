"""
SQLite storage for settings and courses.
"""

import json
import os
import sqlite3
from typing import Any, Dict, List

from ..utils.config import BASE_DIR, SQLITE_DB_PATH
from ..utils.timetable_reader import Course


class Database:
    """Lightweight sqlite wrapper with schema bootstrap."""

    def __init__(self, db_path: str = SQLITE_DB_PATH):
        self.db_path = db_path or os.path.join(BASE_DIR, "data", "app.db")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS courses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    slots_json TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()


class SettingsRepository:
    """Settings persistence in sqlite with optional JSON migration."""

    DEFAULT_SETTINGS: Dict[str, Any] = {
        "student_id": "",
        "password": "",
        "method": "Request",
        "headless_mode": False,
        "max_retries": 3,
    }

    def __init__(self, database: Database):
        self.database = database

    def load_settings(self) -> Dict[str, Any]:
        result = dict(self.DEFAULT_SETTINGS)
        with self.database._connect() as conn:
            rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
            for row in rows:
                key = row["key"]
                value = row["value"]
                if key in ("headless_mode",):
                    result[key] = value.lower() == "true"
                elif key in ("max_retries",):
                    try:
                        result[key] = int(value)
                    except ValueError:
                        result[key] = self.DEFAULT_SETTINGS[key]
                else:
                    result[key] = value
        return result

    def save_settings(self, settings: Dict[str, Any]) -> None:
        with self.database._connect() as conn:
            for key, value in settings.items():
                conn.execute(
                    "INSERT INTO app_settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, str(value)),
                )
            conn.commit()

    def migrate_from_json(self, settings_file: str) -> None:
        if not settings_file or not os.path.exists(settings_file):
            return

        with self.database._connect() as conn:
            existing = conn.execute("SELECT COUNT(*) AS count FROM app_settings").fetchone()["count"]
            if existing > 0:
                return

        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                legacy = json.load(f)
            merged = dict(self.DEFAULT_SETTINGS)
            merged.update(legacy)
            self.save_settings(merged)
        except Exception:
            self.save_settings(dict(self.DEFAULT_SETTINGS))


class CourseRepository:
    """Course persistence in sqlite with optional JSON migration."""

    def __init__(self, database: Database):
        self.database = database

    def list_courses(self) -> List[Course]:
        with self.database._connect() as conn:
            rows = conn.execute(
                "SELECT code, name, slots_json FROM courses ORDER BY sort_order ASC, id ASC"
            ).fetchall()
            courses: List[Course] = []
            for row in rows:
                slots = json.loads(row["slots_json"]) if row["slots_json"] else {}
                courses.append(Course(code=row["code"], name=row["name"], slots=slots))
            return courses

    def replace_courses(self, courses: List[Course]) -> None:
        with self.database._connect() as conn:
            conn.execute("DELETE FROM courses")
            for index, course in enumerate(courses):
                conn.execute(
                    "INSERT INTO courses(code, name, slots_json, sort_order) VALUES (?, ?, ?, ?)",
                    (course.code, course.name, json.dumps(course.slots), index),
                )
            conn.commit()

    def migrate_from_json(self, courses_file: str) -> None:
        if not courses_file or not os.path.exists(courses_file):
            return

        with self.database._connect() as conn:
            existing = conn.execute("SELECT COUNT(*) AS count FROM courses").fetchone()["count"]
            if existing > 0:
                return

        try:
            with open(courses_file, "r", encoding="utf-8") as f:
                raw_courses = json.load(f)
            courses = [Course(**item) for item in raw_courses]
            self.replace_courses(courses)
        except Exception:
            return
