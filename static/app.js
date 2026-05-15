let currentSession = null;
let memoryCache = [];
let focusTimerId = null;

const goalForm = document.querySelector("#goal-form");
const feedbackForm = document.querySelector("#feedback-form");
const refreshMemory = document.querySelector("#refresh-memory");
const taskList = document.querySelector("#task-list");
const statusMessage = document.querySelector("#status-message");
const goalInput = document.querySelector("#goal");
const goalLabel = document.querySelector("#goal-label");
const modeButtons = document.querySelectorAll("[data-input-mode]");
const restButton = document.querySelector("#rest-button");
const focusPanel = document.querySelector("#focus-panel");
const focusBack = document.querySelector("#focus-back");
const focusDone = document.querySelector("#focus-done");
const focusPause = document.querySelector("#focus-pause");
const focusResume = document.querySelector("#focus-resume");

const inputModes = {
  brief: {
    label: "Assignment Brief or Rubric",
    text: `Build an intelligent software agent prototype.
Report: 2 pages.
Page 1 should include GitHub repo link, system design diagram and explanation.
Page 2 should include screenshots and explanations of how the system works.
GitHub repo should include README.md with reproduction instructions, a 2-minute demo video link, and commit checkpoints.`,
    placeholder: "Paste the assignment brief, rubric, or submission instructions",
  },
  goal: {
    label: "Goal Description",
    text: "Complete COMPSCI 767 assignment 2 with a GitHub repository, README, report, and demo video",
    placeholder: "Describe the goal in your own words",
  },
};

goalForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const goal = goalInput.value;
  const payload = {
    goal,
    goal_or_brief: goal,
    deadline: document.querySelector("#deadline").value || null,
    available_hours: Number(document.querySelector("#hours").value),
    priority: document.querySelector("#priority").value,
  };

  await runAction("Generating plan...", async () => {
    const session = await request("/api/plan", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderSession(session);
    await loadMemory();
  });
});

feedbackForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentSession) {
    showStatus("Generate a plan first.");
    return;
  }

  const feedback = document.querySelector("#feedback").value.trim();
  if (!feedback) return;

  await runAction("Applying feedback...", async () => {
    const session = await request("/api/feedback", {
      method: "POST",
      body: JSON.stringify({
        session_id: currentSession.session_id,
        feedback,
        available_hours: Number(document.querySelector("#hours").value),
      }),
    });
    document.querySelector("#feedback").value = "";
    document.querySelector("#hours").value = session.available_hours || session.perception?.time_budget || document.querySelector("#hours").value;
    renderSession(session);
    await loadMemory();
  });
});

refreshMemory.addEventListener("click", () => runAction("Refreshing memory...", loadMemory));

modeButtons.forEach((button) => {
  button.addEventListener("click", () => setInputMode(button.dataset.inputMode));
});

taskList.addEventListener("change", async (event) => {
  const select = event.target.closest("[data-task-id]");
  if (!select || !currentSession) return;
  await runAction("Updating task...", async () => {
    const session = await request(`/api/sessions/${currentSession.session_id}/tasks/${select.dataset.taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ status: select.value }),
    });
    renderSession(session);
    await loadMemory();
  });
});

taskList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-focus-task-id]");
  if (!button || !currentSession) return;
  const taskId = button.dataset.focusTaskId;
  const focus = currentSession.focus_state || {};

  if (focus.active_task_id === taskId && ["running", "paused"].includes(focus.status)) {
    renderFocusState(currentSession);
    return;
  }

  await runAction("Opening timer...", async () => {
    const session = await request(`/api/sessions/${currentSession.session_id}/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ status: "doing" }),
    });
    renderSession(session);
    await loadMemory();
  });
});

document.querySelector("#memory-list").addEventListener("click", (event) => {
  const item = event.target.closest("[data-memory-index]");
  if (!item) return;
  const session = memoryCache[Number(item.dataset.memoryIndex)];
  if (session) renderSession(session);
});

restButton.addEventListener("click", () => pauseCurrentSession());
focusPause.addEventListener("click", () => pauseCurrentSession());

focusBack.addEventListener("click", () => {
  showPlanView();
});

focusDone.addEventListener("click", async () => {
  const task = activeFocusTask();
  if (!task || !currentSession) return;
  await runAction("Completing focused task...", async () => {
    const session = await request(`/api/sessions/${currentSession.session_id}/tasks/${task.id}`, {
      method: "PATCH",
      body: JSON.stringify({ status: "done" }),
    });
    renderSession(session);
    showPlanView();
    await loadMemory();
  });
});

focusResume.addEventListener("click", async () => {
  if (!currentSession) return;
  await runAction("Resuming timer...", async () => {
    const session = await request(`/api/sessions/${currentSession.session_id}/focus/resume`, {
      method: "POST",
    });
    renderSession(session);
    await loadMemory();
  });
});

async function runAction(message, action) {
  showStatus(message);
  try {
    await action();
    showStatus("");
  } catch (error) {
    showStatus(error.message || "Something went wrong.");
  }
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message);
  }
  return response.json();
}

function renderSession(session) {
  currentSession = session;
  syncComposerFromSession(session);
  const safety = normalizedSafety(session);
  const progress = progressForSession(session);

  document.querySelector("#goal-state").textContent = summarizeGoal(session);
  document.querySelector("#time-budget").textContent =
    `${formatHours(safety.planned_hours)} planned / ${formatHours(safety.recommended_effort_hours)} recommended`;
  document.querySelector("#safety-state").textContent =
    safety.warnings.length === 0 ? "No warnings" : `${safety.warnings.length} warning(s)`;
  document.querySelector("#session-id").textContent = `Session ${session.session_id.slice(0, 8)}`;

  renderSafety(safety);
  renderProgress(progress);
  renderTasks(session.tasks || []);
  renderTrace(session.agent_trace, session.agent_log);
  renderPerception(session.perception || {});
  renderMemorySummary(session.memory_summary);
  restButton.hidden = false;
  renderFocusState(session);
}

function syncComposerFromSession(session) {
  if (session.goal) {
    goalInput.value = session.goal;
  }
  const deadlineInput = document.querySelector("#deadline");
  if (session.deadline && session.deadline !== "Not specified") {
    deadlineInput.value = String(session.deadline).slice(0, 10);
  } else {
    deadlineInput.value = "";
  }
  document.querySelector("#hours").value = session.available_hours || session.perception?.time_budget || document.querySelector("#hours").value;
  const priority = session.priority || session.perception?.urgency;
  if (["low", "medium", "high"].includes(priority)) {
    document.querySelector("#priority").value = priority;
  }
}

function renderFocusState(session) {
  const focus = session.focus_state || {};
  const task = activeFocusTask();
  stopFocusTimer();

  if (!task || !["running", "paused"].includes(focus.status)) {
    showPlanView();
    return;
  }

  document.querySelector("#focus-session").textContent = `Session ${session.session_id.slice(0, 8)}`;
  document.querySelector("#focus-title").textContent = task.title;
  document.querySelector("#focus-hint").textContent = task.support_hint || "";
  document.querySelector("#focus-planned").textContent = formatHours(task.effort_hours);
  document.querySelector("#focus-priority").textContent = priorityLabel(task.priority_score);
  document.querySelector("#focus-schedule").textContent = task.schedule || "-";
  document.querySelector("#focus-state").textContent = focus.status === "running" ? "Timer running" : "Paused and saved";
  focusResume.hidden = focus.status !== "paused";
  focusPause.hidden = focus.status === "paused";
  document.querySelector("#focus-note").textContent =
    focus.status === "paused"
      ? "Your progress is saved. Use Resume Timer to continue from the saved time, or stop the local service and reload later."
      : "Work on the focused task. Mark Done when finished, or Pause / Rest to save your place.";
  updateFocusTimer();
  if (focus.status === "running") {
    focusTimerId = window.setInterval(updateFocusTimer, 1000);
  }
  showFocusView();
}

function showFocusView() {
  document.querySelector(".plan-panel").hidden = true;
  focusPanel.hidden = false;
}

function showPlanView() {
  stopFocusTimer();
  document.querySelector(".plan-panel").hidden = false;
  focusPanel.hidden = true;
}

function stopFocusTimer() {
  if (focusTimerId) {
    window.clearInterval(focusTimerId);
    focusTimerId = null;
  }
}

function updateFocusTimer() {
  const focus = currentSession?.focus_state || {};
  document.querySelector("#focus-timer").textContent = formatDuration(focusElapsedSeconds(focus));
}

function focusElapsedSeconds(focus) {
  let elapsed = Number(focus.elapsed_seconds || 0);
  if (focus.status === "running" && focus.active_started_at) {
    const startedAt = new Date(focus.active_started_at).getTime();
    if (!Number.isNaN(startedAt)) {
      elapsed += Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
    }
  }
  return elapsed;
}

function activeFocusTask() {
  const taskId = currentSession?.focus_state?.active_task_id;
  if (!taskId) return null;
  return (currentSession.tasks || []).find((task) => task.id === taskId) || null;
}

async function pauseCurrentSession() {
  if (!currentSession) {
    showStatus("Generate or load a plan first.");
    return;
  }
  await runAction("Saving pause state...", async () => {
    const session = await request(`/api/sessions/${currentSession.session_id}/pause`, {
      method: "POST",
    });
    renderSession(session);
    await loadMemory();
    showStatus("Pause saved. You can stop the local service and resume later.");
  });
}

function renderSafety(safety) {
  const list = document.querySelector("#safety-list");
  const messages = safety.messages || [];
  list.classList.toggle("ok", safety.warnings.length === 0);
  if (!messages.length && !safety.warnings.length) {
    list.innerHTML = "";
    return;
  }
  list.innerHTML = `
    <strong>${safety.warnings.length ? "Safety warnings" : "Safety check"}</strong>
    <ul>
      ${messages.map((message) => `<li>${escapeHtml(message)}</li>`).join("")}
    </ul>
  `;
}

function renderProgress(progress) {
  const panel = document.querySelector("#progress-panel");
  panel.hidden = false;
  document.querySelector("#progress-text").textContent =
    `Progress: ${progress.completed_tasks} / ${progress.total_tasks} tasks completed`;
  document.querySelector("#remaining-time").textContent =
    `Remaining planned time: ${formatHours(progress.remaining_planned_hours)}`;
  document.querySelector("#completed-time").textContent =
    `Completed time: ${formatHours(progress.completed_hours)}`;
  document.querySelector("#progress-bar").style.width = `${Math.max(0, Math.min(100, progress.percent_complete || 0))}%`;
}

function renderTasks(tasks) {
  if (!tasks.length) {
    taskList.className = "task-list empty";
    taskList.textContent = "No tasks yet.";
    return;
  }
  taskList.className = "task-list";
  taskList.innerHTML = tasks
    .map(
      (task) => `
        <article class="task-card ${escapeHtml(task.status)} ${task.deferred ? "deferred" : ""}">
          <div class="task-main">
            <span class="task-order">${escapeHtml(task.order)}</span>
            <div>
              <h3>${escapeHtml(task.title)}</h3>
              <p>${escapeHtml(task.support_hint)}</p>
              <div class="task-meta">
                <span>${escapeHtml(task.schedule)}</span>
                <span>${formatHours(task.effort_hours)}</span>
                <span>${escapeHtml(priorityLabel(task.priority_score))}</span>
                ${task.deferred ? "<span>Deferred</span>" : ""}
              </div>
            </div>
          </div>
          <label class="status-select-label">
            <span>Status</span>
            ${statusSelect(task)}
            ${timerButton(task)}
          </label>
        </article>
      `
    )
    .join("");
}

function timerButton(task) {
  if (task.status !== "doing") return "";
  return `<button class="open-timer" type="button" data-focus-task-id="${escapeHtml(task.id)}">Open Timer</button>`;
}

function statusSelect(task) {
  const options = [
    ["todo", "Todo"],
    ["doing", "Doing"],
    ["done", "Done"],
    ["blocked", "Blocked"],
  ];
  return `
    <select class="status-select" data-task-id="${escapeHtml(task.id)}" aria-label="Task status">
      ${options
        .map(([value, label]) => `<option value="${value}" ${task.status === value ? "selected" : ""}>${label}</option>`)
        .join("")}
    </select>
  `;
}

function renderTrace(trace, fallbackLog = []) {
  const container = document.querySelector("#agent-trace");
  if (!trace) {
    container.innerHTML = `<ol class="log-list">${(fallbackLog || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol>`;
    return;
  }
  const sections = [
    ["perception", "Perception"],
    ["decision", "Decision"],
    ["action", "Action"],
    ["memory", "Memory"],
    ["safety_check", "Safety Check"],
  ];
  container.innerHTML = sections
    .map(([key, title]) => {
      const items = trace[key] || [];
      return `
        <section class="trace-section">
          <h3>${title}</h3>
          <ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
        </section>
      `;
    })
    .join("");
}

function renderPerception(perception) {
  const facts = document.querySelector("#perception");
  const deliverables = perception.deliverables ? perception.deliverables.join(", ") : "None";
  const methods = perception.methods ? perception.methods.join(", ") : "None";
  facts.innerHTML = [
    ["Input", perception.input_type || "goal_description"],
    ["Source", perception.analysis_source || "rules"],
    ["Domain", perception.domain || "unknown"],
    ["Keywords", (perception.keywords || []).join(", ") || "None"],
    ["Deliverables", deliverables],
    ["Key requirements", methods],
    ["Deadline pressure", perception.deadline_pressure || (perception.deadline_detected ? "Detected" : "Missing")],
    ["Time until deadline", formatOptionalHours(perception.time_until_deadline_hours ?? perception.deadline_hours_remaining)],
    ["Available working hours", `${formatHours(perception.available_working_hours ?? perception.time_budget ?? 0)}`],
    ["Recommended effort", `${formatHours(perception.recommended_effort_hours ?? perception.recommended_hours ?? perception.time_budget ?? 0)}`],
    ["Complexity", perception.complexity || "Unknown"],
    ["Constraints", (perception.constraints || []).join(", ") || "None"],
  ]
    .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`)
    .join("");
}

async function loadMemory() {
  const memory = await request("/api/plans");
  memoryCache = memory.sessions || [];
  renderMemorySummary(memory.summary);
  const list = document.querySelector("#memory-list");
  if (memoryCache.length === 0) {
    list.innerHTML = `<p class="muted">No stored sessions.</p>`;
    return;
  }
  list.innerHTML = memoryCache
    .slice(0, 6)
    .map((session, index) => memoryItem(session, index))
    .join("");
}

async function loadResumeSession() {
  try {
    const session = await request("/api/resume");
    renderSession(session);
    const focus = session.focus_state || {};
    const pressure = session.perception?.deadline_pressure || "unknown";
    if (focus.status === "paused" && focus.active_task_id) {
      showStatus(`Restored paused task. Deadline pressure is ${pressure}.`);
    } else {
      showStatus(`Restored latest plan. Deadline pressure is ${pressure}.`);
    }
  } catch (error) {
    if (!String(error.message || "").includes("404")) {
      showStatus(error.message || "Could not restore previous plan.");
    }
  }
}

function renderMemorySummary(summary) {
  const target = document.querySelector("#memory-summary");
  if (!target) return;
  const stored = summary?.stored_plans ?? memoryCache.length;
  const current = summary?.current_session || currentSession?.session_id || null;
  const lastSaved = summary?.last_saved || currentSession?.updated_at || currentSession?.created_at || null;
  target.innerHTML = `
    <span>Stored plans: ${escapeHtml(stored)}</span>
    <span>Current session: ${escapeHtml(current ? current.slice(0, 8) : "-")}</span>
    <span>Last saved: ${escapeHtml(lastSaved ? formatDateTime(lastSaved) : "-")}</span>
  `;
}

function memoryItem(session, index) {
  const title = session.short_title || buildMemoryTitle(session);
  const date = formatDateTime(session.updated_at || session.created_at);
  const planned = session.planned_hours ?? session.safety?.planned_hours ?? session.safety?.total_estimated_hours ?? 0;
  const event = session.event_type === "updated" ? "Updated" : "Generated";
  return `
    <button class="memory-item" type="button" data-memory-index="${index}">
      <strong>${escapeHtml(title)}</strong>
      <span>${escapeHtml(date)} - ${escapeHtml(session.tasks?.length || 0)} tasks - ${formatHours(planned)} - ${event}</span>
    </button>
  `;
}

function setInputMode(mode) {
  const selected = inputModes[mode] || inputModes.brief;
  modeButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.inputMode === mode);
  });
  goalLabel.textContent = selected.label;
  goalInput.placeholder = selected.placeholder;
  goalInput.value = selected.text;
  goalInput.classList.toggle("brief-textarea", mode === "brief");
}

function setDefaultDeadline() {
  const deadline = new Date();
  deadline.setDate(deadline.getDate() + 7);
  document.querySelector("#deadline").value = deadline.toISOString().slice(0, 10);
}

function summarizeGoal(session) {
  if (session.short_title) {
    return session.short_title;
  }
  if (session.perception && session.perception.input_type === "assignment_brief") {
    return `Assignment brief - ${compactText(session.goal, 110)}`;
  }
  return compactText(session.goal, 150);
}

function buildMemoryTitle(session) {
  if (session.perception?.input_type === "assignment_brief") {
    return `Assignment 2 ${session.event_type === "updated" ? "Updated Plan" : "Plan"} - ${formatHours(session.planned_hours ?? session.available_hours ?? 0)}`;
  }
  return `${compactText(session.goal, 42)} - ${session.tasks?.length || 0} tasks`;
}

function normalizedSafety(session) {
  const safety = session.safety || {};
  return {
    planned_hours: safety.planned_hours ?? safety.total_estimated_hours ?? session.planned_hours ?? 0,
    recommended_effort_hours: safety.recommended_effort_hours ?? safety.recommended_hours ?? session.recommended_effort_hours ?? 0,
    warnings: safety.warnings || session.safety_warnings || [],
    messages: safety.messages || [],
  };
}

function progressForSession(session) {
  if (session.progress) return session.progress;
  const tasks = session.tasks || [];
  const completed = tasks.filter((task) => task.status === "done");
  return {
    completed_tasks: completed.length,
    total_tasks: tasks.length,
    completed_hours: completed.reduce((sum, task) => sum + Number(task.effort_hours || 0), 0),
    remaining_planned_hours: tasks
      .filter((task) => task.status !== "done")
      .reduce((sum, task) => sum + Number(task.effort_hours || 0), 0),
    percent_complete: tasks.length ? Math.round((completed.length / tasks.length) * 100) : 0,
  };
}

function priorityLabel(score) {
  if (score >= 8) return "Priority: Critical";
  if (score >= 6) return "Priority: High";
  if (score >= 4) return "Priority: Medium";
  return "Priority: Low";
}

function formatOptionalHours(value) {
  return value === null || value === undefined ? "Unknown" : formatHours(value);
}

function compactText(value, limit) {
  const text = String(value).replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit - 3)}...` : text;
}

function showStatus(message) {
  statusMessage.textContent = message;
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
  return date.toLocaleString([], {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatHours(value) {
  return `${Number(value || 0).toFixed(1).replace(/\.0$/, "")}h`;
}

function formatDuration(value) {
  const total = Math.max(0, Math.floor(Number(value || 0)));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return [hours, minutes, seconds].map((part) => String(part).padStart(2, "0")).join(":");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function initialize() {
  setInputMode("brief");
  setDefaultDeadline();
  await loadMemory();
  await loadResumeSession();
}

initialize();
