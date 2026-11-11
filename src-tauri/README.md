# UTAR Course Bidding — Tauri + Rust backend

An alternative implementation of the desktop app on **Tauri 2 + Rust**, reusing
the existing Vue frontend in `../web`. This lives on the `tauri-rust` branch; the
`develop` branch keeps the Python (pywebview) version.

## Why

- Tauri renders with the system WebView2 — the same engine pywebview uses — so
  the UI is unchanged.
- The backend is a single native binary: no Python, no venv, no PyInstaller
  unpacking at launch.

## Architecture

| Concern | Python (develop) | Rust (here) |
|---|---|---|
| Window + bridge | pywebview `DesktopApi` | Tauri commands (`src/commands.rs`) |
| Frontend | Vue in `web/` | same Vue; `web/src/tauri-bridge.js` maps `window.pywebview.api.*` to `invoke` |
| HTTP scraper | requests + BeautifulSoup | reqwest + scraper (`src/scraper_http.rs`) |
| Browser scraper | Playwright | chromiumoxide (`src/scraper_browser.rs`) |
| Captcha OCR | onnxruntime + numpy + PIL | `ort` + `image` (`src/ocr.rs`), same `common_old.onnx` |
| Storage | sqlite3 | rusqlite (`src/storage.rs`), same `data/app.db` schema |

The frontend is shell-agnostic: `tauri-bridge.js` only activates under Tauri, so
the identical `web/` builds for both the Python and Rust shells.

## Build / run

Prerequisites: Rust (MSVC toolchain), Node, WebView2 (preinstalled on Windows 10+).

```bash
# install the Tauri CLI once
cargo install tauri-cli --version "^2"

# dev (hot-reload frontend + Rust)
cargo tauri dev

# release bundle (MSI / NSIS installer under target/release/bundle/)
cargo tauri build
```

Point the app at the local mock server instead of real UTAR:

```bash
# PowerShell
$env:UTAR_BASE_URL = "http://127.0.0.1:8765/portal/courseRegStu"
```

## Build milestones (how this was assembled)

1. Tauri shell + SQLite storage + commands (course CRUD, import, status).
2. `ort` captcha OCR + reqwest/scraper HTTP registration method.
3. chromiumoxide browser registration method.

## TLS note

UTAR serves an incomplete certificate chain. The Python version uses
`verify=False`; the Rust client currently mirrors that with
`danger_accept_invalid_certs(true)`. For production, bundle UTAR's missing
intermediate certificate and remove that flag instead.
