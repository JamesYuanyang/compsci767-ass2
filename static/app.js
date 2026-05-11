let currentSession = null;
let memoryCache = [];

const goalForm = document.querySelector("#goal-form");
const feedbackForm = document.querySelector("#feedback-form");
const refreshMemory = document.querySelector("#refresh-memory");
const taskList = document.querySelector("#task-list");
const statusMessage = document.querySelector("#status-message");
const goalInput = document.querySelector("#goal");
const goalLabel = document.querySelector("#goal-label");
const modeButtons = document.querySelectorAll("[data-input-mode]");

const inputModes = {
  brief: {
    label: "Assignment Brief or Rubric",
    text: `Assignment 2 requirements:
Build a personal task planning agent with a working web interface and API.
The agent should perceive the user's goal, deadline, available hours, and feedback.
It should decide a plan, generate ordered tasks, store memory, and apply safety checks.
Submit the GitHub repository, README, short report, screenshots, and demo video.`,
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
  const payload = {
    goal: goalInput.value,
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

  await runAction("Updating plan...", async () => {
    const session = await request("/api/feedback", {
      method: "POST",
      body: JSON.stringify({ session_id: currentSession.session_id, feedback }),
    });
    document.querySelector("#feedback").value = "";
    renderSession(session);
    await loadMemory();
  });
});

refreshMemory.addEventListener("click", () => runAction("Refreshing memory...", loadMemory));

modeButtons.forEach((button) => {
  button.addEventListener("click", () => setInputMode(button.dataset.inputMode));
});

taskList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-task-id][data-status]");
  if (!button || !currentSession) return;
  await runAction("Updating task...", async () => {
    const session = await request(`/api/sessions/${currentSession.session_id}/tasks/${button.dataset.taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ status: button.dataset.status }),
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
  document.querySelector("#goal-state").textContent = summarizeGoal(session);
  document.querySelector("#time-budget").textContent = `${formatHours(session.safety.total_estimated_hours)} planned`;
  document.querySelector("#safety-state").textContent =
    session.safety.warnings.length === 0 ? "No warnings" : `${session.safety.warnings.length} warning(s)`;
  document.querySelector("#session-id").textContent = `Session ${session.session_id.slice(0, 8)}`;

  renderSafety(session.safety);
  renderTasks(session.tasks);
  renderLog(session.agent_log);
  renderPerception(session.perception);
}

function renderSafety(safety) {
  const list = document.querySelector("#safety-list");
  if (!safety.warnings.length) {
    list.innerHTML = "";
    return;
  }
  list.innerHTML = `
    <strong>Safety warnings</strong>
    <ul>
      ${safety.messages.map((message) => `<li>${escapeHtml(message)}</li>`).join("")}
    </ul>
  `;
}

function renderTasks(tasks) {
  taskList.className = "task-list";
  taskList.innerHTML = tasks
    .map(
      (task) => `
        <article class="task-card ${task.status}">
          <div class="task-main">
            <span class="task-order">${escapeHtml(task.order)}</span>
            <div>
              <h3>${escapeHtml(task.title)}</h3>
              <p>${escapeHtml(task.support_hint)}</p>
              <div class="task-meta">
                <span>${escapeHtml(task.schedule)}</span>
                <span>${formatHours(task.effort_hours)}</span>
                <span>${escapeHtml(priorityLabel(task.priority_score))}</span>
              </div>
            </div>
          </div>
          <div class="status-tabs" aria-label="Task status">
            ${statusButton(task, "todo", "Todo")}
            ${statusButton(task, "doing", "Doing")}
            ${statusButton(task, "done", "Done")}
            ${statusButton(task, "blocked", "Blocked")}
          </div>
        </article>
      `
    )
    .join("");
}

function statusButton(task, status, label) {
  const active = task.status === status ? "active" : "";
  return `<button class="${active}" type="button" data-task-id="${escapeHtml(task.id)}" data-status="${status}">${label}</button>`;
}

function renderLog(log) {
  const list = document.querySelector("#agent-log");
  list.innerHTML = log.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
}

function renderPerception(perception) {
  const facts = document.querySelector("#perception");
  const deliverables = perception.deliverables ? perception.deliverables.join(", ") : "None";
  facts.innerHTML = [
    ["Input", perception.input_type || "goal_description"],
    ["Domain", perception.domain],
    ["Keywords", perception.keywords.join(", ") || "None"],
    ["Deliverables", deliverables],
    ["Deadline pressure", perception.deadline_pressure || (perception.deadline_detected ? "Detected" : "Missing")],
    ["Hours remaining", formatOptionalHours(perception.deadline_hours_remaining)],
    ["Available time", `${formatHours(perception.time_budget)}`],
    ["Recommended time", `${formatHours(perception.recommended_hours || perception.time_budget)}`],
    ["Complexity", perception.complexity || "Unknown"],
    ["Constraints", perception.constraints.join(", ") || "None"],
  ]
    .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`)
    .join("");
}

async function loadMemory() {
  const memory = await request("/api/memory");
  memoryCache = memory.sessions;
  const list = document.querySelector("#memory-list");
  if (memoryCache.length === 0) {
    list.innerHTML = `<p class="muted">No stored sessions.</p>`;
    return;
  }
  list.innerHTML = memoryCache
    .slice(0, 5)
    .map((session, index) => memoryItem(session, index))
    .join("");
}

function memoryItem(session, index) {
  return `
    <button class="memory-item" type="button" data-memory-index="${index}">
      <strong>${escapeHtml(compactText(session.goal, 90))}</strong>
      <span>${escapeHtml(session.tasks.length)} tasks - ${escapeHtml(session.created_at.slice(0, 10))}</span>
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
  if (session.perception && session.perception.input_type === "assignment_brief") {
    return `Copied assignment brief - ${compactText(session.goal, 130)}`;
  }
  return compactText(session.goal, 170);
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

function formatHours(value) {
  return `${Number(value).toFixed(1).replace(/\.0$/, "")}h`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

setInputMode("brief");
setDefaultDeadline();
loadMemory();
