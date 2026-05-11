let currentSession = null;
let memoryCache = [];

const goalForm = document.querySelector("#goal-form");
const feedbackForm = document.querySelector("#feedback-form");
const refreshMemory = document.querySelector("#refresh-memory");

goalForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    goal: document.querySelector("#goal").value,
    deadline: document.querySelector("#deadline").value,
    available_hours: Number(document.querySelector("#hours").value),
    priority: document.querySelector("#priority").value,
  };
  const session = await request("/api/plan", { method: "POST", body: JSON.stringify(payload) });
  renderSession(session);
  loadMemory();
});

feedbackForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentSession) return;
  const feedback = document.querySelector("#feedback").value.trim();
  if (!feedback) return;
  const session = await request("/api/feedback", {
    method: "POST",
    body: JSON.stringify({ session_id: currentSession.session_id, feedback }),
  });
  document.querySelector("#feedback").value = "";
  renderSession(session);
  loadMemory();
});

refreshMemory.addEventListener("click", loadMemory);

async function updateTask(taskId, status) {
  if (!currentSession) return;
  const session = await request(`/api/sessions/${currentSession.session_id}/tasks/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
  renderSession(session);
  loadMemory();
}

async function request(url, options = {}) {
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function renderSession(session) {
  currentSession = session;
  document.querySelector("#goal-state").textContent = session.goal;
  document.querySelector("#time-budget").textContent = `${session.available_hours} hours`;
  document.querySelector("#safety-state").textContent = session.safety.warnings.length === 0 ? "No warnings" : `${session.safety.warnings.length} warning(s)`;
  document.querySelector("#session-id").textContent = `Session ${session.session_id.slice(0, 8)}`;
  renderTasks(session.tasks);
  renderLog(session.agent_log);
  renderPerception(session.perception);
}

function renderTasks(tasks) {
  const list = document.querySelector("#task-list");
  list.className = "task-list";
  list.innerHTML = tasks.map((task) => `
    <article class="task-card ${task.status}">
      <div class="task-header"><h3 class="task-title">${escapeHtml(task.order)}. ${escapeHtml(task.title)}</h3><span class="pill">${escapeHtml(task.status)}</span></div>
      <div class="meta"><span class="pill">${escapeHtml(task.schedule)}</span><span class="pill">${escapeHtml(task.effort_hours)}h</span><span class="pill">Priority ${escapeHtml(task.priority_score)}</span></div>
      <p class="hint">${escapeHtml(task.support_hint)}</p>
      <div class="task-actions">
        ${statusButton(task, "todo", "Todo")}
        ${statusButton(task, "doing", "Doing")}
        ${statusButton(task, "done", "Done")}
        ${statusButton(task, "blocked", "Blocked")}
      </div>
    </article>`).join("");
}

function statusButton(task, status, label) {
  const active = task.status === status ? "active" : "";
  return `<button class="${active}" type="button" onclick="updateTask('${task.id}', '${status}')">${label}</button>`;
}

function renderLog(log) {
  document.querySelector("#agent-log").innerHTML = log.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
}

function renderPerception(perception) {
  document.querySelector("#perception").innerHTML = [
    ["Domain", perception.domain],
    ["Keywords", perception.keywords.join(", ") || "None"],
    ["Deadline", perception.deadline_detected ? "Detected" : "Missing"],
    ["Time", `${perception.time_budget} hours`],
    ["Urgency", perception.urgency],
    ["Constraints", perception.constraints.join(", ") || "None"],
  ].map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`).join("");
}

async function loadMemory() {
  const memory = await request("/api/memory");
  memoryCache = memory.sessions;
  const list = document.querySelector("#memory-list");
  if (memoryCache.length === 0) {
    list.innerHTML = `<p class="hint">No stored sessions yet.</p>`;
    return;
  }
  list.innerHTML = memoryCache.slice(0, 6).map((session, index) => `
    <article class="memory-item" data-memory-index="${index}">
      <strong>${escapeHtml(session.goal)}</strong>
      <span>${escapeHtml(session.tasks.length)} tasks - ${escapeHtml(session.created_at.slice(0, 10))}</span>
    </article>`).join("");
}

document.querySelector("#memory-list").addEventListener("click", (event) => {
  const item = event.target.closest("[data-memory-index]");
  if (!item) return;
  const session = memoryCache[Number(item.dataset.memoryIndex)];
  if (session) renderSession(session);
});

function escapeHtml(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

loadMemory();
