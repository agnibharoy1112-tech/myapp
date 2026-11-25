const customerView = document.querySelector("#customer-view");
const staffView = document.querySelector("#staff-view");
const loginForm = document.querySelector("#login-form");
const logoutButton = document.querySelector("#logout-button");
const applicationList = document.querySelector("#application-list");
let currentStaff = null;

const roleLabels = {
  coordinator: "Loan Coordinator",
  approver_level_1: "Loan Approval Level 1",
  approver_level_2: "Loan Approval Level 2",
  finance: "Finance - Fund Disbursement",
  admin: "Admin",
};

const statusLabels = {
  coordinator_review: "Coordinator review",
  level_1_review: "Level 1 review",
  level_2_review: "Level 2 review",
  finance_pending: "Awaiting disbursement",
  funded: "Funded",
  rejected: "Rejected",
};

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.detail || "The request could not be completed.");
  }
  return body;
}

function showMessage(element, message, isError = false) {
  element.textContent = message;
  element.classList.toggle("error", isError);
}

function setStaffView(staff) {
  currentStaff = staff;
  customerView.classList.add("hidden");
  staffView.classList.remove("hidden");
  logoutButton.classList.remove("hidden");
  document.querySelector("#staff-identity").textContent =
    `${staff.username} · ${roleLabels[staff.role] || staff.role}`;
  document.querySelector("#staff-tools").classList.toggle("hidden", staff.role !== "admin");
  loadApplications();
}

function actionButton(application, action, label, style = "") {
  return `<button class="button ${style}" data-application="${escapeHtml(application.id)}" data-action="${action}">${label}</button>`;
}

function renderApplication(application) {
  const actions = [];
  if (currentStaff.role === "coordinator" && application.status === "coordinator_review") {
    actions.push(actionButton(application, "forward", "Forward to Level 1", "button-secondary"));
    actions.push(actionButton(application, "reject", "Reject", "button-danger"));
  } else if (currentStaff.role === "approver_level_1" && application.status === "level_1_review") {
    actions.push(actionButton(application, "approve", "Approve", "button-primary"));
    actions.push(actionButton(application, "reject", "Reject", "button-danger"));
  } else if (currentStaff.role === "approver_level_2" && application.status === "level_2_review") {
    actions.push(actionButton(application, "approve", "Approve", "button-primary"));
    actions.push(actionButton(application, "reject", "Reject", "button-danger"));
  } else if (currentStaff.role === "finance" && application.status === "finance_pending") {
    actions.push(actionButton(application, "disburse", "Mark funds disbursed", "button-primary"));
  }
  const events = application.events.map((event) => `
    <li><span>${escapeHtml(event.actor)} · ${escapeHtml(event.action.replaceAll("_", " "))}</span>
      <time>${escapeHtml(new Date(event.created_at).toLocaleString())}</time>
      ${event.note ? `<p>${escapeHtml(event.note)}</p>` : ""}
    </li>`).join("");
  return `
    <article class="application-card">
      <div class="application-header">
        <div><p class="eyebrow">Application ${escapeHtml(application.id.slice(0, 8))}</p>
          <h2>${escapeHtml(application.applicant_name)}</h2></div>
        <span class="status status-${escapeHtml(application.status)}">${escapeHtml(statusLabels[application.status] || application.status)}</span>
      </div>
      <dl class="details">
        <div><dt>Requested</dt><dd>$${Number(application.amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</dd></div>
        <div><dt>Email</dt><dd>${escapeHtml(application.email)}</dd></div>
        <div><dt>Submitted</dt><dd>${escapeHtml(new Date(application.created_at).toLocaleString())}</dd></div>
      </dl>
      <p class="purpose">${escapeHtml(application.purpose)}</p>
      ${actions.length ? `<div class="actions">${actions.join("")}</div>` : ""}
      <details><summary>Activity history</summary><ol class="event-list">${events}</ol></details>
    </article>`;
}

async function loadApplications() {
  try {
    const applications = await api("/api/applications");
    applicationList.innerHTML = applications.length
      ? applications.map(renderApplication).join("")
      : '<div class="panel empty-state">No applications have been submitted yet.</div>';
  } catch (error) {
    applicationList.innerHTML = `<p class="message error">${escapeHtml(error.message)}</p>`;
  }
}

document.querySelector("#application-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const message = document.querySelector("#application-message");
  const values = Object.fromEntries(new FormData(form));
  values.amount = Number(values.amount);
  try {
    const result = await api("/api/applications", { method: "POST", body: JSON.stringify(values) });
    showMessage(message, `${result.message} Your tracking code is ${result.tracking_code}`);
    form.reset();
  } catch (error) {
    showMessage(message, error.message, true);
  }
});

document.querySelector("#tracking-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const trackingCode = new FormData(event.currentTarget).get("tracking_code");
  const resultElement = document.querySelector("#tracking-result");
  try {
    const result = await api(`/api/track/${encodeURIComponent(trackingCode)}`);
    resultElement.innerHTML = `<div class="tracking-card"><strong>${escapeHtml(statusLabels[result.status] || result.status)}</strong>
      <p>${escapeHtml(result.applicant_name)} · $${Number(result.amount).toLocaleString()}</p>
      <small>Last updated ${escapeHtml(new Date(result.updated_at).toLocaleString())}</small></div>`;
  } catch (error) {
    showMessage(resultElement, error.message, true);
  }
});

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = document.querySelector("#login-message");
  const values = Object.fromEntries(new FormData(loginForm));
  try {
    const staff = await api("/api/login", { method: "POST", body: JSON.stringify(values) });
    showMessage(message, "");
    setStaffView(staff);
  } catch (error) {
    showMessage(message, error.message, true);
  }
});

logoutButton.addEventListener("click", async () => {
  try {
    await api("/api/logout", { method: "POST" });
    currentStaff = null;
    staffView.classList.add("hidden");
    customerView.classList.remove("hidden");
    logoutButton.classList.add("hidden");
    applicationList.replaceChildren();
  } catch (error) {
    window.alert(error.message);
  }
});

applicationList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-application]");
  if (!button) return;
  let note = "";
  if (button.dataset.action === "reject") {
    note = window.prompt("Enter the reason for rejection:") || "";
    if (!note.trim()) return;
  }
  button.disabled = true;
  try {
    await api(`/api/applications/${button.dataset.application}/actions`, {
      method: "POST",
      body: JSON.stringify({ action: button.dataset.action, note }),
    });
    await loadApplications();
  } catch (error) {
    window.alert(error.message);
    button.disabled = false;
  }
});

document.querySelector("#staff-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form));
  const message = document.querySelector("#staff-message");
  try {
    const created = await api("/api/staff", { method: "POST", body: JSON.stringify(values) });
    showMessage(message, `Created ${created.username} as ${roleLabels[created.role]}.`);
    form.reset();
  } catch (error) {
    showMessage(message, error.message, true);
  }
});

api("/api/me")
  .then(setStaffView)
  .catch(() => {});
