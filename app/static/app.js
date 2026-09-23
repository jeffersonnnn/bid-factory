const $ = (s) => document.querySelector(s);
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const json = (v) => (typeof v === "string" ? JSON.parse(v) : v);
const human = (s) => String(s).toLowerCase().replaceAll("_", " ");
const kinds = [
  "eligibility",
  "technical",
  "management",
  "staffing",
  "key_personnel",
  "past_performance",
  "pricing",
  "certification",
  "form",
  "attachment",
  "formatting",
  "page_limit",
  "deadline",
  "submission",
  "amendment",
  "signature",
  "representation",
  "administrative",
  "other",
];
let workspace,
  view = null,
  current = null,
  tab = "requirements",
  busy = false;
let reviewStarted = Date.now();
let reviewer = sessionStorage.getItem("reviewer") || "";
const badge = (s) =>
  `<span class="badge ${["SATISFIED", "GO", "SUBMISSION_READY", "PASSED"].includes(s) ? "good" : ["MISSING", "FAILED", "NO-GO", "NEEDS_REVISION"].includes(s) ? "bad" : "wait"}">${esc(human(s))}</span>`;
const options = (list, selected) =>
  list
    .map(
      (x) =>
        `<option value="${esc(x.id ?? x)}" ${(x.id ?? x) === selected ? "selected" : ""}>${esc(x.label ?? human(x.id ?? x))}</option>`,
    )
    .join("");

async function api(path, body, method) {
  const config = {
    method: method || (body === undefined ? "GET" : "POST"),
    headers: {},
  };
  if (body instanceof FormData) config.body = body;
  else if (body !== undefined) {
    config.headers["Content-Type"] = "application/json";
    config.body = JSON.stringify(body);
  }
  const r = await fetch("/api" + path, config);
  if (!r.ok) {
    const error = await r
      .json()
      .catch(() => ({ detail: "The request failed." }));
    const d = error.detail;
    throw new Error(
      typeof d === "string"
        ? d
        : Array.isArray(d)
          ? d.map((e) => `${e.loc?.slice(1).join(".")}: ${e.msg}`).join("\n")
          : (d?.message || "The request failed.") +
            (d?.blockers?.length
              ? "\n" +
                d.blockers
                  .slice(0, 8)
                  .map((b) => b.finding)
                  .join("\n")
              : ""),
    );
  }
  return r.headers.get("content-type")?.includes("application/zip")
    ? r.blob()
    : r.json();
}
function toast(text) {
  $("#notice").textContent = text;
  $("#notice").hidden = false;
  setTimeout(() => ($("#notice").hidden = true), 6000);
}
async function task(label, fn) {
  if (busy) return;
  busy = true;
  $("#busy-text").textContent = label;
  $("#busy").hidden = false;
  try {
    await fn();
  } catch (e) {
    const target = $("#dialog[open] .form-error");
    if (target) {
      target.textContent = e.message;
      target.hidden = false;
    } else toast(e.message);
  } finally {
    busy = false;
    $("#busy").hidden = true;
  }
}
function closeInspector() {
  $("#inspector").hidden = true;
}
function modal(title, body, onSubmit) {
  reviewStarted = Date.now();
  $("#dialog-content").innerHTML =
    `<div class="dialog-head"><h2>${esc(title)}</h2><button type="button" class="icon" data-close aria-label="Close dialog">×</button></div><form id="modal-form">${body}<div class="error form-error" hidden></div></form>`;
  $("#dialog [data-close]").onclick = () => $("#dialog").close();
  $("#modal-form").onsubmit = (e) => {
    e.preventDefault();
    const values = Object.fromEntries(new FormData(e.target));
    task("Saving your review…", async () => {
      await onSubmit(values, e.target);
    });
  };
  $("#dialog").showModal();
}
function reviewFields(reasonLabel = "Review notes", defaultReason = "") {
  return `<label for="reviewer">Reviewer name</label><input id="reviewer" name="reviewer" value="${esc(reviewer)}" required minlength="2" autocomplete="name"><label for="reason">${esc(reasonLabel)}</label><textarea id="reason" name="reason" minlength="8" required placeholder="Record what you checked and any decision.">${esc(defaultReason)}</textarea>`;
}
function reviewData(v) {
  reviewer = v.reviewer;
  sessionStorage.setItem("reviewer", reviewer);
  return {
    reviewer: v.reviewer,
    reason: v.reason,
    expected_revision: current?.bid?.revision ?? null,
    duration_seconds: Math.min(
      86400,
      Math.floor((Date.now() - reviewStarted) / 1000),
    ),
  };
}
const submit = (text) =>
  `<div class="form-actions"><button class="primary" type="submit">${esc(text)}</button></div>`;

async function loadWorkspace() {
  workspace = await api("/workspace");
  $("#provider-label").textContent =
    workspace.ai.provider === "offline"
      ? "Human review mode"
      : `${workspace.ai.provider} · ${workspace.ai.configured ? "AI configured" : "Key required"}`;
  $("#bid-list").innerHTML = workspace.bids.length
    ? workspace.bids
        .map(
          (b) =>
            `<button class="nav-item ${view?.id === b.id ? "active" : ""}" data-bid="${b.id}">${esc(b.title)}<small>${esc(b.company_name)}</small></button>`,
        )
        .join("")
    : '<span class="note nav-item">No bids yet</span>';
  $("#company-list").innerHTML = workspace.companies.length
    ? workspace.companies
        .map(
          (c) =>
            `<button class="nav-item ${view?.id === c.id ? "active" : ""}" data-company="${c.id}">${esc(c.name)}</button>`,
        )
        .join("")
    : '<span class="note nav-item">Add your first company</span>';
  document
    .querySelectorAll("[data-bid]")
    .forEach((b) => (b.onclick = () => openBid(b.dataset.bid)));
  document
    .querySelectorAll("[data-company]")
    .forEach((b) => (b.onclick = () => openCompany(b.dataset.company)));
}
async function refresh() {
  await loadWorkspace();
  if (view?.type === "bid") await openBid(view.id, false);
  else if (view?.type === "company") await openCompany(view.id, false);
  else home();
}
function home() {
  view = null;
  $("#content").innerHTML =
    `<div class="topline"><span class="breadcrumb">Workspace / Review desk</span><span class="badge">V0 · Civilian service RFQs</span></div><div class="empty"><h1>A clear path from<br>solicitation to submission.</h1><p>Extract the requirements. Confirm the evidence. Resolve the missing facts. Review one complete bid package.</p><div class="actions"><button class="primary" id="start-company">Add a company</button><button id="start-bid">Create a bid</button></div><div class="step-grid"><div><strong>Sources first</strong>Keep each requirement linked to its original instruction.</div><div><strong>Evidence only</strong>Use approved facts. Ask for every missing answer.</div><div><strong>Zero blockers</strong>Check the final document before you release it.</div></div></div><div class="hint">This desk supports ordinary civilian service RFQs and proposals of up to 30 pages. Use unclassified, non-CUI documents only.</div>`;
  $("#start-company").onclick = newCompany;
  $("#start-bid").onclick = newBid;
}
function newCompany() {
  modal(
    "Add a company",
    `<p class="muted">Start with a name. Extract company facts from supporting documents next.</p><label for="company-name">Company name</label><input id="company-name" name="name" required minlength="2" maxlength="120">${submit("Create company")}`,
    async (v) => {
      const c = await api("/companies", { name: v.name });
      $("#dialog").close();
      await loadWorkspace();
      await openCompany(c.id);
    },
  );
}
function newBid() {
  if (!workspace.companies.length) {
    newCompany();
    return;
  }
  modal(
    "Create a bid",
    `<label for="bid-title">Solicitation or bid title</label><input id="bid-title" name="title" required minlength="2" maxlength="180" placeholder="Janitorial services — RFQ reference"><label for="bid-company">Company</label><select id="bid-company" name="company_id">${options(workspace.companies.map((c) => ({ id: c.id, label: c.name })))}</select><p class="note">Upload the solicitation, attachments and all amendments after this step.</p>${submit("Create bid")}`,
    async (v) => {
      const b = await api("/bids", v);
      $("#dialog").close();
      tab = "sources";
      await loadWorkspace();
      await openBid(b.id);
    },
  );
}

async function openCompany(id, push = true) {
  closeInspector();
  view = { type: "company", id };
  current = await api("/companies/" + id);
  if (push) history.pushState({}, "", `/companies/${id}`);
  const c = current.company;
  const active = current.evidence.filter((e) => !e.rejected);
  $("#content").innerHTML =
    `<div class="topline"><span class="breadcrumb">Workspace / Company evidence</span>${badge("REVIEW")}</div><div class="title-row"><div><h1>${esc(c.name)}</h1><p class="muted">Approve the facts that proposals can use.</p></div><div class="actions"><button id="upload-company">Upload documents</button><button class="primary" id="extract-company">Extract evidence</button></div></div><div class="stats"><div class="stat"><strong>${current.documents.length}</strong><span>Source documents</span></div><div class="stat"><strong>${active.filter((e) => e.approved).length}</strong><span>Approved facts</span></div><div class="stat"><strong>${active.filter((e) => !e.approved).length}</strong><span>Facts to review</span></div></div><div class="hint">A source is not proof of truth. Check ownership, accuracy, dates and permission before you approve a fact.</div><section class="panel"><div class="panel-head"><h2>Company documents</h2><button class="small" id="add-manual-evidence">Add a sourced fact</button></div>${documentList(current.documents, true)}</section><section><h2>Evidence library</h2>${active.length ? `<div class="table-wrap"><table><thead><tr><th>Source statement</th><th>Type</th><th>Review</th></tr></thead><tbody>${active.map((e) => `<tr><td class="req-text"><button class="text-button" data-evidence="${e.id}">${esc(e.statement)}</button><small>${esc(e.document_name || e.locator)} · ${esc(e.locator)}</small></td><td>${esc(human(e.kind))}</td><td>${badge(e.approved ? "SATISFIED" : "CLIENT_CONFIRMATION_REQUIRED")}</td></tr>`).join("")}</tbody></table></div>` : '<div class="panel"><p class="muted">Upload company documents, then extract evidence. No facts are approved automatically.</p></div>'}</section>`;
  $("#upload-company").onclick = () => uploadDialog("company");
  $("#extract-company").onclick = () =>
    task("Extracting source statements…", async () => {
      const r = await api(`/companies/${id}/extract`, {});
      toast(`${r.added} facts extracted for review.`);
      await refresh();
    });
  $("#add-manual-evidence").onclick = manualEvidence;
  bindDocuments();
  bindEvidence();
  await loadWorkspace();
}

function documentList(docs, company = false) {
  return docs.length
    ? docs
        .map(
          (d) =>
            `<div class="document-row"><div><button class="text-button" data-source="${d.id}">${esc(d.name)}</button><small>${esc(human(d.kind))}${d.sequence ? ` ${String(d.sequence).padStart(4, "0")}` : ""} · ${json(d.pages).length} source blocks${d.reviewed ? " · Coverage confirmed" : ""}</small></div><div class="actions">${d.kind === "amendment" && !d.acknowledged ? `<button class="small" data-ack="${d.id}">Acknowledge</button>` : ""}${d.kind === "response_attachment" ? `<button class="small" data-att-extract="${d.id}">Extract evidence</button>` : ""}<a class="small" href="/api/documents/${d.id}/download">Original file</a></div></div>`,
        )
        .join("")
    : '<p class="muted">No documents yet. Upload the original files to begin.</p>';
}
function bindDocuments() {
  document
    .querySelectorAll("[data-source]")
    .forEach((b) => (b.onclick = () => showSource(b.dataset.source)));
  document
    .querySelectorAll("[data-ack]")
    .forEach(
      (b) =>
        (b.onclick = () =>
          reviewAction(
            "Acknowledge amendment",
            `/documents/${b.dataset.ack}/acknowledge`,
            "Record the customer acknowledgment. Upload a signed form if the solicitation requires one.",
          )),
    );
  document.querySelectorAll("[data-att-extract]").forEach(
    (b) =>
      (b.onclick = () =>
        task("Extracting attachment evidence…", async () => {
          await api(`/documents/${b.dataset.attExtract}/extract-evidence`, {});
          await refresh();
        })),
  );
}
function bindEvidence() {
  document
    .querySelectorAll("[data-evidence]")
    .forEach((b) => (b.onclick = () => showEvidence(b.dataset.evidence)));
}
function uploadDialog(type) {
  modal(
    type === "company" ? "Upload company document" : "Upload bid document",
    `<label for="upload-file">Document</label><input id="upload-file" type="file" name="file" accept=".pdf,.docx,.xlsx,.txt,.md,.csv" required><p class="note">PDF, DOCX, XLSX or text. Maximum 12 MB. Scan-only solicitation pages require OCR first.</p>${type === "bid" ? `<label for="doc-kind">Document role</label><select id="doc-kind" name="kind"><option value="solicitation">Solicitation or source attachment</option><option value="amendment">Amendment</option><option value="response_attachment">Response attachment to include in export</option></select><label for="doc-sequence">Amendment number</label><input id="doc-sequence" type="number" name="sequence" min="0" max="9999" value="0"><p class="note">Use 0 for the solicitation and response attachments. Use the official number for amendments.</p>` : ""}${submit("Upload document")}`,
    async (v, form) => {
      const r = await api(
        `/${type === "company" ? "companies" : "bids"}/${view.id}/documents`,
        new FormData(form),
      );
      $("#dialog").close();
      toast(
        r.duplicate
          ? "This file is already in the package."
          : "Document saved.",
      );
      await refresh();
    },
  );
}

async function openBid(id, push = true) {
  view = { type: "bid", id };
  current = await api("/bids/" + id);
  if (push) history.pushState({}, "", `/bids/${id}`);
  const b = current.bid;
  const satisfied = current.requirements.filter(
    (r) => r.status === "SATISFIED",
  ).length;
  $("#content").innerHTML =
    `<div class="topline"><span class="breadcrumb">${esc(current.company.name)} / Bid review</span><span class="source-meta">Revision ${b.revision}</span></div><div class="title-row"><div><h1>${esc(b.title)}</h1><div class="actions">${badge(b.state)}${badge(current.qualification.status)}<span class="note">${current.ready ? "Approved for this exact version." : "Final export stays locked until all blockers are resolved."}</span></div></div><div class="actions"><button id="settings-button">Submission settings</button><button class="primary" id="upload-bid">Upload document</button></div></div><div class="stats"><div class="stat"><strong>${current.requirements.length}</strong><span>Current requirements</span></div><div class="stat"><strong>${satisfied}</strong><span>Evidence confirmed</span></div><div class="stat"><strong>${current.questions.length}</strong><span>Open questions</span></div><div class="stat block"><strong>${current.blockers.length}</strong><span>Export blockers</span></div></div><nav class="tabs" aria-label="Bid stages">${[
      ["sources", "Sources"],
      ["requirements", "Requirements"],
      ["questions", "Questions"],
      ["proposal", "Proposal"],
      ["audit", "Audit & export"],
    ]
      .map(
        ([key, label]) =>
          `<button class="tab ${tab === key ? "active" : ""}" data-tab="${key}">${label}</button>`,
      )
      .join("")}</nav><div id="tab-content"></div>`;
  $("#settings-button").onclick = settings;
  $("#upload-bid").onclick = () => uploadDialog("bid");
  document.querySelectorAll("[data-tab]").forEach(
    (b) =>
      (b.onclick = () => {
        tab = b.dataset.tab;
        closeInspector();
        openBid(id, false);
      }),
  );
  renderTab();
  await loadWorkspace();
}
function renderTab() {
  const c = current;
  let html = "";
  if (tab === "sources")
    html = `<section class="panel"><div class="panel-head"><div><h2>Complete source package</h2><p class="note">Review every source block after extraction. Confirm that no obligation was omitted.</p></div><button class="primary" id="extract-bid">Extract requirements</button></div>${documentList(c.documents)}</section><div class="hint">Amendments stay in the history. Link each changed instruction to the requirement it replaces. Confirm the latest versions in submission settings.</div><button id="manual-req">Add a sourced requirement</button>`;
  if (tab === "requirements")
    html = `<div class="panel-head"><div><h2>Requirement ledger</h2><span class="note">Select a requirement to compare the source, evidence and proposal response.</span></div><div class="actions"><button id="manual-req">Add requirement</button><button id="map-button">Suggest evidence</button></div></div>${c.requirements.length ? `<div class="table-wrap"><table><thead><tr><th>Requirement</th><th>Type / scope</th><th>Evidence status</th></tr></thead><tbody>${c.requirements.map((r) => `<tr class="clickable" data-req="${r.id}"><td class="req-text"><button class="text-button">${esc(r.text)}</button><small>${esc(r.document_name)} · ${esc(r.locator)}${r.supersedes ? " · Replaces an earlier instruction" : ""}</small></td><td>${esc(human(r.kind))}<small>${r.mandatory ? "Mandatory" : "Optional"} · ${esc(r.scope)}</small></td><td>${badge(r.status)}</td></tr>`).join("")}</tbody></table></div>` : '<div class="panel"><p class="muted">Upload the source package and extract its requirements first.</p><button id="go-sources">Open sources</button></div>'}<details><summary>Version history (${c.ledger.length} records)</summary>${c.ledger.map((r) => `<div class="history">${esc(r.id)} — ${esc(r.text)} ${r.supersedes ? `<br>Replaces ${esc(r.supersedes)}: ${esc(r.supersession_reason)}` : ""}</div>`).join("")}</details>`;
  if (tab === "questions")
    html = `<div class="panel-head"><div><h2>Only the missing information</h2><p class="note">Customer answers become traceable evidence. A reviewer then confirms requirement coverage.</p></div></div>${
      c.questions.length
        ? c.questions
            .map((q) => {
              const r = c.requirements.find((r) => r.id === q.requirement_id);
              return `<div class="question"><small>${esc(human(r.kind))} · ${esc(r.document_name)}, ${esc(r.locator)}</small><p>${esc(q.text)}</p><div class="actions">${["deadline", "page_limit", "submission"].includes(r.kind) ? '<button class="small open-settings">Confirm settings</button>' : `<button class="small" data-answer="${r.id}">Record customer answer</button>`}<button class="small" data-req="${r.id}">Review evidence</button></div></div>`;
            })
            .join("")
        : '<div class="panel"><h3>No open requirement questions</h3><p class="muted">Check the audit tab for package and review blockers.</p></div>'
    }`;
  if (tab === "proposal")
    html = `<div class="panel-head"><div><h2>Evidence-grounded proposal</h2><p class="note">Each statement uses approved source text. Select a statement to inspect its evidence.</p></div><div class="actions">${c.draft.length ? `<a target="_blank" href="/api/bids/${c.bid.id}/preview.pdf">Preview PDF</a>` : ""}<button class="primary" id="generate-button" ${!c.can_generate ? "disabled" : ""}>${c.draft.length ? "Regenerate draft" : "Generate draft"}</button></div></div>${!c.can_generate ? '<div class="hint">Resolve the source, evidence and submission-setting blockers before generating a draft.</div>' : ""}${c.draft.length ? `<article class="paper"><span class="badge wait">${c.bid.draft_revision !== c.bid.revision ? "Outdated draft" : "Draft for review"}</span><h2>${esc(c.company.name)}</h2><p class="muted">${esc(c.bid.title)}</p>${c.draft.map((s) => `<h3>${esc(s.title)}</h3>${s.claims.map((cl) => `<p class="claim" tabindex="0" role="button" data-evidence="${cl.evidence_id}">${esc(cl.text)}<small>Source attached · ${esc(cl.evidence_id)}</small></p>`).join("")}`).join("")}</article>` : '<div class="panel"><p class="muted">No proposal yet. The generator never fills missing facts with invented text.</p></div>'}`;
  if (tab === "audit")
    html = `<div class="panel-head"><div><h2>${c.ready ? "Submission ready" : "Release checks"}</h2><p class="note">A fresh audit and human approval are required for each final version.</p></div><div class="actions"><button id="audit-button" ${c.bid.draft_revision !== c.bid.revision ? "disabled" : ""}>Run independent audit</button><button id="approve-button" ${c.blockers.length ? "disabled" : ""}>Approve final version</button></div></div><div class="panel">${c.blockers.length ? c.blockers.map((f) => `<div class="blocker"><span class="blocker-marker">!</span><div><p>${esc(f.finding)}</p><small>${esc(f.action)}</small>${f.requirement_id ? `<button class="text-button small" data-req="${esc(f.requirement_id)}">Open requirement</button>` : ""}</div></div>`).join("") : '<h3>No unresolved blockers</h3><p class="muted">Review the PDF and submission files before final approval.</p>'}</div><div class="panel"><div class="panel-head"><div><h2>Submission package</h2><p class="note">DOCX, PDF, original response attachments, compliance matrix, checklist and private source records.</p></div><div class="actions"><button id="draft-export" ${!c.draft.length ? "disabled" : ""}>Export draft</button><button class="primary" id="final-export" ${!c.ready ? "disabled" : ""}>Export final package</button></div></div><p class="note">Send only the requested submission files. The internal folder contains private evidence and review records.</p></div>${
      c.audit_findings.filter(
        (f) => f.rule_id === "RED-TEAM" && f.resolved_revision === null,
      ).length
        ? `<section class="panel"><h2>Red-team findings to resolve</h2>${c.audit_findings
            .filter(
              (f) => f.rule_id === "RED-TEAM" && f.resolved_revision === null,
            )
            .map(
              (f) =>
                `<div class="blocker"><div><p>${esc(f.finding)}</p><button class="small" data-resolve="${f.id}">Record correction</button></div></div>`,
            )
            .join("")}</section>`
        : ""
    }<details><summary>Audit and review history</summary>${c.audits.map((a) => `<p class="history">${badge(a.status)} Revision ${a.revision} · ${esc(a.mode)} review by ${esc(a.reviewer)}<br>${esc(a.notes)}</p>`).join("")}${c.review_events.map((e) => `<p class="history">${esc(human(e.action))} · ${esc(e.reviewer)} · ${esc(e.created_at)}</p>`).join("")}</details>`;
  $("#tab-content").innerHTML = html;
  document
    .querySelectorAll("[data-resolve]")
    .forEach(
      (b) =>
        (b.onclick = () =>
          reviewAction(
            "Resolve red-team finding",
            `/findings/${b.dataset.resolve}/resolve`,
            "Describe the source or evidence correction. A new audit is required after resolution.",
          )),
    );
  bindDocuments();
  bindEvidence();
  document
    .querySelectorAll("[data-req]")
    .forEach((b) => (b.onclick = () => showRequirement(b.dataset.req)));
  document
    .querySelectorAll("[data-answer]")
    .forEach((b) => (b.onclick = () => answerDialog(b.dataset.answer)));
  document
    .querySelectorAll(".open-settings")
    .forEach((b) => (b.onclick = settings));
  if ($("#extract-bid"))
    $("#extract-bid").onclick = () =>
      task("Extracting requirements. This can take a minute…", async () => {
        const r = await api(`/bids/${view.id}/extract`, {});
        toast(`${r.added} requirements added. Review source coverage next.`);
        await refresh();
      });
  if ($("#manual-req")) $("#manual-req").onclick = () => manualRequirement();
  if ($("#map-button"))
    $("#map-button").onclick = () =>
      task("Finding possible evidence matches…", async () => {
        await api(`/bids/${view.id}/map-evidence`, {});
        await refresh();
        toast("Suggested matches need your approval.");
      });
  if ($("#go-sources"))
    $("#go-sources").onclick = () => {
      tab = "sources";
      openBid(view.id, false);
    };
  if ($("#generate-button"))
    $("#generate-button").onclick = () =>
      task("Assembling the proposal from approved evidence…", async () => {
        await api(`/bids/${view.id}/generate`, {});
        await refresh();
      });
  if ($("#audit-button")) $("#audit-button").onclick = auditDialog;
  if ($("#approve-button"))
    $("#approve-button").onclick = () =>
      reviewAction(
        "Approve final version",
        `/bids/${view.id}/approve`,
        "Confirm that you inspected the rendered PDF, the required forms, signatures, pricing and submission method.",
      );
  if ($("#draft-export"))
    $("#draft-export").onclick = () => exportPackage(false);
  if ($("#final-export"))
    $("#final-export").onclick = () => exportPackage(true);
}

async function showSource(id) {
  const d = await api("/documents/" + id);
  const pages = json(d.pages);
  const reqs = (current.requirements || []).filter((r) => r.document_id === id);
  modal(
    "Review source coverage",
    `<h3>${esc(d.name)}</h3><p class="source-meta">SHA-256: ${esc(d.sha256)}</p>${json(
      d.warnings,
    )
      .map((w) => `<div class="hint">${esc(w)}</div>`)
      .join(
        "",
      )}${pages.map((p) => `<details open><summary>${esc(p.locator)}</summary><div class="quote source-block">${esc(p.text)}</div></details>`).join("")}<h3>Extracted requirements (${reqs.length})</h3>${reqs.map((r) => `<p class="note">${esc(r.text)}</p>`).join("")}${d.bid_id && d.kind !== "response_attachment" ? `<p class="note">Add any missing requirement before you confirm coverage. Return to the requirement ledger to add or replace one.</p>${reviewFields()}<label class="check"><input type="checkbox" required>I compared every source block with the requirement ledger, including attachments and uncertain instructions.</label>${submit("Confirm source coverage")}` : '<p class="note">Review individual facts in the evidence library before approving them.</p>'}`,
    async (v) => {
      await api(`/documents/${id}/review`, reviewData(v));
      $("#dialog").close();
      await refresh();
    },
  );
}
function reviewAction(title, path, description) {
  modal(
    title,
    `<p class="muted">${esc(description)}</p>${reviewFields()}<label class="check"><input type="checkbox" required>I completed this check for the current version.</label>${submit(title)}`,
    async (v) => {
      await api(path, reviewData(v));
      $("#dialog").close();
      await refresh();
    },
  );
}

function showEvidence(id) {
  const e = current.evidence.find((x) => x.id === id);
  if (!e) {
    toast("This evidence is no longer current.");
    return;
  }
  const panel = $("#inspector");
  panel.hidden = false;
  panel.innerHTML = `<div class="inspector-head"><div><h2>Claim evidence</h2><span class="source-meta">${esc(e.id)}</span></div><button class="icon" id="close-inspector" aria-label="Close evidence">×</button></div>${badge(e.approved ? "SATISFIED" : "CLIENT_CONFIRMATION_REQUIRED")}<div class="quote">${esc(e.statement)}</div><p class="note">${esc(e.document_name || e.locator)}<br>${esc(e.locator)}<br>Fact key: ${esc(e.fact_key || "Not assigned")}</p>${e.document_id ? `<a href="/api/documents/${e.document_id}/download">Download source document</a>` : ""}<p class="note">Approve only facts you can verify. Reject stale, false or conflicting statements with a reason.</p><div class="actions"><button class="primary" id="approve-evidence">Approve evidence</button><button class="danger" id="reject-evidence">Reject evidence</button></div>`;
  $("#close-inspector").onclick = closeInspector;
  $("#approve-evidence").onclick = () => evidenceReview(id, true);
  $("#reject-evidence").onclick = () => evidenceReview(id, false);
}
function evidenceReview(id, approved) {
  modal(
    approved ? "Approve source evidence" : "Reject source evidence",
    `${reviewFields()}${approved ? '<label for="expiry">Expiration, if applicable (ISO date and time with offset)</label><input name="expires_at" id="expiry" placeholder="2027-12-31T23:59:00-05:00">' : ""}${submit(approved ? "Approve evidence" : "Reject evidence")}`,
    async (v) => {
      await api(`/evidence/${id}/review`, {
        ...reviewData(v),
        approved,
        expires_at: v.expires_at || null,
      });
      $("#dialog").close();
      closeInspector();
      await refresh();
    },
  );
}

function showRequirement(id) {
  reviewStarted = Date.now();
  const r = current.requirements.find((x) => x.id === id);
  if (!r) {
    toast("This requirement is no longer current. Open the version history.");
    return;
  }
  const c = current;
  const panel = $("#inspector");
  panel.hidden = false;
  const control = ["deadline", "page_limit", "submission"].includes(r.kind);
  panel.innerHTML = `<div class="inspector-head"><div><h2>Requirement review</h2><span class="source-meta">${esc(r.id)}</span></div><button class="icon" id="close-inspector" aria-label="Close requirement">×</button></div>${badge(r.status)}<h3>${esc(r.text)}</h3><p class="note">${esc(r.document_name)} · ${esc(r.locator)}<br>${esc(r.scope)} obligation · ${r.mandatory ? "Mandatory" : "Optional"}</p><div class="quote">${esc(r.quote)}</div><div class="actions"><button class="small" id="req-source">Open full source</button><button class="small" id="replace-req">Correct or supersede</button></div>${control ? '<div class="hint">Confirm this instruction in the submission settings.</div><button class="primary" id="req-settings">Open settings</button>' : `<h3>Evidence for this requirement</h3><p class="note">Select evidence that fully meets the instruction. Check quantities, dates, comparability and all required details.</p><form id="mapping-form">${c.evidence.length ? c.evidence.map((e) => `<label class="evidence-choice"><input type="checkbox" name="evidence_ids" value="${e.id}" ${r.mappings.some((m) => m.evidence_id === e.id) ? "checked" : ""}><span>${esc(e.statement)}<small>${esc(e.document_name || e.locator)} · ${e.approved ? "Approved" : "Needs approval"}</small><button type="button" class="small" data-evidence-review="${e.id}">Inspect evidence</button></span></label>`).join("") : '<p class="muted">No evidence yet.</p>'}${reviewFields("Why does this evidence meet the complete requirement?")}${submit("Approve evidence mapping")}</form><div class="actions"><button class="small" id="req-answer">Record customer answer</button></div>`}<details><summary>Proposal response</summary>${
    c.draft
      .filter((s) => s.requirement_id === r.id)
      .map((s) => s.claims.map((cl) => `<p>${esc(cl.text)}</p>`).join(""))
      .join("") || '<p class="note">No current response.</p>'
  }</details>`;
  $("#close-inspector").onclick = closeInspector;
  $("#req-source").onclick = () => showSource(r.document_id);
  $("#replace-req").onclick = () => manualRequirement(r);
  if (control) $("#req-settings").onclick = settings;
  else {
    $("#req-answer").onclick = () => answerDialog(id);
    $("#mapping-form").onsubmit = (e) => {
      e.preventDefault();
      const form = new FormData(e.target);
      const v = Object.fromEntries(form);
      task("Saving evidence mapping…", async () => {
        await api(`/requirements/${id}/mapping`, {
          ...reviewData(v),
          evidence_ids: form.getAll("evidence_ids"),
          approved: true,
        });
        await refresh();
        showRequirement(id);
        toast("Mapping saved.");
      });
    };
    document
      .querySelectorAll("[data-evidence-review]")
      .forEach(
        (b) => (b.onclick = () => showEvidence(b.dataset.evidenceReview)),
      );
  }
}

function answerDialog(id) {
  const r = current.requirements.find((x) => x.id === id);
  modal(
    "Record a customer answer",
    `<div class="quote">${esc(r.text)}</div><label for="customer-name">Customer name</label><input id="customer-name" name="customer_name" required minlength="2"><label for="answer-text">Confirmed factual answer</label><textarea id="answer-text" name="text" required minlength="2" placeholder="Use complete sentences that can appear in the proposal."></textarea><label for="fact-key">Fact key</label><input id="fact-key" name="fact_key" value="${esc(r.key)}"><p class="note">Use a different key for each distinct project reference. Use the same key for conflicting values of one fact.</p><label for="supersedes-evidence">Replace incorrect evidence, if applicable</label><select id="supersedes-evidence" name="supersedes"><option value="">No replacement</option>${options(current.evidence.map((e) => ({ id: e.id, label: e.statement.slice(0, 100) })))}</select><label>Response attachment verified by this answer, if required</label><select name="attachment_document_id"><option value="">No attachment</option>${options(current.documents.filter((d) => d.kind === "response_attachment").map((d) => ({ id: d.id, label: d.name })))}</select><label class="check"><input type="checkbox" required>The named customer confirmed this exact answer, including any pricing and the selected attachment.</label>${submit("Save customer answer")}`,
    async (v) => {
      await api(`/bids/${view.id}/answers`, {
        ...v,
        requirement_id: id,
        supersedes: v.supersedes || null,
        attachment_document_id: v.attachment_document_id || null,
        confirmed: true,
      });
      $("#dialog").close();
      await refresh();
      showRequirement(id);
    },
  );
}

function settings() {
  const c = json(current.bid.controls);
  const list = (kind) =>
    current.requirements
      .filter((r) => r.kind === kind)
      .map((r) => ({ id: r.id, label: r.text }));
  modal(
    "Confirm submission settings",
    `<p class="note">Use the latest source instructions. Include the time zone. A missing deadline or submission method blocks drafting.</p><label for="deadline-source">Deadline source</label><select id="deadline-source" name="deadline_requirement_id" required><option value="">Select requirement</option>${options(list("deadline"), c.deadline_requirement_id)}</select><label for="deadline">Deadline with time zone</label><input id="deadline" name="deadline" required value="${esc(c.deadline || "")}" placeholder="2026-12-01T14:00:00-05:00"><label for="limit-source">Page limit source</label><select id="limit-source" name="page_limit_requirement_id"><option value="">No explicit source limit; apply the V0 cap</option>${options(list("page_limit"), c.page_limit_requirement_id)}</select><label for="limit">Maximum proposal pages</label><input id="limit" type="number" min="1" max="30" name="page_limit" value="${c.page_limit || 30}" required><label for="method-source">Submission method source</label><select id="method-source" name="submission_requirement_id" required><option value="">Select requirement</option>${options(list("submission"), c.submission_requirement_id)}</select><label for="method">Submission method and destination</label><textarea id="method" name="submission_method" required minlength="5">${esc(c.submission_method || "")}</textarea>${reviewFields()}<label class="check"><input type="checkbox" required>This is an ordinary civilian service RFQ, with no CUI, classified material, complex cost proposal or unsupported format constraints.</label><label class="check"><input type="checkbox" required>I checked the complete source package, all amendments, formatting instructions and required attachments.</label>${submit("Confirm settings")}`,
    async (v) => {
      await api(`/bids/${view.id}/controls`, {
        ...v,
        ...reviewData(v),
        page_limit: Number(v.page_limit),
        page_limit_requirement_id: v.page_limit_requirement_id || null,
        scope_confirmed: true,
        package_complete: true,
      });
      $("#dialog").close();
      await refresh();
    },
  );
}

function manualRequirement(old) {
  const docs = current.documents.filter(
    (d) => d.kind !== "response_attachment",
  );
  modal(
    old ? "Correct or replace a requirement" : "Add an omitted requirement",
    `<p class="note">Copy the source quote exactly. Keep one obligation per requirement. Replacements preserve the old record.</p><label>Source document</label><select name="document_id" required>${options(
      docs.map((d) => ({ id: d.id, label: d.name })),
      old?.document_id,
    )}</select><label>Source block number (PDF page, DOCX body block or sheet index)</label><input type="number" min="1" name="page" value="${old?.page || 1}" required><label>Exact source quote</label><textarea name="quote" required>${esc(old?.quote || "")}</textarea><label>One atomic requirement</label><textarea name="text" required>${esc(old?.text || "")}</textarea><div class="form-row"><div><label>Type</label><select name="kind">${options(kinds, old?.kind || "technical")}</select></div><div><label>Scope</label><select name="scope">${options(["submission", "performance"], old?.scope || "submission")}</select></div></div><label>Stable topic key</label><input name="key" required value="${esc(old?.key || "")}" placeholder="supervisor_experience"><label>Constraints (JSON)</label><textarea name="constraints">${esc(old?.constraints || "{}")}</textarea><p class="note">Examples: {"count":3}, {"max_pages":20}, {"attachment":true}, {"uei":true}.</p>${old ? '<label>Replacement reason</label><textarea name="supersession_reason" required minlength="8"></textarea>' : ""}${submit("Save sourced requirement")}`,
    async (v) => {
      await api(`/bids/${view.id}/requirements`, {
        ...v,
        page: Number(v.page),
        constraints: JSON.parse(v.constraints),
        mandatory: true,
        supersedes: old?.id || null,
      });
      $("#dialog").close();
      closeInspector();
      await refresh();
    },
  );
}
function manualEvidence() {
  modal(
    "Add a sourced fact",
    `<label>Source document</label><select name="document_id" required>${options(current.documents.map((d) => ({ id: d.id, label: d.name })))}</select><label>Source block number</label><input type="number" name="page" min="1" value="1" required><label>Exact factual source quote</label><textarea name="quote" required></textarea><label>Type</label><select name="kind">${options(kinds, "technical")}</select><label>Fact key</label><input name="fact_key" placeholder="supervisor.experience">${submit("Add evidence for review")}`,
    async (v) => {
      await api(`/companies/${view.id}/evidence`, {
        ...v,
        page: Number(v.page),
      });
      $("#dialog").close();
      await refresh();
    },
  );
}
function auditDialog() {
  modal(
    "Independent compliance audit",
    `<p class="muted">Compare the finished response with every original instruction. Check extraction omissions, factual support, forms, signatures, pricing and page layout.</p><label>Audit mode</label><select name="mode"><option value="human">Human red-team review</option>${workspace.ai.configured ? '<option value="ai">Separate AI red-team review plus human check</option>' : ""}</select>${reviewFields("What did the independent review check?")}<label>Unresolved findings (one per line)</label><textarea name="findings" placeholder="Leave empty only if no issues remain."></textarea><label class="check"><input type="checkbox" required>I completed an independent review of the rendered proposal and original source package.</label>${submit("Run audit and deterministic checks")}`,
    async (v) => {
      await api(`/bids/${view.id}/audit`, {
        ...reviewData(v),
        mode: v.mode,
        independent_review_complete: true,
        findings: v.findings
          .split("\n")
          .map((x) => x.trim())
          .filter(Boolean),
      });
      $("#dialog").close();
      await refresh();
    },
  );
}
function exportPackage(final) {
  task("Rendering and checking the submission package…", async () => {
    const blob = await api(`/bids/${view.id}/export`, { final });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${view.id}-${final ? "FINAL" : "DRAFT"}.zip`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    toast("Package exported. Keep the internal review folder private.");
  });
}

$("#new-company").onclick = newCompany;
$("#new-bid").onclick = newBid;
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeInspector();
  if (
    (e.key === "Enter" || e.key === " ") &&
    e.target.classList.contains("claim")
  ) {
    e.preventDefault();
    e.target.click();
  }
});
window.addEventListener("popstate", () => route());
async function route() {
  const parts = location.pathname.split("/");
  await loadWorkspace();
  if (parts[1] === "bids" && parts[2] && parts[2] !== "new")
    await openBid(parts[2], false);
  else if (parts[1] === "companies" && parts[2] && parts[2] !== "new")
    await openCompany(parts[2], false);
  else {
    home();
    if (parts[2] === "new") (parts[1] === "bids" ? newBid : newCompany)();
  }
}
route().catch((e) => {
  $("#content").innerHTML = `<div class="error">${esc(e.message)}</div>`;
});
