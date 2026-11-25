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

const stages = [
  ["coordinator_review", "Coordinator"],
  ["level_1_review", "Level 1"],
  ["level_2_review", "Level 2"],
  ["finance_pending", "Finance"],
  ["funded", "Funded"],
];

const decisionReasons = {
  approve: {
    creditworthiness_confirmed: "Creditworthiness confirmed",
    affordability_confirmed: "Repayment affordability confirmed",
    documents_verified: "Required documents verified",
    policy_eligible: "Meets lending policy",
    other: "Other",
  },
  reject: {
    insufficient_credit_history: "Insufficient credit history",
    repayment_unaffordable: "Repayment is unaffordable",
    missing_or_unverified_documents: "Missing or unverified documents",
    eligibility_not_met: "Eligibility criteria not met",
    other: "Other",
  },
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

async function uploadDocuments(trackingCode, files) {
  const formData = new FormData();
  for (const file of files) formData.append("files", file);
  const response = await fetch(`/api/track/${encodeURIComponent(trackingCode)}/documents`, {
    method: "POST",
    body: formData,
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || "Document upload failed.");
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

function decisionPanel(application, actions) {
  const reasonOptions = Object.entries(decisionReasons.reject)
    .map(([value, label]) => `<option value="${value}">${label}</option>`)
    .join("");
  return `
    <div class="decision-actions">
      ${actions.map((action) => `<button class="button ${action === "reject" ? "button-danger" : "button-primary"}" type="button" data-start-decision="${action}">${action === "approve" ? "Approve" : "Reject"}</button>`).join("")}
    </div>
    <form class="decision-form hidden" data-decision-form data-application="${escapeHtml(application.id)}">
      <input type="hidden" name="action">
      <label>Decision reason
        <select name="reason_code" required>
          <option value="">Select a reason</option>
          ${reasonOptions}
        </select>
      </label>
      <label>Decision details
        <textarea name="note" required minlength="10" maxlength="2000" rows="3" placeholder="Explain the decision (at least 10 characters)"></textarea>
      </label>
      <button class="button button-secondary" type="submit">Submit decision</button>
      <button class="button button-quiet" type="button" data-cancel-decision>Cancel</button>
      <p class="message" data-decision-message aria-live="polite"></p>
    </form>`;
}

function stageSteps(application) {
  let activeIndex = stages.findIndex(([status]) => status === application.status);
  if (application.status === "rejected") {
    const rejectEvent = [...application.events].reverse().find((event) => event.action === "reject");
    activeIndex = stages.findIndex(([status]) => status === rejectEvent?.from_status);
  }
  return `<ol class="case-steps">${stages.map(([status, label], index) => {
    const state = application.status === "rejected" && index === activeIndex
      ? "rejected"
      : index < activeIndex || application.status === "funded"
        ? "complete"
        : index === activeIndex
          ? "current"
          : "upcoming";
    return `<li class="step-${state}"><span>${index + 1}</span>${label}</li>`;
  }).join("")}</ol>`;
}

function renderApplication(application) {
  const actions = [];
  if (currentStaff.role === "coordinator" && application.status === "coordinator_review") {
    actions.push(actionButton(application, "forward", "Forward to Level 1", "button-secondary"));
  }
  if (currentStaff.role === "coordinator" && application.status === "coordinator_review") {
    actions.push(decisionPanel(application, ["reject"]));
  } else if (currentStaff.role === "approver_level_1" && application.status === "level_1_review") {
    actions.push(decisionPanel(application, ["approve", "reject"]));
  } else if (currentStaff.role === "approver_level_2" && application.status === "level_2_review") {
    actions.push(decisionPanel(application, ["approve", "reject"]));
  } else if (currentStaff.role === "finance" && application.status === "finance_pending") {
    actions.push(actionButton(application, "disburse", "Mark funds disbursed", "button-primary"));
  }

  const events = application.events.map((event) => `
    <li><span>${escapeHtml(event.actor)} · ${escapeHtml(event.action.replaceAll("_", " "))}</span>
      ${event.reason_code ? `<strong>${escapeHtml(event.reason_code.replaceAll("_", " "))}</strong>` : ""}
      <time>${escapeHtml(new Date(event.created_at).toLocaleString())}</time>
      ${event.note ? `<p>${escapeHtml(event.note)}</p>` : ""}
    </li>`).join("");
  const fieldChanges = application.field_changes.map((change) => `
    <li><span>${escapeHtml(change.field_name.replaceAll("_", " "))}: ${escapeHtml(change.old_value)} → ${escapeHtml(change.new_value)}</span>
      <time>${escapeHtml(change.actor)} · ${escapeHtml(new Date(change.created_at).toLocaleString())}</time>
      <p>${escapeHtml(change.reason)}</p>
    </li>`).join("");
  const documents = application.documents.map((document) => `
    <li><a href="/api/documents/${encodeURIComponent(document.id)}">${escapeHtml(document.original_filename)}</a>
      <span>${(document.size_bytes / 1024 / 1024).toFixed(2)} MB · ${escapeHtml(new Date(document.created_at).toLocaleString())}</span>
    </li>`).join("");
  const adminEditor = currentStaff.role === "admin" ? `
    <details class="case-editor">
      <summary>Edit case fields</summary>
      <form data-edit-application="${escapeHtml(application.id)}">
        <label>Applicant name<input name="applicant_name" value="${escapeHtml(application.applicant_name)}" required minlength="2" maxlength="120"></label>
        <label>Email<input name="email" type="email" value="${escapeHtml(application.email)}" required maxlength="254"></label>
        <label>Amount (USD)<input name="amount" type="number" value="${Number(application.amount)}" min="1" max="10000000" step="0.01" required></label>
        <label>Loan type<input name="loan_type" list="loan-types" value="${escapeHtml(application.loan_type)}" required></label>
        <label>Purpose<textarea name="purpose" required minlength="10" maxlength="2000" rows="3">${escapeHtml(application.purpose)}</textarea></label>
        <label>Reason for case update<textarea name="reason" required minlength="10" maxlength="2000" rows="2"></textarea></label>
        <button class="button button-secondary" type="submit">Save audited changes</button>
        <p class="message" data-edit-message aria-live="polite"></p>
      </form>
    </details>` : "";

  return `
    <article class="application-card">
      <div class="application-header">
        <div><p class="eyebrow">Case ${escapeHtml(application.id.slice(0, 8))}</p>
          <h2>${escapeHtml(application.applicant_name)}</h2></div>
        <span class="status status-${escapeHtml(application.status)}">${escapeHtml(statusLabels[application.status] || application.status)}</span>
      </div>
      ${stageSteps(application)}
      <dl class="details">
        <div><dt>Requested</dt><dd>$${Number(application.amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</dd></div>
        <div><dt>Loan type</dt><dd>${escapeHtml(application.loan_type)}</dd></div>
        <div><dt>Email</dt><dd>${escapeHtml(application.email)}</dd></div>
        <div><dt>Submitted</dt><dd>${escapeHtml(new Date(application.created_at).toLocaleString())}</dd></div>
      </dl>
      <p class="purpose">${escapeHtml(application.purpose)}</p>
      ${documents ? `<section class="case-documents"><h3>Supporting documents</h3><ul>${documents}</ul></section>` : ""}
      ${actions.length ? `<div class="actions">${actions.join("")}</div>` : ""}
      ${adminEditor}
      <details class="case-history" open><summary>Case history and field audit</summary>
        <h3>Workflow events</h3><ol class="event-list">${events}</ol>
        ${fieldChanges ? `<h3>Field changes</h3><ol class="event-list">${fieldChanges}</ol>` : ""}
      </details>
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
  const documents = Array.from(form.elements.documents.files);
  delete values.documents;
  values.amount = Number(values.amount);
  try {
    const result = await api("/api/applications", { method: "POST", body: JSON.stringify(values) });
    form.reset();
    if (documents.length) {
      try {
        await uploadDocuments(result.tracking_code, documents);
        showMessage(message, `${result.message} Tracking code: ${result.tracking_code}. Documents uploaded.`);
      } catch (error) {
        showMessage(message, `Application submitted. Tracking code: ${result.tracking_code}. Document upload failed: ${error.message}. Use the upload form to retry.`, true);
      }
    } else {
      showMessage(message, `${result.message} Tracking code: ${result.tracking_code}`);
    }
  } catch (error) {
    showMessage(message, error.message, true);
  }
});

document.querySelector("#document-upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = new FormData(form);
  const trackingCode = values.get("tracking_code");
  const files = Array.from(form.elements.files.files);
  const message = document.querySelector("#document-message");
  try {
    const result = await uploadDocuments(trackingCode, files);
    showMessage(message, `Uploaded ${result.documents.length} document(s).`);
    form.elements.files.value = "";
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
  const decisionButton = event.target.closest("button[data-start-decision]");
  if (decisionButton) {
    const card = decisionButton.closest(".application-card");
    const form = card.querySelector("[data-decision-form]");
    const action = decisionButton.dataset.startDecision;
    form.elements.action.value = action;
    form.elements.reason_code.innerHTML = `<option value="">Select a reason</option>${
      Object.entries(decisionReasons[action]).map(([value, label]) =>
        `<option value="${value}">${escapeHtml(label)}</option>`).join("")
    }`;
    form.classList.remove("hidden");
    form.elements.reason_code.focus();
    return;
  }
  if (event.target.closest("[data-cancel-decision]")) {
    event.target.closest("[data-decision-form]").classList.add("hidden");
    return;
  }
  const button = event.target.closest("button[data-application]");
  if (!button) return;
  button.disabled = true;
  try {
    await api(`/api/applications/${button.dataset.application}/actions`, {
      method: "POST",
      body: JSON.stringify({ action: button.dataset.action }),
    });
    await loadApplications();
  } catch (error) {
    window.alert(error.message);
    button.disabled = false;
  }
});

applicationList.addEventListener("submit", async (event) => {
  const decisionForm = event.target.closest("[data-decision-form]");
  if (decisionForm) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(decisionForm));
    const message = decisionForm.querySelector("[data-decision-message]");
    try {
      await api(`/api/applications/${decisionForm.dataset.application}/actions`, {
        method: "POST",
        body: JSON.stringify(values),
      });
      await loadApplications();
    } catch (error) {
      showMessage(message, error.message, true);
    }
    return;
  }
  const editForm = event.target.closest("[data-edit-application]");
  if (!editForm) return;
  event.preventDefault();
  const values = Object.fromEntries(new FormData(editForm));
  values.amount = Number(values.amount);
  const message = editForm.querySelector("[data-edit-message]");
  try {
    await api(`/api/applications/${editForm.dataset.editApplication}`, {
      method: "PATCH",
      body: JSON.stringify(values),
    });
    await loadApplications();
  } catch (error) {
    showMessage(message, error.message, true);
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
