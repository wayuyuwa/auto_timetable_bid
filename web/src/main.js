import "./tauri-bridge.js"; // installs window.pywebview.api when running under Tauri
import { createApp } from "vue";
import App from "./App.vue";
import "./style.css";

createApp(App).mount("#app");
