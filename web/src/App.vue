<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";

let api = window.pywebview?.api;
const bridgeReady = ref(Boolean(api));
const courses = ref([]);
const selectedCode = ref("");
const fileInput = ref(null);
const notice = ref({ type: "info", text: "Loading your course list..." });
const toast = ref(null);
const courseDialogOpen = ref(false);
const deleteDialogOpen = ref(false);
const courseForm = reactive({ code: "", name: "", lecture: "", tutorial: "", practical: "" });
const courseBeingEdited = ref(null);
const courseBeingRemoved = ref(null);
const status = reactive({
  running: false,
  phase: "idle",
  message: "Ready",
  completed: 0,
  total: 0,
  results: {},
});
const credentials = reactive({ studentId: "", password: "" });
const options = reactive({ method: "BeautifulSoup", headless: false });
let pollTimer;

const selectedCourse = computed(() => courses.value.find((course) => course.code === selectedCode.value));
const successCount = computed(() => Object.values(status.results).filter((result) => result.status === "success").length);
const failedCount = computed(() => Object.values(status.results).filter((result) => result.status === "failed").length);
let toastTimer;

function formatSlots(slots = {}) {
  return Object.entries(slots)
    .filter(([, values]) => values?.length)
    .map(([type, values]) => `${type} ${values.join(", ")}`)
    .join("  ·  ") || "Any available slot";
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
    courses.value = await callApi("get_courses");
    selectedCode.value = courses.value[0]?.code || "";
    setNotice(`${courses.value.length} course(s) ready.`, "success");
  } catch (error) {
    setNotice(error.message, "error");
  }
}

async function saveCourses() {
  try {
    await callApi("save_courses", courses.value);
    setNotice("Course list saved.", "success");
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
  const nextCourse = {
    code,
    name,
    slots: {
      L: lecture,
      T: tutorial,
      P: practical,
    },
  };
  if (courseBeingEdited.value) Object.assign(courseBeingEdited.value, nextCourse);
  else courses.value.push(nextCourse);
  selectedCode.value = code;
  closeCourseDialog();
  await saveCourses();
}

function requestRemoveCourse(course) {
  courseBeingRemoved.value = course;
  deleteDialogOpen.value = true;
}

async function confirmRemoveCourse() {
  if (!courseBeingRemoved.value) return;
  const removedCode = courseBeingRemoved.value.code;
  courses.value = courses.value.filter((course) => course !== courseBeingRemoved.value);
  selectedCode.value = courses.value[0]?.code || "";
  deleteDialogOpen.value = false;
  courseBeingRemoved.value = null;
  setNotice(`${removedCode} was removed.`, "success");
  await saveCourses();
}

async function importFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    const content = await file.text();
    courses.value = await callApi("import_courses", file.name, content);
    selectedCode.value = courses.value[0]?.code || "";
    setNotice(`Loaded ${courses.value.length} course(s) from ${file.name}.`, "success");
  } catch (error) {
    setNotice(error.message, "error");
  } finally {
    event.target.value = "";
  }
}

async function startRun() {
  if (!credentials.studentId || !credentials.password) {
    setNotice("Enter your student ID and password first.", "error");
    return;
  }
  if (!courses.value.length) {
    setNotice("Add or import at least one course first.", "error");
    return;
  }
  try {
    await callApi("start", credentials.studentId, credentials.password, options.method, options.headless);
    setNotice("Login started. You can watch each course below.", "info");
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
          <label v-if="options.method === 'Playwright'" class="toggle-label"><span>Browser visible</span><input v-model="options.headless" type="checkbox" /><span class="toggle"></span></label>
        </div>
        <button class="primary-action" :disabled="status.running" @click="startRun">{{ status.running ? "Registration in progress" : "Start registration" }}</button>
        <button v-if="status.running" class="quiet-action danger" @click="stopRun">Stop safely</button>
        <p class="helper">Your credentials stay in the local application settings. They are not sent to a separate web server.</p>
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
                <td><span class="row-status" :class="status.results[course.code]?.status || 'ready'">{{ status.results[course.code]?.label || "Ready" }}</span></td>
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

    <section class="panel progress-panel">
      <div class="panel-heading progress-heading">
        <div><p class="section-kicker">03 / LIVE OUTCOME</p><h2>Registration progress</h2></div>
        <div class="progress-summary"><strong>{{ successCount }}</strong><span>successful</span><strong class="failed-number">{{ failedCount }}</strong><span>needs attention</span></div>
      </div>
      <div class="progress-track"><span :style="{ width: `${status.total ? (status.completed / status.total) * 100 : 0}%` }"></span></div>
      <p class="current-message">{{ status.message }}</p>
      <div class="notice" :class="notice.type">{{ notice.text }}</div>
    </section>
    <transition name="toast"><div v-if="toast" class="toast" :class="toast.type" role="status">{{ toast.text }}</div></transition>
  </main>
</template>
