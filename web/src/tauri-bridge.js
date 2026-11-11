// Bridges the Vue app to the Tauri (Rust) backend without changing App.vue.
//
// App.vue talks to `window.pywebview.api.<method>(...positional args)`. Under
// Tauri we expose an object with the same method names that forwards to the
// Rust commands via `invoke`, mapping positional args to the named arguments
// each #[tauri::command] expects. Under pywebview this file does nothing, so the
// same frontend runs in both shells.

const argMap = {
  get_courses: () => ({}),
  save_courses: (courses) => ({ courses }),
  import_courses: (filename, content) => ({ filename, content }),
  start: (studentId, password, method, headless) => ({ studentId, password, method, headless }),
  cancel: () => ({}),
  get_status: () => ({}),
};

function installTauriBridge() {
  const tauri = window.__TAURI__;
  if (!tauri || !tauri.core || typeof tauri.core.invoke !== "function") {
    return false; // not running inside Tauri
  }
  const { invoke } = tauri.core;
  const api = {};
  for (const name of Object.keys(argMap)) {
    api[name] = (...args) => invoke(name, argMap[name](...args));
  }
  window.pywebview = { api };
  // App.vue listens for this once to attach the bridge after load.
  window.dispatchEvent(new Event("pywebviewready"));
  return true;
}

installTauriBridge();

export {};
