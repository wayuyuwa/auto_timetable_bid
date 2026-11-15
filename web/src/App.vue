<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";

let api = window.pywebview?.api;
const bridgeReady = ref(Boolean(api));
const TABS = [
  { id: "courses", label: "Courses" },
  { id: "login", label: "Login & settings" },
  { id: "preflight", label: "Pre-flight" },
  { id: "run", label: "Registration" },
  { id: "logs", label: "Logs" },
];
const activeTab = ref("courses");
const plans = ref([{ name: "Plan A", courses: [] }]);
const activePlan = ref(0);
const selectedCode = ref("");
const fileInput = ref(null);
const notice = ref({ type: "info", text: "Loading your course list..." });
const courseDialogOpen = ref(false);
const deleteDialogOpen = ref(false);
const planDialogOpen = ref(false);
const removePlanDialogOpen = ref(false);
const planNameDraft = ref("");
const courseForm = reactive({ code: "", name: "", lecture: "", tutorial: "", practical: "" });
const courseBeingEdited = ref(null);
const courseBeingRemoved = ref(null);
const proposalChoice = ref([]);
const status = reactive({
  running: false,
  phase: "idle",
  message: "Ready",
  completed: 0,
  total: 0,
  results: {},
  registered: [],
  credit: {},
  plan: "",
  attempt: 0,
  proposal: null,
  preflight: null,
  start_at: null,
  next_retry_at: null,
  kind: "",
  started_at: null,
  ended_at: null,
  stopping: false,
  login: { attempt: 0, max: 0, reasons: [] },
  error_source: null,
  error_kind: null,
  steps: [],
  log: [],
});
const credentials = reactive({ studentId: "", password: "", remember: true, secure: true });
const showPassword = ref(false);
const options = reactive({
  method: "BeautifulSoup",
  browserVisible: true,
  fallbackMode: "auto",
  autoRetry: false,
  retrySeconds: 30,
  maxAttempts: 10,
  startMode: "now",
  startTime: "",
  delayMinutes: 5,
});
const browser = reactive({ checked: false, installed: true, path: "", install: { running: false, ok: null, message: "" } });
const importDialog = reactive({ open: false, filename: "", content: "", courses: [], mode: "replace", newName: "" });
const dragActive = ref(false);
const loginError = ref(null);
const rejectedCredentials = ref(null);
const now = ref(Date.now());
let pollTimer;
let clockTimer;
let saveCredentialsTimer;
let credentialsLoaded = false;
let lastFinishedRun = null;

// --------------------------------------------------------------- toasts
// One toast at a time, queued; identical messages are not repeated.
const toast = ref(null);
const toastQueue = [];
let toastTimer;
const TOAST_MS = { info: 3200, success: 3200, error: 6500 };

function showToast(text, type = "info") {
  if (!text) return;
  if (toast.value?.text === text || toastQueue.some((item) => item.text === text)) return;
  toastQueue.push({ text, type, id: Date.now() + Math.random() });
  if (toastQueue.length > 4) toastQueue.splice(0, toastQueue.length - 4);
  if (!toast.value) nextToast();
}

function nextToast() {
  window.clearTimeout(toastTimer);
  toast.value = toastQueue.shift() || null;
  if (toast.value) toastTimer = window.setTimeout(nextToast, TOAST_MS[toast.value.type] || TOAST_MS.info);
}

function setNotice(text, type = "info", { toast: withToast = true } = {}) {
  notice.value = { text, type };
  if (withToast) showToast(text, type);
}

// --------------------------------------------------------------- derived
const courses = computed(() => plans.value[activePlan.value]?.courses || []);
const totalCourses = computed(() => plans.value.reduce((sum, plan) => sum + plan.courses.length, 0));
const resultList = computed(() => Object.entries(status.results).map(([code, result]) => ({ code, ...result })));
const successCount = computed(() => resultList.value.filter((result) => result.status === "success" || result.status === "partial").length);
const failedCount = computed(() => resultList.value.filter((result) => result.status === "failed").length);
const hasMissing = computed(() => !status.running && status.kind === "run" && failedCount.value > 0);
const startLabel = computed(() => {
  if (status.running) return status.kind === "preflight" ? "Pre-flight in progress" : "Registration in progress";
  return hasMissing.value ? "Retry missing courses" : "Start registration";
});
const proposalOpen = computed(() => status.phase === "awaiting_choice" && Boolean(status.proposal));
const creditText = computed(() => {
  if (!status.credit?.total && !status.credit?.max) return "";
  return `${status.credit.total || "?"} of ${status.credit.max || "?"} credit hours`;
});
const PHASES = {
  idle: "Ready", login: "Logging in", scheduled: "Waiting for scheduled start", preflight: "Pre-flight",
  verifying: "Checking registered courses", bidding: "Bidding", awaiting_choice: "Waiting for your choice",
  waiting_retry: "Waiting to retry", complete: "Done", preflight_done: "Pre-flight done",
  error: "Needs attention", cancelled: "Cancelled",
};
const phaseLabel = computed(() => (status.running && status.stopping ? "Stopping..." : PHASES[status.phase] || status.phase));
const ELAPSED_THRESHOLD_S = 3;

function clock(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
  const secs = String(total % 60).padStart(2, "0");
  return hours ? `${hours}:${minutes}:${secs}` : `${minutes}:${secs}`;
}

function elapsedSeconds(start, end) {
  if (!start) return 0;
  return ((end ? end * 1000 : now.value) - start * 1000) / 1000;
}

const elapsedText = computed(() => {
  const seconds = elapsedSeconds(status.started_at, status.running ? null : status.ended_at);
  return status.started_at && seconds >= ELAPSED_THRESHOLD_S ? clock(seconds) : "";
});
const countdownText = computed(() => {
  if (!status.running) return "";
  if (status.phase === "scheduled" && status.start_at && status.start_at * 1000 > now.value) {
    return `starts in ${clock(status.start_at - now.value / 1000)}`;
  }
  if (status.next_retry_at && status.next_retry_at * 1000 > now.value) {
    return `next try in ${clock(status.next_retry_at - now.value / 1000)}`;
  }
  return "";
});
const loginProgress = computed(() => (status.running && status.phase === "login" && status.login?.max ? `attempt ${status.login.attempt}/${status.login.max}` : ""));
const credentialsRejected = computed(() => Boolean(rejectedCredentials.value
  && rejectedCredentials.value.id === credentials.studentId && rejectedCredentials.value.pw === credentials.password));
const scheduledHint = computed(() => {
  if (options.startMode === "at") return "The app logs in about a minute before this time and bids at the time. Keep the app open and the computer awake until then.";
  if (options.startMode === "after") return "The countdown starts when you click Start. Keep the app open and the computer awake until bidding starts.";
  return "";
});

function formatSlots(slots = {}) {
  return Object.entries(slots)
    .filter(([, values]) => values?.length)
    .map(([type, values]) => `${type} ${values.join(", ")}`)
    .join("  ·  ") || "Any available slot";
}

function formatSessions(sessions = []) {
  return sessions.map((session) => `${session.day} ${session.time}`).join(" / ");
}

function formatTime(epoch) {
  return new Date(epoch * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function resultFor(code) {
  return status.results[code];
}

function resultDetail(result) {
  if (!result) return "";
  const via = result.plan && result.plan !== plans.value[activePlan.value]?.name ? ` (via ${result.plan})` : "";
  return `${result.message || ""}${via}`;
}

function stepTime(step) {
  if (!step.started_at) return "";
  const seconds = elapsedSeconds(step.started_at, step.ended_at);
  return step.state === "running" || seconds >= 1 ? clock(seconds) : "";
}

const STEP_LABELS = { pending: "Waiting", running: "Running", ok: "Done", warn: "Warning", error: "Failed", skipped: "Skipped" };

// --------------------------------------------------------------- backend calls
async function callApi(method, ...args) {
  if (!api || typeof api[method] !== "function") {
    throw new Error("The desktop bridge is not available. Start the Python application instead of the Vue dev page.");
  }
  return api[method](...args);
}

async function loadCourses() {
  try {
    const loaded = await callApi("get_plans");
    plans.value = loaded.length ? loaded : [{ name: "Plan A", courses: [] }];
    activePlan.value = 0;
    selectedCode.value = courses.value[0]?.code || "";
    setNotice(`${courses.value.length} course(s) ready.`, "success", { toast: false });
  } catch (error) {
    setNotice(error.message, "error");
  }
}

async function loadCredentials() {
  try {
    const saved = await callApi("get_saved_credentials");
    credentials.studentId = saved.student_id || credentials.studentId;
    credentials.password = saved.password || credentials.password;
    credentials.remember = saved.remember;
    credentials.secure = saved.secure_storage;
  } catch (error) {
    setNotice(`Saved login could not be loaded: ${error.message}`, "error");
  } finally {
    credentialsLoaded = true;
  }
}

async function persistCredentials() {
  try {
    await callApi("save_credentials", credentials.studentId, credentials.password, credentials.remember);
  } catch (error) {
    setNotice(`Login could not be saved: ${error.message}`, "error");
  }
}

watch(() => [credentials.studentId, credentials.password, credentials.remember], () => {
  if (!credentialsLoaded) return;
  window.clearTimeout(saveCredentialsTimer);
  saveCredentialsTimer = window.setTimeout(persistCredentials, 500);
});

// A rejected login stays on screen until the user edits the credentials or dismisses it.
watch(() => [credentials.studentId, credentials.password], () => {
  if (loginError.value?.kind === "invalid_credentials" && !credentialsRejected.value) loginError.value = null;
});

async function refreshBrowser() {
  try {
    const result = await callApi("browser_status");
    Object.assign(browser, result, { checked: true });
  } catch (error) {
    browser.checked = false;
  }
}

async function installBrowser() {
  try {
    Object.assign(browser, await callApi("install_browser"));
    setNotice("Downloading the browser for the Playwright method. This can take a few minutes.", "info");
  } catch (error) {
    setNotice(error.message, "error");
  }
}

watch(() => options.method, (method) => { if (method === "Playwright") refreshBrowser(); });

async function savePlans(message = "Course list saved.") {
  try {
    await callApi("save_plans", plans.value);
    setNotice(message, "success");
  } catch (error) {
    setNotice(error.message, "error");
  }
}

// --------------------------------------------------------------- courses
function parseSlotInput(value) {
  const input = value.trim();
  if (!input) return [];
  const parts = input.split(",").map((slot) => slot.trim());
  if (parts.some((slot) => !/^\d+$/.test(slot))) return null;
  return parts.map((slot) => Number.parseInt(slot, 10));
}

function openCourseDialog(course = null) {
  courseBeingEdited.value = course;
  courseForm.code = course?.code || "";
  courseForm.name = course?.name || "";
  courseForm.lecture = course?.slots?.L?.join(", ") || "";
  courseForm.tutorial = course?.slots?.T?.join(", ") || "";
  courseForm.practical = course?.slots?.P?.join(", ") || "";
  courseDialogOpen.value = true;
}

function closeCourseDialog() {
  courseDialogOpen.value = false;
  courseBeingEdited.value = null;
}

async function saveCourseDialog() {
  const code = courseForm.code.trim().toUpperCase();
  const name = courseForm.name.trim();
  if (!code || !name) {
    setNotice("Course code and course name are required.", "error");
    return;
  }
  const duplicate = courses.value.some((course) => course.code === code && course !== courseBeingEdited.value);
  if (duplicate) {
    setNotice(`${code} is already in your course list.`, "error");
    return;
  }
  const lecture = parseSlotInput(courseForm.lecture);
  const tutorial = parseSlotInput(courseForm.tutorial);
  const practical = parseSlotInput(courseForm.practical);
  if (!lecture || !tutorial || !practical) {
    setNotice("Slot numbers must be comma-separated numbers, such as 1, 2, 3.", "error");
    return;
  }
  const nextCourse = { code, name, slots: { L: lecture, T: tutorial, P: practical } };
  if (courseBeingEdited.value) Object.assign(courseBeingEdited.value, nextCourse);
  else courses.value.push(nextCourse);
  selectedCode.value = code;
  closeCourseDialog();
  await savePlans();
}

function requestRemoveCourse(course) {
  courseBeingRemoved.value = course;
  deleteDialogOpen.value = true;
}

async function confirmRemoveCourse() {
  if (!courseBeingRemoved.value) return;
  const plan = plans.value[activePlan.value];
  const removedCode = courseBeingRemoved.value.code;
  plan.courses = plan.courses.filter((course) => course !== courseBeingRemoved.value);
  selectedCode.value = plan.courses[0]?.code || "";
  deleteDialogOpen.value = false;
  courseBeingRemoved.value = null;
  setNotice(`${removedCode} was removed.`, "success");
  await savePlans();
}

// --------------------------------------------------------------- import (picker + drag and drop)
const IMPORT_TYPES = [".txt", ".json"];

async function startImport(file) {
  if (!file) return;
  if (!IMPORT_TYPES.some((extension) => file.name.toLowerCase().endsWith(extension))) {
    setNotice(`${file.name} is not supported. Import a UTAR timetable .txt file or a .json course list.`, "error");
    return;
  }
  try {
    const content = await file.text();
    const parsed = await callApi("preview_import", file.name, content);
    const currentHasCourses = courses.value.length > 0;
    Object.assign(importDialog, {
      open: true,
      filename: file.name,
      content,
      courses: parsed,
      mode: currentHasCourses ? "new" : "replace",
      newName: `Plan ${String.fromCharCode(65 + plans.value.length)}`,
    });
  } catch (error) {
    setNotice(error.message, "error");
  }
}

async function importFile(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  await startImport(file);
}

async function confirmImport() {
  const { filename, content, mode } = importDialog;
  const newName = importDialog.newName.trim();
  if (mode === "new" && !newName) {
    setNotice("Give the new plan a name.", "error");
    return;
  }
  try {
    const updated = await callApi("import_courses", filename, content, activePlan.value, mode, newName);
    plans.value = updated;
    if (mode === "new") activePlan.value = updated.length - 1;
    selectedCode.value = courses.value[0]?.code || "";
    importDialog.open = false;
    const where = mode === "new" ? ` into new plan ${plans.value[activePlan.value].name}` : "";
    setNotice(`Loaded ${importDialog.courses.length} course(s) from ${filename}${where}.`, "success");
  } catch (error) {
    setNotice(error.message, "error");
  }
}

function hasFiles(event) {
  return Array.from(event.dataTransfer?.types || []).includes("Files");
}

function onDragOver(event) {
  if (!hasFiles(event)) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = "copy";
  dragActive.value = true;
}

function onDragLeave(event) {
  if (!event.currentTarget.contains(event.relatedTarget)) dragActive.value = false;
}

async function onDrop(event) {
  if (!hasFiles(event)) return;
  event.preventDefault();
  event.stopPropagation();
  dragActive.value = false;
  const files = Array.from(event.dataTransfer.files || []);
  if (!files.length) {
    setNotice("Nothing was dropped. Drag a timetable .txt or .json file onto the course list.", "error");
    return;
  }
  if (files.length > 1) setNotice(`Importing ${files[0].name} only; drop one file at a time.`, "info");
  await startImport(files[0]);
}

// Without this, dropping a file anywhere else makes the window open the file
// itself and the app disappears.
function blockWindowDrop(event) {
  if (!hasFiles(event)) return;
  event.preventDefault();
  if (event.type === "drop") setNotice("Drop the file on the course list (Courses tab) to import it.", "info");
}

// --------------------------------------------------------------- plans
function selectPlan(index) {
  activePlan.value = index;
  selectedCode.value = courses.value[0]?.code || "";
}

async function addPlan() {
  const letter = String.fromCharCode(65 + plans.value.length);
  plans.value.push({ name: `Plan ${letter}`, courses: [] });
  selectPlan(plans.value.length - 1);
  await savePlans(`Plan ${letter} added. It is used only if the plans before it cannot be completed.`);
}

function openPlanDialog() {
  planNameDraft.value = plans.value[activePlan.value].name;
  planDialogOpen.value = true;
}

async function savePlanName() {
  const name = planNameDraft.value.trim();
  if (!name) {
    setNotice("Give the plan a name.", "error");
    return;
  }
  plans.value[activePlan.value].name = name;
  planDialogOpen.value = false;
  await savePlans("Plan renamed.");
}

async function confirmRemovePlan() {
  const removed = plans.value[activePlan.value].name;
  plans.value.splice(activePlan.value, 1);
  removePlanDialogOpen.value = false;
  selectPlan(Math.max(0, activePlan.value - 1));
  await savePlans(`${removed} was removed.`);
}

// --------------------------------------------------------------- runs
function scheduledEpoch() {
  if (options.startMode === "after") {
    const minutes = Number(options.delayMinutes);
    return Date.now() / 1000 + minutes * 60;
  }
  if (options.startMode !== "at" || !options.startTime) return null;
  const [hours, minutes, seconds = 0] = options.startTime.split(":").map(Number);
  const when = new Date();
  when.setHours(hours, minutes, seconds, 0);
  if (when.getTime() <= Date.now()) when.setDate(when.getDate() + 1);
  return when.getTime() / 1000;
}

function credentialsReady() {
  if (!credentials.studentId || !credentials.password) {
    setNotice("Enter your student ID and password first.", "error");
    activeTab.value = "login";
    return false;
  }
  if (credentialsRejected.value) {
    setNotice("UTAR rejected this student ID or password. Correct it in Login & settings before starting.", "error");
    activeTab.value = "login";
    return false;
  }
  return true;
}

async function startRun() {
  if (!credentialsReady()) return;
  if (!totalCourses.value) {
    setNotice("Add or import at least one course first.", "error");
    activeTab.value = "courses";
    return;
  }
  if (options.startMode === "at" && !options.startTime) {
    setNotice("Choose the time bidding should start.", "error");
    activeTab.value = "login";
    return;
  }
  if (options.startMode === "after" && !(Number(options.delayMinutes) > 0)) {
    setNotice("Enter how many minutes to wait before bidding starts.", "error");
    activeTab.value = "login";
    return;
  }
  const runOptions = {
    fallback_mode: options.fallbackMode,
    auto_retry_seconds: options.autoRetry ? Number(options.retrySeconds) || 0 : 0,
    max_attempts: options.autoRetry ? Number(options.maxAttempts) || 0 : 0,
    start_at: scheduledEpoch(),
  };
  try {
    loginError.value = null;
    await callApi("start", credentials.studentId, credentials.password, options.method, !options.browserVisible, runOptions);
    activeTab.value = "run";
    setNotice(runOptions.start_at
      ? `Scheduled for ${formatTime(runOptions.start_at)}. Keep the app open until bidding starts.`
      : "Login started. You can follow each course on the Registration tab.", "info");
  } catch (error) {
    setNotice(error.message, "error");
  }
}

async function runPreflight() {
  if (!credentialsReady()) return;
  try {
    loginError.value = null;
    await callApi("preflight", credentials.studentId, credentials.password, options.method, !options.browserVisible);
    activeTab.value = "preflight";
    setNotice(totalCourses.value
      ? "Pre-flight check started. Nothing will be registered."
      : "Pre-flight check started: checking login only (no course plan yet).", "info");
  } catch (error) {
    setNotice(error.message, "error");
  }
}

async function stopRun() {
  try {
    Object.assign(status, await callApi("cancel"));
    setNotice("Stopping... the current network step will finish safely first.", "info");
  } catch (error) {
    setNotice(error.message, "error");
  }
}

async function answerProposal(codes) {
  try {
    await callApi("choose", codes);
  } catch (error) {
    setNotice(error.message, "error");
  }
}

async function openLogsFolder() {
  try {
    const folder = await callApi("open_logs_folder");
    setNotice(`Opened ${folder}`, "info", { toast: false });
  } catch (error) {
    setNotice(error.message, "error");
  }
}

const FINAL_TYPES = { complete: "success", preflight_done: "success", error: "error", cancelled: "info" };
const LOGIN_TITLES = {
  invalid_credentials: "UTAR rejected the student ID or password",
  portal_closed: "Logged in, but UTAR closed the session at once",
  portal_unavailable: "The portal did not respond properly",
  browser_missing: "The Playwright browser is not installed",
  account_not_allowed: "UTAR refused this account",
  login: "Login failed",
};

function handleFinished(next) {
  const runKey = `${next.kind}|${next.started_at}`;
  if (next.running || !next.started_at || runKey === lastFinishedRun) return;
  lastFinishedRun = runKey;
  const type = FINAL_TYPES[next.phase];
  if (type) setNotice(next.message, type);
  if (next.phase === "error" && next.error_source === "login") {
    loginError.value = {
      kind: next.error_kind || "login",
      title: LOGIN_TITLES[next.error_kind] || LOGIN_TITLES.login,
      message: next.message,
      reasons: next.login?.reasons || [],
    };
    if (next.error_kind === "invalid_credentials") {
      rejectedCredentials.value = { id: credentials.studentId, pw: credentials.password };
    }
    if (next.error_kind === "browser_missing") refreshBrowser();
    activeTab.value = "login";
  }
}

async function refreshStatus() {
  if (!api) return;
  try {
    const next = await callApi("get_status");
    Object.assign(status, next);
    handleFinished(next);
  } catch (error) {
    setNotice(error.message, "error");
  }
  if (browser.install?.running) refreshBrowser();
}

// Reset the ticks only when a different prompt appears. The status poll replaces
// the proposal object every 700 ms, which must not undo the user's choices.
watch(
  () => (status.proposal ? `${status.proposal.plan}|${status.proposal.items.map((item) => item.code).join(",")}` : ""),
  (key) => {
    proposalChoice.value = key ? status.proposal.items.filter((item) => item.action === "add").map((item) => item.code) : [];
    if (key) activeTab.value = "run";
  },
);

function attachBridge() {
  api = window.pywebview?.api;
  bridgeReady.value = Boolean(api);
  if (api) startup();
}

let started = false;
function startup() {
  if (started) return;
  started = true;
  loadCourses();
  loadCredentials();
}

onMounted(() => {
  window.addEventListener("pywebviewready", attachBridge, { once: true });
  window.addEventListener("dragover", blockWindowDrop);
  window.addEventListener("drop", blockWindowDrop);
  if (api) startup();
  pollTimer = window.setInterval(refreshStatus, 700);
  clockTimer = window.setInterval(() => { now.value = Date.now(); }, 500);
});

onUnmounted(() => {
  window.removeEventListener("pywebviewready", attachBridge);
  window.removeEventListener("dragover", blockWindowDrop);
  window.removeEventListener("drop", blockWindowDrop);
  window.clearInterval(pollTimer);
  window.clearInterval(clockTimer);
  window.clearTimeout(toastTimer);
  window.clearTimeout(saveCredentialsTimer);
});
</script>

<template>
  <main class="app-shell" :data-bridge="bridgeReady ? 'ready' : 'waiting'">
    <header class="topbar">
      <h1>UTAR Course Bidding</h1>
      <div class="run-controls">
        <span class="run-chip" :class="[status.phase, { running: status.running, stopping: status.stopping && status.running }]" role="status">
          <span class="status-dot"></span>
          <span class="run-chip-label">{{ phaseLabel }}</span>
          <span v-if="loginProgress" class="run-chip-extra">{{ loginProgress }}</span>
          <span v-if="countdownText" class="run-chip-extra">{{ countdownText }}</span>
          <span v-if="elapsedText && (status.running || status.ended_at)" class="run-chip-time" title="Elapsed time">{{ elapsedText }}</span>
        </span>
        <button v-if="!status.running" class="quiet-action compact" @click="runPreflight">Run pre-flight check</button>
        <button v-if="!status.running" class="primary-action compact" @click="startRun">{{ startLabel }}</button>
        <button v-else class="quiet-action compact danger" :disabled="status.stopping" @click="stopRun">{{ status.stopping ? "Stopping..." : "Stop safely" }}</button>
      </div>
    </header>
    <p v-if="!bridgeReady" class="bridge-warning">Waiting for the desktop bridge. If this stays, start the app with UnitRegTimetable.exe or main.py.</p>

    <nav class="tabs" role="tablist" aria-label="Sections">
      <button v-for="tab in TABS" :key="tab.id" role="tab" class="tab" :class="{ active: activeTab === tab.id }" :aria-selected="activeTab === tab.id" @click="activeTab = tab.id">
        {{ tab.label }}
        <span v-if="tab.id === 'login' && loginError" class="tab-flag error" title="Login problem">!</span>
        <span v-if="tab.id === 'preflight' && status.running && status.kind === 'preflight'" class="tab-flag busy" title="Running"></span>
        <span v-if="tab.id === 'run' && status.running && status.kind === 'run'" class="tab-flag busy" title="Running"></span>
      </button>
    </nav>

    <section class="status-strip">
      <p class="current-message">{{ status.message }}<span v-if="status.attempt > 1"> (attempt {{ status.attempt }})</span><span v-if="elapsedText && status.running" class="message-time"> · {{ elapsedText }}</span></p>
      <div class="notice" :class="notice.type">{{ notice.text }}</div>
    </section>

    <!-- ============================================================ Courses -->
    <section v-show="activeTab === 'courses'" class="panel course-panel drop-zone" :class="{ dragging: dragActive }" role="tabpanel" @dragover="onDragOver" @dragenter="onDragOver" @dragleave="onDragLeave" @drop="onDrop">
      <div class="panel-heading">
        <h2>Course plan <span class="count-badge">{{ courses.length }}</span></h2>
        <div class="toolbar">
          <button title="Import a timetable or JSON file" @click="fileInput?.click()">Import file</button>
          <input ref="fileInput" class="visually-hidden" type="file" accept=".txt,.json" @change="importFile" />
          <button title="Add a course" @click="openCourseDialog()">Add course</button>
        </div>
      </div>
      <div v-if="dragActive" class="drop-overlay">Drop a timetable .txt or .json file to import it</div>

      <div class="plan-tabs" role="tablist" aria-label="Timetable plans">
        <button v-for="(plan, index) in plans" :key="index" role="tab" class="plan-tab" :class="{ active: index === activePlan }" :aria-selected="index === activePlan" @click="selectPlan(index)">
          {{ plan.name }}<span class="plan-count">{{ plan.courses.length }}</span>
        </button>
        <button class="plan-tab add" title="Add a backup timetable" @click="addPlan">Add plan</button>
        <span class="plan-tools">
          <button title="Rename this plan" @click="openPlanDialog">Rename</button>
          <button v-if="plans.length > 1" class="text-danger" title="Remove this plan" @click="removePlanDialogOpen = true">Remove plan</button>
        </span>
      </div>
      <p v-if="plans.length > 1" class="helper plan-helper">Plans are tried in order. A later plan is used only for courses still missing, and only where the class is free and does not clash with what you already hold.</p>

      <div v-if="!courses.length" class="empty-state">
        <strong>Your course list is empty.</strong>
        <span>Import a timetable file, drag one here, or add your first course.</span>
      </div>
      <div v-else class="management-table-wrap">
        <table class="management-table">
          <thead><tr><th>Code</th><th>Course</th><th>Preferred slots</th><th>Outcome</th><th><span class="visually-hidden">Actions</span></th></tr></thead>
          <tbody>
            <tr v-for="course in courses" :key="course.code" :class="{ selected: selectedCode === course.code }" @click="selectedCode = course.code">
              <td class="course-code">{{ course.code }}</td>
              <td class="course-name">{{ course.name }}</td>
              <td class="course-slots">{{ formatSlots(course.slots) }}</td>
              <td class="outcome-cell" :title="resultFor(course.code)?.history?.join('\n')">
                <span class="row-status" :class="resultFor(course.code)?.status || 'ready'">{{ resultFor(course.code)?.label || "Ready" }}</span>
                <span v-if="resultFor(course.code)" class="outcome-detail">{{ resultDetail(resultFor(course.code)) }}</span>
              </td>
              <td class="row-actions"><button title="Edit course" @click.stop="openCourseDialog(course)">Edit</button><button class="text-danger" title="Remove course" @click.stop="requestRemoveCourse(course)">Remove</button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="helper">Drag a timetable .txt or .json file onto this panel, or use Import file. Changes save automatically.</p>
    </section>

    <!-- ============================================================ Login & settings -->
    <section v-show="activeTab === 'login'" class="settings-grid" role="tabpanel">
      <div class="panel">
        <h2 class="panel-title">Login</h2>
        <div v-if="loginError" class="login-error" role="alert">
          <div class="login-error-head"><strong>{{ loginError.title }}</strong><button type="button" class="link-button" @click="loginError = null">Dismiss</button></div>
          <p>{{ loginError.message }}</p>
          <ol v-if="loginError.reasons.length > 1" class="attempt-list"><li v-for="(reason, index) in loginError.reasons" :key="index">{{ reason }}</li></ol>
          <p v-if="loginError.kind === 'invalid_credentials'" class="hint">Correct the student ID or password below; Start is blocked until you change them.</p>
          <p v-else-if="loginError.kind === 'portal_closed'" class="hint">This usually means course registration is not open yet. Use a scheduled start: the app keeps retrying the login (never bidding) until shortly after the start time.</p>
          <p v-else-if="loginError.kind === 'account_not_allowed'" class="hint">The student ID and password were accepted, but UTAR will not let this account into course registration. The reason above is UTAR's own message; it has to be resolved with UTAR (faculty officer or academic adviser). The app cannot bypass it, and retrying will not help until it is resolved.</p>
          <p v-else-if="loginError.kind === 'browser_missing'" class="hint">Install the browser below, or switch the connection method to BeautifulSoup.</p>
        </div>
        <label>Student ID<input v-model.trim="credentials.studentId" :class="{ invalid: credentialsRejected }" autocomplete="username" placeholder="e.g. 2103370" /></label>
        <div class="field">
          <label for="password-input">Password</label>
          <div class="password-field">
            <input id="password-input" v-model="credentials.password" :type="showPassword ? 'text' : 'password'" :class="{ invalid: credentialsRejected }" autocomplete="current-password" placeholder="Your UTAR password" />
            <button type="button" class="reveal-button" :aria-pressed="showPassword" :title="showPassword ? 'Hide the typed text' : 'Show the typed text'" @mousedown.prevent @click="showPassword = !showPassword">{{ showPassword ? "Hide" : "Show" }}</button>
          </div>
        </div>
        <label class="toggle-label"><span>Remember on this computer</span><input v-model="credentials.remember" type="checkbox" /><span class="toggle"></span></label>
        <p class="helper">{{ credentials.secure ? "The password is encrypted with your Windows account (DPAPI) before it is saved; it is never written to logs." : "Secure storage is not available here, so only the student ID is remembered." }}</p>

        <h3 class="sub-title">Connection</h3>
        <div class="field-row">
          <label>Connection method<select v-model="options.method"><option>BeautifulSoup</option><option>Playwright</option></select></label>
          <label v-if="options.method === 'Playwright'" class="toggle-label"><span>Browser visible</span><input v-model="options.browserVisible" type="checkbox" /><span class="toggle"></span></label>
        </div>
        <div v-if="options.method === 'Playwright' && browser.checked && !browser.installed" class="browser-box">
          <p><strong>The Playwright browser is not installed.</strong> It is a one-time download of about 150 MB to {{ browser.path }}.</p>
          <button type="button" class="primary-action compact" :disabled="browser.install.running" @click="installBrowser">{{ browser.install.running ? "Installing..." : "Install browser" }}</button>
          <p v-if="browser.install.message" class="helper">{{ browser.install.message }}</p>
        </div>
        <p v-else-if="options.method === 'Playwright' && browser.install.ok" class="helper">Browser installed.</p>
      </div>

      <div class="panel">
        <h2 class="panel-title">Bidding options</h2>
        <label>When should bidding start?<select v-model="options.startMode"><option value="now">Immediately after login</option><option value="at">At a set clock time</option><option value="after">After a delay</option></select></label>
        <label v-if="options.startMode === 'at'">Bidding opens at<input v-model="options.startTime" type="time" step="1" /></label>
        <label v-if="options.startMode === 'after'">Start after (minutes)<input v-model.number="options.delayMinutes" type="number" min="1" step="1" /></label>
        <p v-if="scheduledHint" class="helper warn-text">{{ scheduledHint }}</p>

        <label>If a plan cannot be completed<select v-model="options.fallbackMode"><option value="auto">Use the next plan automatically</option><option value="ask">Ask me what to bid first</option></select></label>
        <label class="toggle-label"><span>Retry until registered</span><input v-model="options.autoRetry" type="checkbox" /><span class="toggle"></span></label>
        <div v-if="options.autoRetry" class="field-row">
          <label>Retry every (seconds)<input v-model.number="options.retrySeconds" type="number" min="5" /></label>
          <label>Stop after (attempts)<input v-model.number="options.maxAttempts" type="number" min="1" /></label>
        </div>
        <p class="helper">Courses already registered are skipped, so starting again only retries what is missing.</p>
      </div>
    </section>

    <!-- ============================================================ Pre-flight -->
    <section v-show="activeTab === 'preflight'" class="panel" role="tabpanel">
      <div class="panel-heading">
        <h2>Pre-flight check</h2>
      </div>
      <p class="helper top">Logs in and checks your plans without registering anything. It also works with no course plan, to test the login on its own.</p>
      <ol v-if="status.kind === 'preflight' && status.steps.length" class="step-list">
        <li v-for="step in status.steps" :key="step.id" class="step" :class="step.state">
          <span class="step-state"><span v-if="step.state === 'running'" class="spinner" aria-hidden="true"></span>{{ STEP_LABELS[step.state] }}</span>
          <span class="step-body"><strong>{{ step.label }}</strong><span v-if="step.id === 'login' && step.state === 'running' && status.login.max" class="step-detail">Attempt {{ status.login.attempt }}/{{ status.login.max }}<template v-if="status.login.reasons.length">, previous: {{ status.login.reasons[status.login.reasons.length - 1] }}</template></span><span v-if="step.detail" class="step-detail">{{ step.detail }}</span></span>
          <span class="step-time">{{ stepTime(step) }}</span>
        </li>
      </ol>
      <p v-else class="empty-note">No pre-flight check has run yet.</p>
      <div v-if="status.preflight && status.kind === 'preflight'" class="preflight">
        <h3>Findings</h3>
        <ul>
          <li v-for="(check, index) in status.preflight.checks" :key="index" :class="check.level"><span class="check-level">{{ { ok: "OK", info: "Note", warn: "Warning", error: "Problem" }[check.level] }}</span>{{ check.text }}</li>
        </ul>
      </div>
    </section>

    <!-- ============================================================ Registration -->
    <section v-show="activeTab === 'run'" class="run-grid" role="tabpanel">
      <div class="panel progress-panel">
        <div class="panel-heading progress-heading">
          <h2>Registration progress</h2>
          <div class="progress-summary"><strong>{{ successCount }}</strong><span>registered</span><strong class="failed-number">{{ failedCount }}</strong><span>needs attention</span></div>
        </div>
        <div class="progress-track"><span :style="{ width: `${status.total ? (status.completed / status.total) * 100 : 0}%` }"></span></div>
        <p v-if="status.running && status.phase === 'scheduled'" class="helper warn-text">Waiting for the scheduled start. Keep the app open and the computer awake.</p>
        <ul v-if="resultList.length" class="result-list">
          <li v-for="result in resultList" :key="result.code"><span class="course-code">{{ result.code }}</span><span class="row-status" :class="result.status">{{ result.label }}</span><span class="outcome-detail">{{ resultDetail(result) }}</span></li>
        </ul>
        <p v-else class="empty-note">No registration has run yet. Click Start registration when you are ready.</p>
      </div>

      <div v-if="status.registered.length || creditText" class="panel registered-panel">
        <div class="panel-heading progress-heading">
          <h2>Confirmed by UTAR <span class="count-badge">{{ status.registered.length }}</span></h2>
          <div v-if="creditText" class="credit-meter">{{ creditText }}</div>
        </div>
        <p v-if="!status.registered.length" class="helper">UTAR shows no registered courses yet.</p>
        <div v-else class="registered-list">
          <article v-for="course in status.registered" :key="course.code" class="registered-card">
            <header><span class="course-code">{{ course.code }}</span><span class="registered-name">{{ course.name }}</span><span class="registered-credit">{{ course.credit_hours }} CH</span></header>
            <p v-if="course.status" class="registered-status">{{ course.status }}</p>
            <ul>
              <li v-for="item in course.classes" :key="item.type + item.group"><span class="class-chip">{{ item.type }}{{ item.group }}</span><span>{{ formatSessions(item.sessions) }}</span><span class="class-room">{{ item.sessions[0]?.room }}</span></li>
            </ul>
          </article>
        </div>
        <p class="helper">Read from UTAR's own registration page after each plan, so it shows what is really registered.</p>
      </div>
    </section>

    <!-- ============================================================ Logs -->
    <section v-show="activeTab === 'logs'" class="panel" role="tabpanel">
      <div class="panel-heading">
        <h2>Activity log</h2>
        <button class="quiet-action compact" @click="openLogsFolder">Open logs folder</button>
      </div>
      <p class="helper top">Steps of the current or last run. Detailed logs are in the logs folder; set <code>level = DEBUG</code> and <code>debug_dumps = true</code> under [Logging] in config.ini for request/response files and screenshots (passwords and cookies are masked).</p>
      <ol v-if="status.log.length" class="activity-log">
        <li v-for="(entry, index) in status.log" :key="index" :class="entry.level"><time>{{ formatTime(entry.t) }}</time><span>{{ entry.text }}</span></li>
      </ol>
      <p v-else class="empty-note">Nothing has run yet.</p>
    </section>

    <!-- ============================================================ dialogs -->
    <div v-if="courseDialogOpen" class="modal-backdrop" @click.self="closeCourseDialog">
      <form class="modal-dialog" @submit.prevent="saveCourseDialog">
        <div class="modal-heading"><div><p class="section-kicker">COURSE DETAILS</p><h2>{{ courseBeingEdited ? "Edit course" : "Add course" }}</h2></div><button type="button" class="icon-close" aria-label="Close" @click="closeCourseDialog">&times;</button></div>
        <label>Course code<input v-model="courseForm.code" placeholder="e.g. UCCD1003" /></label>
        <label>Course name<input v-model="courseForm.name" placeholder="e.g. Database Technology" /></label>
        <div class="slot-grid"><label>Lecture slots<input v-model="courseForm.lecture" placeholder="1, 2, 3" /></label><label>Tutorial slots<input v-model="courseForm.tutorial" placeholder="1, 2, 3" /></label><label>Practical slots<input v-model="courseForm.practical" placeholder="1, 2, 3" /></label></div>
        <p class="helper">Enter preferred slot numbers separated by commas. Leave a category empty if it does not apply.</p>
        <div class="modal-actions"><button type="button" class="quiet-action" @click="closeCourseDialog">Cancel</button><button type="submit" class="primary-action">Save course</button></div>
      </form>
    </div>

    <div v-if="deleteDialogOpen" class="modal-backdrop" @click.self="deleteDialogOpen = false">
      <div class="modal-dialog compact-dialog"><div class="modal-heading"><div><p class="section-kicker">REMOVE COURSE</p><h2>Remove {{ courseBeingRemoved?.code }}?</h2></div><button type="button" class="icon-close" aria-label="Close" @click="deleteDialogOpen = false">&times;</button></div><p class="modal-copy">This removes the course from your saved plan. You can add it again later.</p><div class="modal-actions"><button type="button" class="quiet-action" @click="deleteDialogOpen = false">Keep course</button><button type="button" class="primary-action danger-action" @click="confirmRemoveCourse">Remove course</button></div></div>
    </div>

    <div v-if="planDialogOpen" class="modal-backdrop" @click.self="planDialogOpen = false">
      <form class="modal-dialog compact-dialog" @submit.prevent="savePlanName">
        <div class="modal-heading"><div><p class="section-kicker">TIMETABLE PLAN</p><h2>Rename plan</h2></div><button type="button" class="icon-close" aria-label="Close" @click="planDialogOpen = false">&times;</button></div>
        <label>Plan name<input v-model="planNameDraft" placeholder="e.g. Plan B - morning classes" /></label>
        <div class="modal-actions"><button type="button" class="quiet-action" @click="planDialogOpen = false">Cancel</button><button type="submit" class="primary-action">Save name</button></div>
      </form>
    </div>

    <div v-if="removePlanDialogOpen" class="modal-backdrop" @click.self="removePlanDialogOpen = false">
      <div class="modal-dialog compact-dialog"><div class="modal-heading"><div><p class="section-kicker">REMOVE PLAN</p><h2>Remove {{ plans[activePlan]?.name }}?</h2></div><button type="button" class="icon-close" aria-label="Close" @click="removePlanDialogOpen = false">&times;</button></div><p class="modal-copy">This deletes the plan and its {{ courses.length }} course(s). Nothing is changed at UTAR.</p><div class="modal-actions"><button type="button" class="quiet-action" @click="removePlanDialogOpen = false">Keep plan</button><button type="button" class="primary-action danger-action" @click="confirmRemovePlan">Remove this plan</button></div></div>
    </div>

    <div v-if="importDialog.open" class="modal-backdrop" @click.self="importDialog.open = false">
      <form class="modal-dialog" @submit.prevent="confirmImport">
        <div class="modal-heading"><div><p class="section-kicker">IMPORT TIMETABLE</p><h2>Import {{ importDialog.courses.length }} course(s) from {{ importDialog.filename }}</h2></div><button type="button" class="icon-close" aria-label="Close" @click="importDialog.open = false">&times;</button></div>
        <div class="import-choice">
          <label class="choice" :class="{ active: importDialog.mode === 'new' }"><input v-model="importDialog.mode" type="radio" value="new" /><span><strong>Import as new plan</strong><span>Adds a separate plan. All existing plans stay as they are.</span></span></label>
          <label v-if="importDialog.mode === 'new'" class="new-plan-name">New plan name<input v-model="importDialog.newName" /></label>
          <label class="choice" :class="{ active: importDialog.mode === 'replace' }"><input v-model="importDialog.mode" type="radio" value="replace" /><span><strong>Replace {{ plans[activePlan]?.name }}</strong><span>{{ courses.length ? `Its ${courses.length} current course(s) are replaced and cannot be restored.` : "This plan is empty, so nothing is lost." }}</span></span></label>
        </div>
        <ul class="import-preview"><li v-for="course in importDialog.courses.slice(0, 8)" :key="course.code"><span class="course-code">{{ course.code }}</span> {{ course.name }}</li><li v-if="importDialog.courses.length > 8">and {{ importDialog.courses.length - 8 }} more</li></ul>
        <div class="modal-actions"><button type="button" class="quiet-action" @click="importDialog.open = false">Cancel</button><button type="submit" class="primary-action">{{ importDialog.mode === "new" ? "Import as new plan" : "Replace plan" }}</button></div>
      </form>
    </div>

    <div v-if="proposalOpen" class="modal-backdrop">
      <div class="modal-dialog proposal-dialog">
        <div class="modal-heading"><div><p class="section-kicker">CHOOSE BEFORE BIDDING</p><h2>{{ status.proposal.plan }}: what should be bid?</h2></div></div>
        <p class="modal-copy">The earlier plan could not be completed. These are the courses from {{ status.proposal.plan }}, checked against what you hold now.</p>
        <ul class="proposal-list">
          <li v-for="item in status.proposal.items" :key="item.code" :class="item.action">
            <label v-if="item.action === 'add'" class="proposal-pick"><input v-model="proposalChoice" type="checkbox" :value="item.code" /><span><strong>{{ item.code }}</strong> {{ item.name }}</span></label>
            <span v-else class="proposal-pick"><strong>{{ item.code }}</strong> {{ item.name }}</span>
            <span class="proposal-tag">{{ { add: "Can add", keep: "Already held", switch: "Needs a switch", skip: "Cannot add" }[item.action] }}</span>
            <span class="proposal-reason">{{ item.reason }}</span>
          </li>
        </ul>
        <div class="modal-actions"><button type="button" class="quiet-action" @click="answerProposal([])">Skip this plan</button><button type="button" class="primary-action" :disabled="!proposalChoice.length" @click="answerProposal(proposalChoice)">Bid selected courses</button></div>
      </div>
    </div>

    <transition name="toast" mode="out-in"><div v-if="toast" :key="toast.id" class="toast" :class="toast.type" role="status"><span>{{ toast.text }}</span><button type="button" class="toast-close" aria-label="Dismiss notification" @click="nextToast">&times;</button></div></transition>
  </main>
</template>
