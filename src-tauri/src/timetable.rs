//! Parse an exported UTAR timetable .txt into courses. Mirrors
//! src/utils/timetable_reader.py (5 lines per course: code, name, then the
//! L/T/P slot lines like "L(1 or 2) - Mon 09:00").

use crate::models::Course;
use std::collections::BTreeMap;

/// Parse the JSON course list the UI exports, or a timetable .txt.
pub fn parse(filename: &str, content: &str) -> anyhow::Result<Vec<Course>> {
    if filename.to_ascii_lowercase().ends_with(".json") {
        Ok(serde_json::from_str::<Vec<Course>>(content)?)
    } else {
        Ok(parse_timetable(content))
    }
}

fn parse_timetable(content: &str) -> Vec<Course> {
    // Keep non-blank lines, matching the Python filter.
    let mut lines: Vec<&str> = content
        .lines()
        .filter(|l| !l.trim().is_empty())
        .collect();

    // TTAP export: a "NOTE" banner occupies the first three kept lines.
    if lines.first().map(|l| l.starts_with("NOTE")).unwrap_or(false) && lines.len() > 3 {
        lines.drain(0..3);
    }

    let mut courses = Vec::new();
    let mut i = 0;
    while i + 1 < lines.len() {
        let chunk_end = (i + 5).min(lines.len());
        let chunk = &lines[i..chunk_end];
        if let Some(course) = parse_course(chunk) {
            courses.push(course);
        }
        i += 5;
    }
    courses
}

fn parse_course(chunk: &[&str]) -> Option<Course> {
    if chunk.len() < 2 {
        return None;
    }
    let code = chunk[0].trim().to_string();
    let name = chunk[1].trim().to_string();
    if code.is_empty() {
        return None;
    }

    let mut slots: BTreeMap<String, Vec<i64>> = BTreeMap::new();
    for line in chunk.iter().skip(2) {
        if let Some((slot_type, numbers)) = parse_slot_line(line) {
            slots.insert(slot_type, numbers);
        }
    }
    Some(Course { code, name, slots })
}

/// Parse a line like "L(1 or 2) - Mon 09:00-11:00" -> ("L", [1, 2]).
fn parse_slot_line(line: &str) -> Option<(String, Vec<i64>)> {
    let line = line.trim();
    let slot_type = match line.chars().next()? {
        c @ ('L' | 'T' | 'P') => c.to_string(),
        _ => return None,
    };
    let open = line.find('(')?;
    let close = line.find(')')?;
    if close <= open + 1 {
        return None;
    }
    // The Python regex requires ") -" after the slot list.
    if !line[close + 1..].trim_start().starts_with('-') {
        return None;
    }
    let inside = &line[open + 1..close];
    let numbers: Vec<i64> = inside
        .split(" or ")
        .filter_map(|n| n.trim().parse::<i64>().ok())
        .collect();
    if numbers.is_empty() {
        return None;
    }
    Some((slot_type, numbers))
}
