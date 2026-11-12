<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";

let api = window.pywebview?.api;
const bridgeReady = ref(Boolean(api));
const plans = ref([{ name: "Plan A", courses: [] }]);
const activePlan = ref(0);
const selectedCode = ref("");
const fileInput = ref(null);
const notice = ref({ type: "info", text: "Loading your course list..." });
const toast = ref(null);
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
});
const credentials = reactive({ studentId: "", password: "" });
const options = reactive({
  method: "BeautifulSoup",
  browserVisible: true,
  fallbackMode: "auto",
  autoRetry: false,
  retrySeconds: 30,
  maxAttempts: 10,
  scheduled: false,
  startTime: "",
});
let pollTimer;
let toastTimer;

const courses = computed(() => plans.value[activePlan.value]?.courses || []);
const totalCourses = computed(() => plans.value.reduce((sum, plan) => sum + plan.courses.length, 0));
const resultList = computed(() => Object.values(status.results));
const successCount = computed(() => resultList.value.filter((result) => result.status === "success" || result.status === "partial").length);
const failedCount = computed(() => resultList.value.filter((result) => result.status === "failed").length);
const hasMissing = computed(() => !status.running && failedCount.value > 0);
const startLabel = computed(() => {
  if (status.running) return status.phase === "preflight" ? "Pre-flight in progress" : "Registration in progress";
  return hasMissing.value ? "Retry missing courses" : "Start registration";
});
const proposalOpen = computed(() => status.phase === "awaiting_choice" && Boolean(status.proposal));
const creditText = computed(() => {
  if (!status.credit?.total && !status.credit?.max) return "";
  return `${status.credit.total || "?"} of ${status.credit.max || "?"} credit hours`;
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

function resultFor(code) {
  return status.results[code];
}

function resultDetail(result) {
  if (!result) return "";
  const via = result.plan && result.plan !== plans.value[activePlan.value]?.name ? ` (via ${result.plan})` : "";
  return `${result.message || ""}${via}`;
}

function setNotice(text, type = "info") {
  notice.value = { text, type };
  toast.value = { type, text };
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => { toast.value = null; }, 4200);
}

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
    setNotice(`${courses.value.length} course(s) ready.`, "success");
  } catch (error) {
    setNotice(error.message, "error");
  }
}

async function savePlans(message = "Course list saved.") {
  try {
    await callApi("save_plans", plans.value);
    setNotice(message, "success");
  } catch (error) {
    setNotice(error.message, "error");
  }
}

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

async function importFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    const content = await file.text();
    const imported = await callApi("import_courses", file.name, content, activePlan.value);
    plans.value[activePlan.value].courses = imported;
    selectedCode.value = imported[0]?.code || "";
    setNotice(`Loaded ${imported.length} course(s) from ${file.name}.`, "success");
  } catch (error) {
    setNotice(error.message, "error");
  } finally {
    event.target.value = "";
  }
}

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

function scheduledEpoch() {
  if (!options.scheduled || !options.startTime) return null;
  const [hours, minutes, seconds = 0] = options.startTime.split(":").map(Number);
  const when = new Date();
  when.setHours(hours, minutes, seconds, 0);
  if (when.getTime() <= Date.now()) when.setDate(when.getDate() + 1);
  return when.getTime() / 1000;
}

function credentialsReady() {
  if (!credentials.studentId || !credentials.password) {
    setNotice("Enter your student ID and password first.", "error");
    return false;
  }
  if (!totalCourses.value) {
    setNotice("Add or import at least one course first.", "error");
    return false;
  }
  return true;
}

async function startRun() {
  if (!credentialsReady()) return;
  if (options.scheduled && !options.startTime) {
    setNotice("Choose the time bidding should start.", "error");
    return;
  }
  const runOptions = {
    fallback_mode: options.fallbackMode,
    auto_retry_seconds: options.autoRetry ? Number(options.retrySeconds) || 0 : 0,
    max_attempts: options.autoRetry ? Number(options.maxAttempts) || 0 : 0,
    start_at: scheduledEpoch(),
  };
  try {
    await callApi("start", credentials.studentId, credentials.password, options.method, !options.browserVisible, runOptions);
    setNotice(runOptions.start_at ? "Scheduled. Keep the app open." : "Login started. You can watch each course below.", "info");
  } catch (error) {
    setNotice(error.message, "error");
  }
}

async function runPreflight() {
  if (!credentialsReady()) return;
  try {
    await callApi("preflight", credentials.studentId, credentials.password, options.method, !options.browserVisible);
    setNotice("Pre-flight check started. Nothing will be registered.", "info");
  } catch (error) {
    setNotice(error.message, "error");
  }
}

async function stopRun() {
  try {
    await callApi("cancel");
    setNotice("Cancellation requested. The current network operation will finish safely.", "info");
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

async function refreshStatus() {
  if (!api) return;
  try {
    const next = await callApi("get_status");
    Object.assign(status, next);
    if (next.message && next.phase !== "idle") setNotice(next.message, next.phase === "error" ? "error" : "info");
  } catch (error) {
    setNotice(error.message, "error");
  }
}

// Reset the ticks only when a different prompt appears. The status poll replaces
// the proposal object every 700 ms, which must not undo the user's choices.
watch(
  () => (status.proposal ? `${status.proposal.plan}|${status.proposal.items.map((item) => item.code).join(",")}` : ""),
  (key) => {
    proposalChoice.value = key ? status.proposal.items.filter((item) => item.action === "add").map((item) => item.code) : [];
  },
);

function attachBridge() {
  api = window.pywebview?.api;
  bridgeReady.value = Boolean(api);
  if (api) loadCourses();
}

onMounted(() => {
  window.addEventListener("pywebviewready", attachBridge, { once: true });
  if (api) loadCourses();
  pollTimer = window.setInterval(refreshStatus, 700);
});

onUnmounted(() => {
  window.removeEventListener("pywebviewready", attachBridge);
  window.clearInterval(pollTimer);
  window.clearTimeout(toastTimer);
});
</script>

<template>
  <main class="app-shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">UTAR COURSE REGISTRATION</p>
        <h1>Choose your courses with confidence.</h1>
        <p class="lede">Prepare your preferences once, then follow every registration attempt from one calm workspace.</p>
      </div>
      <div class="connection-pill" :class="{ online: bridgeReady }">
        <span class="status-dot"></span>{{ bridgeReady ? "Desktop ready" : "Waiting for desktop bridge" }}
      </div>
    </header>

    <section class="workspace-grid">
      <section class="panel setup-panel">
        <div class="panel-heading">
          <div>
            <p class="section-kicker">01 / SET UP</p>
            <h2>Registration details</h2>
          </div>
          <span class="step-mark">A</span>
        </div>
        <label>Student ID<input v-model.trim="credentials.studentId" autocomplete="username" placeholder="e.g. 2103370" /></label>
        <label>Password<input v-model="credentials.password" type="password" autocomplete="current-password" placeholder="Your UTAR password" /></label>
        <div class="field-row">
          <label>Connection method<select v-model="options.method"><option>BeautifulSoup</option><option>Playwright</option></select></label>
          <label v-if="options.method === 'Playwright'" class="toggle-label"><span>Browser visible</span><input v-model="options.browserVisible" type="checkbox" /><span class="toggle"></span></label>
        </div>

        <div class="option-group">
          <label>If a plan cannot be completed<select v-model="options.fallbackMode"><option value="auto">Use the next plan automatically</option><option value="ask">Ask me what to bid first</option></select></label>
          <label class="toggle-label"><span>Retry until registered</span><input v-model="options.autoRetry" type="checkbox" /><span class="toggle"></span></label>
          <div v-if="options.autoRetry" class="field-row">
            <label>Retry every (seconds)<input v-model.number="options.retrySeconds" type="number" min="5" /></label>
            <label>Stop after (attempts)<input v-model.number="options.maxAttempts" type="number" min="1" /></label>
          </div>
          <label class="toggle-label"><span>Start at a set time</span><input v-model="options.scheduled" type="checkbox" /><span class="toggle"></span></label>
          <label v-if="options.scheduled">Bidding opens at<input v-model="options.startTime" type="time" step="1" /></label>
        </div>

        <button class="primary-action" :disabled="status.running" @click="startRun">{{ startLabel }}</button>
        <button v-if="!status.running" class="quiet-action" @click="runPreflight">Run pre-flight check</button>
        <button v-if="status.running" class="quiet-action danger" @click="stopRun">Stop safely</button>
        <p class="helper">Courses already registered are skipped, so starting again only retries what is missing. Your credentials stay on this computer.</p>
      </section>

      <section class="panel course-panel">
        <div class="panel-heading">
          <div>
            <p class="section-kicker">02 / YOUR LIST</p>
            <h2>Course plan <span class="count-badge">{{ courses.length }}</span></h2>
          </div>
          <div class="toolbar">
            <button title="Import a timetable or JSON file" @click="fileInput?.click()">Import</button>
            <input ref="fileInput" class="visually-hidden" type="file" accept=".txt,.json" @change="importFile" />
            <button title="Add a course" @click="openCourseDialog()">Add course</button>
          </div>
        </div>

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
          <span>Import a timetable file or add your first course to begin.</span>
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
        <p class="helper">Use Edit to change the course name or preferred slots. Changes save automatically.</p>
      </section>
    </section>

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

    <section class="panel progress-panel">
      <div class="panel-heading progress-heading">
        <div><p class="section-kicker">03 / LIVE OUTCOME</p><h2>Registration progress</h2></div>
        <div class="progress-summary"><strong>{{ successCount }}</strong><span>registered</span><strong class="failed-number">{{ failedCount }}</strong><span>needs attention</span></div>
      </div>
      <div class="progress-track"><span :style="{ width: `${status.total ? (status.completed / status.total) * 100 : 0}%` }"></span></div>
      <p class="current-message">{{ status.message }}<span v-if="status.attempt > 1"> (attempt {{ status.attempt }})</span></p>
      <div class="notice" :class="notice.type">{{ notice.text }}</div>

      <div v-if="status.preflight" class="preflight">
        <h3>Pre-flight check</h3>
        <ul>
          <li v-for="(check, index) in status.preflight.checks" :key="index" :class="check.level"><span class="check-level">{{ { ok: "OK", info: "Note", warn: "Warning", error: "Problem" }[check.level] }}</span>{{ check.text }}</li>
        </ul>
      </div>
    </section>

    <section v-if="status.registered.length || creditText" class="panel registered-panel">
      <div class="panel-heading progress-heading">
        <div><p class="section-kicker">04 / CONFIRMED BY UTAR</p><h2>Registered courses <span class="count-badge">{{ status.registered.length }}</span></h2></div>
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
      <p class="helper">This list is read from UTAR's own registration page after each plan, so it shows what is really registered.</p>
    </section>

    <transition name="toast"><div v-if="toast" class="toast" :class="toast.type" role="status">{{ toast.text }}</div></transition>
  </main>
</template>
