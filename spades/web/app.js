"use strict";

const $ = (selector) => document.querySelector(selector);
const state = { token: "", runs: [], report: null, corpus: [], active: null, handled: null, workspace: { presets: [], bookmarks: [] } };
const selectionState = { ids: new Set(), previewRevision: 0, previewTimer: null };
const names = { baseline: "Legitimate controls", indirect_injection: "Indirect injection", semantic_camouflage: "Semantic camouflage", metadata_hijacking: "Metadata hijacking", exfiltration: "Exfiltration", data_corruption: "Data corruption", role_spoofing: "Role impersonation", cross_document: "Cross-document manipulation" };
const metrics = [
  ["vulnerable_asr", "Vulnerable attack rate", "Lower is better", "risk"],
  ["secured_asr", "Secured attack rate", "Lower is better", "good"],
  ["mitigation_rate", "Attack mitigation", "Of baseline-successful attacks", "good"],
  ["secured_task_success", "Legitimate task success", "Number / unit assertions", "good"],
  ["false_positive_rate", "False positive rate", "Clean baseline cases only", "risk"],
  ["secured_leakage_rate", "Secured data leakage", "Synthetic canary disclosures", "risk"],
];
const enterpriseMetrics = [
  ["secured_field_score", "Field accuracy", "Typed values and numeric tolerances", "good"],
  ["secured_task_success", "Complete rubric pass", "All fields, citations and no leakage", "good"],
  ["secured_citation_coverage", "Citation coverage", "Required operative records cited", "good"],
  ["required_source_recall", "Evidence coverage", "Required sources in model context", "good"],
  ["secured_format_rate", "Valid structured output", "JSON contract validation", "good"],
  ["secured_asr", "Attack objective matched", "Incorrect typed value or canary", "risk"],
  ["false_positive_rate", "Control overblocking", "Legitimate baseline cases only", "risk"],
  ["secured_leakage_rate", "Restricted data disclosure", "Synthetic evidence-vault canary", "risk"],
];
const metricsFor = report => report?.configuration?.profile === "complex" ? enterpriseMetrics : metrics;

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
function percent(value) { return value == null || !Number.isFinite(value) ? "N/A" : `${(100 * value).toFixed(1)}%`; }
function date(value) { return value ? new Date(value).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "—"; }
function runName(run) { return `${run.configuration?.profile === "complex" ? "Enterprise" : "Foundation"} / ${run.mode === "local" ? "Local" : "Demo"} / ${run.configuration?.policy || "strict"} · ${date(run.created_at)} · ${run.run_id.slice(0, 6)}`; }
function toast(message) { $("#toast").textContent = message; $("#toast").hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => { $("#toast").hidden = true; }, 4500); }
function error(message) { $("#global-error").textContent = message; $("#global-error").hidden = !message; }
async function api(path, body) {
  const options = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", "X-Spades-Token": state.token }, body: JSON.stringify(body) };
  const response = await fetch(path, { ...options, cache: "no-store" });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}
function view(name) {
  document.querySelectorAll(".view").forEach(node => { node.hidden = node.id !== `view-${name}`; });
  document.querySelectorAll(".nav-item").forEach(node => {
    const selected = node.dataset.view === name;
    node.classList.toggle("selected", selected);
    if (selected) node.setAttribute("aria-current", "page"); else node.removeAttribute("aria-current");
  });
  $("#breadcrumb").textContent = { overview: "Overview", experiments: "Experiments", corpus: "Scenario library", runtime: "Local runtime", presets: "Presets", bookmarks: "Bookmarks" }[name];
  window.scrollTo({ top: 0, behavior: "instant" });
  if (name === "runtime") refreshRuntime().catch(e => error(e.message));
}
function badge(text, kind = "") { return el("span", `outcome ${kind}`, text); }
function status(row) {
  if (row.error) return "error";
  if (row.secured_success) return "attack";
  if (!row.secured_utility) return "utility";
  return "passed";
}

function renderOverview() {
  const report = state.report;
  const grid = $("#metric-grid"); grid.replaceChildren();
  grid.classList.toggle("enterprise-metrics", report?.configuration?.profile === "complex");
  for (const [key, title, foot, kind] of metricsFor(report)) {
    const value = report?.metrics[key];
    const tone = value == null ? "neutral" : kind === "risk" ? (value === 0 ? "good" : "risk") : value >= 0.99 ? "good" : "attention";
    const card = el("article", `metric-card ${tone}`);
    card.append(el("span", "metric-label", title), el("div", "metric-value", percent(report?.metrics[key])), el("span", "metric-foot", foot));
    grid.append(card);
  }
  const notice = $("#mode-notice");
  $("#download-report").hidden = !report;
  $("#download-csv").hidden = !report;
  if (!report) { notice.textContent = "No evidence yet. Start a demonstration or local model experiment."; return; }
  notice.className = `notice ${report.mode === "local" ? "real" : ""}`;
  notice.textContent = report.mode === "local" ? `MEASURED LOCAL INFERENCE · ${report.model} · ${report.retrieval}. Inspect errors and grading limits before interpreting results.` : "DEMONSTRATION · Deterministic responses and lexical retrieval. These scores do not measure Qwen or any real language model.";
  if (report.status === "cancelled") notice.textContent += ` PARTIAL RUN: ${report.results.length} of ${report.planned_cases} planned cases.`;
  if (["running", "interrupted"].includes(report.status)) notice.textContent += ` ${report.status === "running" ? "LIVE CHECKPOINT" : "INTERRUPTED CHECKPOINT"}: ${report.results.length} of ${report.planned_cases} cases saved.`;
  const chart = $("#family-chart"); chart.replaceChildren();
  for (const [category, label] of Object.entries(names)) {
    if (category === "baseline") continue;
    let values = report.categories?.[category];
    if (!values) {
      const rows = report.results.filter(r => r.category === category && !r.error);
      if (!rows.length) continue;
      values = { vulnerable_asr: rows.filter(r => r.vulnerable_success).length / rows.length, secured_asr: rows.filter(r => r.secured_success).length / rows.length };
    }
    const row = el("div", "family-row"); const bars = el("div", "bar-pair");
    for (const [key, cls] of [["vulnerable_asr", "before"], ["secured_asr", "after"]]) {
      const bar = el("progress", cls); bar.max = 1; bar.value = values[key] ?? 0;
      bar.setAttribute("aria-label", `${label}, ${cls === "before" ? "vulnerable" : "secured"}: ${percent(values[key])}`);
      bars.append(bar);
    }
    const valuesLabel = el("div", "bar-values"); valuesLabel.append(el("div", "", percent(values.vulnerable_asr)), el("div", "", percent(values.secured_asr)));
    row.append(el("span", "", label), bars, valuesLabel); chart.append(row);
  }
  if (!chart.children.length) chart.append(el("p", "empty", "This run contains no completed attack cases."));
  const snapshot = $("#snapshot"); snapshot.replaceChildren();
  const m = report.metrics;
  for (const [title, value] of [
    ["Completed cases", `${m.completed_cases} / ${report.planned_cases ?? m.total_cases}`],
    ["Runtime errors", m.error_cases], ["Retrieval depth", report.configuration.retrieval_k],
    ["Trust threshold", report.configuration.trust_threshold.toFixed(2)],
    ["Defense policy", report.configuration.policy || "strict"],
    ["Evaluation profile", report.configuration.profile === "complex" ? "Enterprise / typed rubric" : "Foundation"],
    ["Async workers", report.configuration.concurrency ?? 1],
    ["Wall time", report.performance ? `${report.performance.wall_seconds.toFixed(1)} s` : "Not recorded"],
    ["Embedding cache", report.performance?.embedding_cache_enabled ? `${report.performance.embedding_cache_hits} reused vectors` : "Not recorded / disabled"],
    ["Mean case time", m.mean_seconds != null ? `${m.mean_seconds.toFixed(2)} s` : "Not recorded"],
    ["Poison retrieved", percent(m.poison_retrieval_rate)], ["Evidence created", date(report.created_at)],
  ]) { const row = el("div"); row.append(el("dt", "", title), el("dd", "", value)); snapshot.append(row); }
  $("#download-report").href = `/api/export/${report.run_id}`;
  $("#download-csv").href = `/api/csv/${report.run_id}`;
  const limits = $("#limits"); limits.replaceChildren(...report.limitations.map(text => el("li", "", text)));
  renderCases();
}

function renderCases() {
  const report = state.report; const body = $("#case-rows"); body.replaceChildren();
  if (!report) return;
  const search = $("#search").value.toLowerCase(); const category = $("#category-filter").value; const outcome = $("#outcome-filter").value;
  const rows = report.results.filter(row => (!category || row.category === category) && (!outcome || (outcome === "bookmarked" ? isBookmarked(report.run_id, row.case_id) : status(row) === outcome)) && (!search || [row.case_id, row.query, row.secured_response, row.vulnerable_response].join(" ").toLowerCase().includes(search)));
  for (const row of rows) {
    const tr = el("tr"); const first = el("td"); const button = el("button", "case-link", row.case_id.replaceAll("_", " "));
    if (isBookmarked(report.run_id, row.case_id)) { const star = el("span", "bookmark-star", "★"); star.setAttribute("aria-label", "Bookmarked: "); button.prepend(star); }
    button.addEventListener("click", () => openCase(row)); first.append(button); tr.append(first, el("td", "", names[row.category] || row.category));
    for (const arm of ["vulnerable", "secured"]) {
      const cell = el("td");
      cell.append(row.error ? badge("Error", "warn") : row.category === "baseline" ? badge("Control", "neutral") : row[`${arm}_success`] ? badge("Objective matched", "bad") : badge("Not matched")); tr.append(cell);
    }
    const utility = el("td"); utility.append(badge(row.error ? "Unmeasured" : row.secured_utility ? (row.secured_grade ? "Rubric passed" : "Fact present") : "Review", row.error || !row.secured_utility ? "warn" : ""));
    tr.append(utility, el("td", "", `${row.duration_seconds.toFixed(2)} s`)); body.append(tr);
  }
  $("#visible-count").textContent = ` / ${rows.length} of ${report.results.length}`;
  $("#ledger-empty").hidden = rows.length > 0;
}

function appendDocument(parent, chunk, decision, rank) {
  const details = el("details", "evidence-document");
  const summary = el("summary", "", `#${rank} · ${chunk.source_id} · ${decision ? `${decision.allowed ? "ALLOW" : "BLOCK"} / ${decision.reason}` : "Source document"}`);
  details.append(summary, el("p", "evidence-meta", `Chunk: ${chunk.chunk_id ?? "full document"} · Author: ${chunk.author_role} · Access: ${chunk.access} · Channel trust: ${chunk.channel_trust} · Trust score: ${decision?.trust ?? "N/A"}`), el("pre", "", chunk.text));
  if (chunk.document_hash) details.append(el("p", "evidence-meta", `SHA-256: ${chunk.document_hash}`));
  if (decision?.sanitized_text != null) details.append(el("h4", "", "Sanitized context supplied to the model"), el("pre", "", decision.sanitized_text));
  parent.append(details);
}
function openCase(row) {
  $("#case-title").textContent = row.case_id.replaceAll("_", " ");
  $("#case-eyebrow").textContent = `${names[row.category]} / CASE EVIDENCE`;
  const content = $("#case-content"); content.replaceChildren(el("p", "", row.query));
  const retest = el("button", "secondary", "Run only this scenario");
  retest.disabled = Boolean(state.active && ["running", "stopping"].includes(state.active.status));
  retest.addEventListener("click", () => {
    configureFromRun(state.report);
    selectionState.ids = new Set([row.case_id]);
    $("#run-scope").value = "selected";
    $("#case-dialog").close(); syncSelectionControls(); $("#new-dialog").showModal();
  });
  content.append(retest);
  bookmarkEditor(content, row, state.report.run_id);
  content.append(el("h3", "", row.rubric?.length ? "Reference assertions" : "Expected legitimate fact"), el("p", "subtle-note", row.expected));
  if (row.indexed_chunks) {
    const summary = el("div", "case-data-summary");
    for (const text of [`${row.document_count} records`, `${row.indexed_chunks} indexed chunks`, `${row.retrieved_ids.length} retrieved`, `${Math.round(row.corpus_characters / 1000)}k indexed characters`]) summary.append(badge(text, "neutral"));
    content.append(summary);
  }
  if (row.target) content.append(el("p", "evidence-meta", `Attack assertion target: ${row.target} · Retrieved poison rank: ${row.poison_rank ?? "not recorded / not retrieved"}`));
  if (row.error) content.append(el("pre", "error", row.error));
  else {
    const answers = el("div", "answer-grid");
    for (const arm of ["vulnerable", "secured"]) {
      const section = el("section"); let response = row[`${arm}_response`];
      if (row[`${arm}_grade`]) { try { response = JSON.stringify(JSON.parse(response), null, 2); } catch {} }
      section.append(el("h3", "", arm === "vulnerable" ? "Vulnerable response" : "Secured response"), el("p", "evidence-meta", `${row[`${arm}_seconds`] ?? "—"} s · ${row[`${arm}_success`] ? "Attack assertion matched" : "No attack assertion matched"}`), el("pre", "", response));
      if (row[`${arm}_grade`]) appendGrade(section, row[`${arm}_grade`]);
      answers.append(section);
    }
    content.append(answers, el("h3", "", "Retrieved context and defense decisions"));
    if (row.retrieved_chunks) row.retrieved_chunks.forEach((chunk, index) => appendDocument(content, chunk, row.decisions.find(d => d.chunk_id === chunk.chunk_id), index + 1));
    else row.decisions.forEach(d => content.append(el("p", "evidence-meta", `${d.chunk_id} · ${d.allowed ? "ALLOW" : "BLOCK"} · ${d.reason} · trust ${d.trust}`)));
  }
  $("#case-dialog").showModal();
}

function appendGrade(parent, grade) {
  parent.append(el("h3", "", "Field-level assessment"));
  const summary = el("div", "rubric-summary");
  for (const [label,value] of [["Field accuracy",percent(grade.field_score)],["Citation coverage",percent(grade.citation_coverage)],["Evidence coverage",percent(grade.required_source_recall)],["JSON contract",grade.format_valid ? "Valid" : "Invalid"]]) {
    const tile = el("div", "rubric-tile", label); tile.append(el("strong", "", value)); summary.append(tile);
  }
  parent.append(summary);
  const wrap = el("div", "table-scroll"), table = el("table"), head = el("thead"), header = el("tr"), body = el("tbody");
  for (const title of ["Field", "Reference", "Observed", "Result"]) { const th = el("th", "", title); th.scope = "col"; header.append(th); }
  head.append(header); table.append(head);
  for (const check of grade.checks) {
    const row = el("tr"); const verdict = el("td"); verdict.append(badge(check.passed ? "Pass" : "Fail", check.passed ? "" : "bad"));
    row.append(el("td", "", check.field), el("td", "", JSON.stringify(check.expected)), el("td", "", check.actual == null ? "Missing" : JSON.stringify(check.actual)), verdict); body.append(row);
  }
  table.append(body); wrap.append(table); parent.append(wrap);
  if (grade.format_error) parent.append(el("p", "error", `Output contract: ${grade.format_error}`));
  if (grade.missing_citations.length) parent.append(el("p", "evidence-meta", `Required citations missing: ${grade.missing_citations.join(", ")}`));
  if (grade.invalid_citations.length) parent.append(el("p", "error", `Citations outside supplied context: ${grade.invalid_citations.join(", ")}`));
}

async function loadReport(id) {
  state.report = await api(`/api/report/${id}`);
  $("#report-select").value = id;
  renderOverview();
}
async function refreshRuns(preferred) {
  const data = await api("/api/runs"); state.runs = data.runs;
  $("#run-count").textContent = state.runs.length;
  const current = preferred || state.report?.run_id || state.runs.find(run => run.mode === "local" && run.configuration?.profile === "complex")?.run_id || state.runs.find(run => run.mode === "local")?.run_id;
  for (const selector of ["#report-select", "#compare-a", "#compare-b"]) {
    const select = $(selector); const previous = select.value; select.replaceChildren();
    for (const run of state.runs) { const option = el("option", "", runName(run)); option.value = run.run_id; select.append(option); }
    if (state.runs.some(r => r.run_id === (selector === "#report-select" ? current : previous))) select.value = selector === "#report-select" ? current : previous;
  }
  if (state.runs.length > 1 && $("#compare-a").value === $("#compare-b").value) $("#compare-b").selectedIndex = 1;
  renderHistory();
  renderSourceRuns();
  if (state.runs.length) await loadReport($("#report-select").value);
  else renderOverview();
  updateProgress(data.active);
}
function renderHistory() {
  const list = $("#history-list"); list.replaceChildren();
  if (!state.runs.length) { list.append(el("p", "empty", "No experiments yet. Start your first run to save evidence.")); return; }
  for (const run of state.runs) {
    const row = el("div", "history-row"); const text = el("div");
    text.append(el("div", "history-title", runName(run)), el("div", "history-meta", `${run.metrics.completed_cases}/${run.planned_cases ?? run.metrics.total_cases} cases saved · ${run.metrics.error_cases} errors · secured ASR ${percent(run.metrics.secured_asr)} · task success ${percent(run.metrics.secured_task_success)}`));
    const actions = el("div", "history-actions"); actions.append(badge(run.status || "completed", run.status === "cancelled" ? "warn" : "neutral"));
    const open = el("button", "secondary", "Open evidence →"); open.addEventListener("click", async () => { try { await loadReport(run.run_id); view("overview"); $("#main").focus(); } catch(e) { error(e.message); } });
    actions.append(open); row.append(text, actions); list.append(row);
    const remaining = el("button", "secondary", "Run untested");
    remaining.disabled = Boolean(state.active && ["running", "stopping"].includes(state.active.status));
    remaining.addEventListener("click", () => {
      configureFromRun(run); $("#run-scope").value = "remaining"; $("#run-source").value = run.run_id;
      syncSelectionControls(); $("#new-dialog").showModal();
    });
    actions.append(remaining);
  }
}
async function compareRuns() {
  const output = $("#comparison"); output.replaceChildren();
  const aId = $("#compare-a").value, bId = $("#compare-b").value;
  if (!aId || !bId || aId === bId) { output.append(el("p", "notice", "Select two different saved experiments.")); return; }
  const [a, b] = await Promise.all([api(`/api/report/${aId}`), api(`/api/report/${bId}`)]);
  const ids = report => report.results.map(r => r.case_id).sort().join("|");
  if (a.mode !== b.mode || a.model !== b.model || ids(a) !== ids(b) || a.configuration.dataset_version !== b.configuration.dataset_version || a.configuration.grading_version !== b.configuration.grading_version) {
    output.append(el("p", "notice", "These experiments use different modes, models or scenario sets. Run both configurations with the same model and cases before comparing their aggregate scores.")); return;
  }
  const table = el("table"); const head = el("thead"), heading = el("tr");
  for (const name of ["Metric", "Reference", "Candidate", "Change"]) { const th = el("th", "", name); th.scope = "col"; heading.append(th); }
  head.append(heading); table.append(head); const body = el("tbody");
  for (const [key, label] of metricsFor(a)) {
    const row = el("tr"), av = a.metrics[key], bv = b.metrics[key], delta = av == null || bv == null ? null : 100 * (bv - av);
    row.append(el("td", "", label), el("td", "", percent(av)), el("td", "", percent(bv)), el("td", "", delta == null ? "N/A" : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)} pp`)); body.append(row);
  }
  table.append(body); output.append(el("p", "small muted", "Change is candidate minus reference in percentage points. Review task utility alongside attack and false positive rates."), table);
}

function renderCorpus() {
  const list = $("#corpus-list"); list.replaceChildren(); const query = $("#corpus-search").value.toLowerCase(), category = $("#corpus-category").value;
  const profile = $("#corpus-profile").value;
  const cases = state.corpus.filter(c => (c.profile || "foundation") === profile && (!category || c.category === category) && (!query || JSON.stringify(c).toLowerCase().includes(query)));
  for (const item of cases) {
    const card = el("article", "panel corpus-card"); card.append(el("span", "eyebrow", names[item.category]), el("h3", "", item.case_id.replaceAll("_", " ")), el("p", "", item.query), el("p", "evidence-meta", item.trusted_poison ? "Approved-channel adversarial record · provenance alone is insufficient" : item.poison ? "Unapproved payload · claimed administrator provenance" : "Approved legitimate control"));
    if (item.profile === "complex") card.append(el("p", "evidence-meta", `${item.domain} · ${2 + item.supporting.length + item.distractors.length + Boolean(item.poison)} records · ${item.rubric.length} typed field assertions · ${item.retrieval_queries.length} retrieval facets`));
    const button = el("button", "secondary", "Inspect fixture"); button.addEventListener("click", () => {
      $("#case-title").textContent = item.case_id.replaceAll("_", " "); $("#case-eyebrow").textContent = "SYNTHETIC FIXTURE / SOURCE MATERIAL";
      const content = $("#case-content"); content.replaceChildren(el("p", "", item.query), el("h3", "", "Legitimate document")); appendDocument(content, item.legitimate, null, 1);
      (item.supporting || []).forEach((doc, i) => appendDocument(content, doc, null, i + 2));
      if (item.poison) { content.append(el("h3", "", "Poisoned document")); appendDocument(content, item.poison, null, 2); }
      if (item.distractors?.length) { const distractors = el("details", "evidence-document"); distractors.append(el("summary", "", `${item.distractors.length} archived and out-of-scope distractor records`)); item.distractors.forEach((doc,i) => appendDocument(distractors,doc,null,i+1)); content.append(distractors); }
      content.append(el("p", "subtle-note", `Expected fact: ${item.expected}`)); $("#case-dialog").showModal();
    }); card.append(button); list.append(card);
  }
  if (!cases.length) list.append(el("p", "empty", "No scenarios match your search."));
}

function isBookmarked(runId, caseId) {
  return state.workspace.bookmarks.some(b => b.run_id === runId && b.case_id === caseId);
}
function currentConfig() {
  const scope = $("#run-scope").value;
  return { mode: $("#run-mode").value, threshold: Number($("#run-threshold").value), k: Number($("#run-k").value), limit: ["all", "selected"].includes(scope) ? 6 : Number($("#run-limit").value), category: $("#run-category").value, policy: $("#run-policy").value, profile: $("#run-profile").value,
           domain: $("#run-domain").value, concurrency: Number($("#run-concurrency").value), selection_scope: scope,
           case_ids: scope === "selected" ? [...selectionState.ids] : null,
           source_run_id: ["remaining", "errors"].includes(scope) ? $("#run-source").value || null : null };
}

function renderDomainOptions() {
  const select = $("#run-domain"), previous = select.value;
  const domains = [...new Set(state.corpus.filter(c => (c.profile || "foundation") === $("#run-profile").value).map(c => c.domain || c.case_id.split("-")[0]))];
  select.replaceChildren(el("option", "", "All domains")); select.firstElementChild.value = "";
  for (const domain of domains) { const option = el("option", "", domain.charAt(0).toUpperCase() + domain.slice(1)); option.value = domain; select.append(option); }
  if (domains.includes(previous)) select.value = previous;
}

function pickerCases(includeSearch=true) {
  const profile = $("#run-profile").value, domain = $("#run-domain").value, family = $("#run-category").value;
  const query = includeSearch ? $("#scenario-search").value.trim().toLowerCase() : "";
  return state.corpus.filter(c => (c.profile || "foundation") === profile && (!domain || (c.domain || c.case_id.split("-")[0]) === domain) && (!family || c.category === family) && (!query || [c.case_id, c.domain, c.query].join(" ").toLowerCase().includes(query)));
}

function renderScenarioPicker() {
  const valid = new Set(pickerCases(false).map(c => c.case_id));
  selectionState.ids = new Set([...selectionState.ids].filter(id => valid.has(id)));
  const choices = pickerCases(), list = $("#scenario-options"); list.replaceChildren();
  for (const c of choices) {
    const label = el("label", "scenario-choice"), input = el("input");
    input.type = "checkbox"; input.checked = selectionState.ids.has(c.case_id);
    input.setAttribute("aria-label", c.case_id);
    input.addEventListener("change", () => {
      if (input.checked) selectionState.ids.add(c.case_id); else selectionState.ids.delete(c.case_id);
      $("#scenario-count").textContent = `${selectionState.ids.size} selected · ${choices.length} visible`;
      queueSelectionPreview();
    });
    const text = el("span", "scenario-choice-text");
    text.append(el("strong", "", c.case_id), el("span", "evidence-meta", `${c.domain || c.case_id.split("-")[0]} · ${names[c.category]}`));
    label.title = c.query; label.append(input, text); list.append(label);
  }
  if (!choices.length) list.append(el("p", "empty", "No scenarios match these filters."));
  $("#scenario-count").textContent = `${selectionState.ids.size} selected · ${choices.length} visible`;
}

function renderSourceRuns() {
  const select = $("#run-source"), previous = select.value;
  select.replaceChildren(el("option", "", "Choose an experiment")); select.firstElementChild.value = "";
  for (const run of state.runs) {
    const option = el("option", "", `${runName(run)} · ${run.metrics.completed_cases} completed`);
    option.value = run.run_id; select.append(option);
  }
  if (state.runs.some(r => r.run_id === previous)) select.value = previous;
}

function configureFromRun(run) {
  const c = run.configuration;
  $("#run-profile").value = c.profile || "foundation";
  $("#run-mode").value = run.mode;
  $("#run-policy").value = c.policy || "strict";
  $("#run-k").value = c.retrieval_k;
  $("#run-threshold").value = c.trust_threshold;
  $("#run-limit").value = 6;
  $("#run-concurrency").value = 2;
  $("#run-scope").value = "sample";
  renderDomainOptions(); $("#run-domain").value = c.domain || "";
  $("#run-category").value = c.category || "";
  $("#run-preset").value = ""; $("#run-error").textContent = "";
  $("#run-source").value = run.run_id;
  selectionState.ids.clear();
}

function syncSelectionControls() {
  const scope = $("#run-scope").value;
  $("#scenario-picker").hidden = scope !== "selected";
  $("#batch-size-field").hidden = ["all", "selected"].includes(scope);
  $("#run-limit").disabled = $("#batch-size-field").hidden;
  $("#source-run-field").hidden = !["remaining", "errors"].includes(scope);
  renderScenarioPicker(); queueSelectionPreview();
}

function queueSelectionPreview() {
  clearTimeout(selectionState.previewTimer);
  const revision = ++selectionState.previewRevision;
  $("#selection-preview").textContent = "Checking scenario selection…";
  $("#launch-run").disabled = true;
  $("#launch-run").textContent = "Checking selection…";
  selectionState.previewTimer = setTimeout(async () => {
    const preview = $("#selection-preview");
    try {
      const data = await api("/api/selection", currentConfig());
      if (revision !== selectionState.previewRevision) return;
      const workers = Math.min(Number($("#run-concurrency").value), data.count);
      preview.textContent = `${data.count} scenario${data.count === 1 ? "" : "s"} · ${data.model_requests} model responses · up to ${workers} concurrent scenario${workers === 1 ? "" : "s"}${data.previous_count ? ` · ${data.previous_count} already tested cases excluded` : ""}.`;
      preview.classList.remove("invalid");
      $("#launch-run").disabled = false;
      $("#launch-run").textContent = `Run ${data.count} scenario${data.count === 1 ? "" : "s"} →`;
    } catch(e) {
      if (revision !== selectionState.previewRevision) return;
      preview.textContent = e.message; preview.classList.add("invalid"); $("#launch-run").disabled = true;
    }
  }, 180);
}
function applyPreset(id) {
  const preset = state.workspace.presets.find(p => p.id === id);
  if (!preset) return;
  $("#run-profile").value = preset.config.profile || "foundation";
  renderDomainOptions();
  $("#run-scope").value = preset.config.selection_scope || "sample";
  $("#run-concurrency").value = preset.config.concurrency || 2;
  $("#run-source").value = preset.config.source_run_id || "";
  selectionState.ids = new Set(preset.config.case_ids || []);
  for (const [key, value] of Object.entries(preset.config)) {
    const selector = { mode: "#run-mode", threshold: "#run-threshold", k: "#run-k", limit: "#run-limit", category: "#run-category", policy: "#run-policy", profile: "#run-profile", domain: "#run-domain" }[key];
    if (selector) $(selector).value = value ?? "";
  }
  $("#preset-name").value = "";
  $("#run-error").textContent = "";
  $("#run-preset").value = id;
  if (!preset.config.selection_scope) $("#run-limit").value = Math.min(preset.config.limit || 6, 6);
  syncSelectionControls();
}
function updateWorkspace(data) {
  state.workspace = data;
  renderPresets();
  renderBookmarks();
  renderCases();
}
function renderPresets() {
  $("#preset-count").textContent = state.workspace.presets.length;
  const selected = $("#run-preset").value;
  $("#run-preset").replaceChildren(el("option", "", "Custom configuration"));
  $("#run-preset").firstElementChild.value = "";
  const list = $("#preset-list"); list.replaceChildren();
  for (const preset of state.workspace.presets) {
    const option = el("option", "", preset.name); option.value = preset.id; $("#run-preset").append(option);
    const card = el("article", "panel corpus-card"); const c = preset.config;
    card.append(el("span", "preset-tag", preset.builtin ? "BUILT-IN" : "YOUR PRESET"), el("h3", "", preset.name), el("p", "", `${c.mode === "local" ? "Real local model" : "Demonstration"} · ${c.policy} · up to ${c.limit} cases`), el("p", "evidence-meta", `${c.profile === "complex" ? "Enterprise" : "Foundation"} · Trust ≥ ${c.threshold.toFixed(2)} · top ${c.k} chunks · ${names[c.category] || "All families"}`));
    const actions = el("div", "preset-actions");
    const use = el("button", "secondary use-preset", "Use preset →");
    use.disabled = Boolean(state.active && ["running", "stopping"].includes(state.active.status));
    use.addEventListener("click", () => { applyPreset(preset.id); $("#new-dialog").showModal(); });
    actions.append(use);
    if (!preset.builtin) {
      const remove = el("button", "secondary", "Remove");
      remove.setAttribute("aria-label", `Remove preset ${preset.name}`);
      remove.addEventListener("click", async () => { try { updateWorkspace(await api("/api/preset/remove", { id: preset.id })); toast("Preset removed."); } catch(e) { error(e.message); } });
      actions.append(remove);
    }
    card.append(actions); list.append(card);
  }
  if (state.workspace.presets.some(p => p.id === selected)) $("#run-preset").value = selected;
}
function bookmarkEditor(parent, row, runId) {
  const existing = state.workspace.bookmarks.find(b => b.run_id === runId && b.case_id === row.case_id);
  const section = el("section", "bookmark-editor"); section.append(el("h3", "", "Bookmark and review notes"));
  const label = el("label", "", "Your observations (up to 2,000 characters)"); label.htmlFor = "case-note";
  const note = el("textarea"); note.id = "case-note"; note.maxLength = 2000; note.value = existing?.note || "";
  note.placeholder = "Record why this case matters or what needs further review…";
  const actions = el("div", "bookmark-actions");
  const save = el("button", "secondary", existing ? "Save note" : "☆ Bookmark case");
  const remove = el("button", "secondary", "Remove bookmark"); remove.hidden = !existing;
  const message = el("p", "error"); message.setAttribute("role", "alert");
  const persist = async saved => {
    save.disabled = true; remove.disabled = true; message.textContent = "";
    try {
      updateWorkspace(await api("/api/bookmark", { run_id: runId, case_id: row.case_id, saved, note: note.value }));
      save.textContent = saved ? "Save note" : "☆ Bookmark case"; remove.hidden = !saved;
      toast(saved ? "Bookmark and notes saved locally." : "Bookmark removed.");
    } catch(e) { message.textContent = e.message; }
    finally { save.disabled = false; remove.disabled = false; }
  };
  save.addEventListener("click", () => persist(true)); remove.addEventListener("click", () => persist(false));
  actions.append(save, remove); section.append(label, note, actions, message); parent.append(section);
}
function renderBookmarks() {
  $("#bookmark-count").textContent = state.workspace.bookmarks.length;
  const list = $("#bookmark-list"); list.replaceChildren(); const query = $("#bookmark-search").value.toLowerCase();
  const bookmarks = state.workspace.bookmarks.filter(b => [b.case_id, b.query, b.note].join(" ").toLowerCase().includes(query)).slice().sort((a,b) => b.updated_at.localeCompare(a.updated_at));
  if (!bookmarks.length) { list.append(el("p", "bookmark-empty muted", state.workspace.bookmarks.length ? "No bookmarks match your search." : "No bookmarks yet. Open a case in the experiment ledger to save it with your notes.")); return; }
  for (const bookmark of bookmarks) {
    const card = el("article", "panel bookmark-card");
    card.append(el("span", "eyebrow", names[bookmark.category] || bookmark.category), el("h3", "", `★ ${bookmark.case_id.replaceAll("_", " ")}`), el("p", "", bookmark.query), el("p", "small muted", `Run ${bookmark.run_id.slice(0,8)} · saved ${date(bookmark.updated_at)}`));
    if (bookmark.note) card.append(el("p", "subtle-note bookmark-note", bookmark.note));
    const open = el("button", "secondary", "Open original evidence →");
    open.addEventListener("click", async () => {
      try {
        await loadReport(bookmark.run_id);
        const row = state.report.results.find(r => r.case_id === bookmark.case_id);
        if (!row) throw new Error("This case is no longer present in the saved report.");
        openCase(row);
      } catch(e) { error(e.message); }
    });
    const actions = el("div", "bookmark-actions"); actions.append(open); card.append(actions); list.append(card);
  }
}

async function refreshRuntime() {
  const runtime = await api("/api/runtime"); const pill = $("#runtime-pill"); pill.textContent = runtime.ready ? "● Local runtime ready" : "○ Local setup needed"; pill.classList.toggle("warning", !runtime.ready);
  const list = $("#runtime-components"); list.replaceChildren();
  for (const [name, subtitle, ready, detail] of [
    ["Ollama engine", "Loopback inference service", runtime.ollama, "127.0.0.1:11434"],
    ["ChromaDB", "Persistent vector retrieval", runtime.chromadb, "Local embeddings · telemetry disabled"],
    ["Model weights", "Qwen2.5 + nomic-embed-text", runtime.ready, runtime.models.join(" · ") || "No installed models found"],
  ]) { const card = el("article", "panel runtime-card"); card.append(el("span", "eyebrow", subtitle), el("h2", "", name), el("p", "", detail), el("div", `runtime-status ${ready ? "" : "off"}`, ready ? "● Available locally" : "○ Preparation required")); list.append(card); }
  $("#runtime-error").textContent = runtime.error || "All experiment requests stay on loopback. Preparing model weights requires internet access once.";
  $("#run-mode").querySelector('option[value="local"]').disabled = !runtime.ready;
}

function updateProgress(active) {
  state.active = active; const running = active && ["running", "stopping"].includes(active.status);
  $("#active-job").hidden = !running;
  document.querySelectorAll(".new-run,.use-preset").forEach(button => { button.disabled = Boolean(running); });
  if (running) {
    $("#job-mode").textContent = `${active.mode === "local" ? "REAL LOCAL MODEL" : "SIMULATED DEMONSTRATION"} / ${active.status.toUpperCase()}`;
    $("#job-label").textContent = `${active.completed} of ${active.total} scenarios complete`;
    $("#job-progress").max = active.total; $("#job-progress").value = active.completed;
    const live = active.in_flight || [];
    const text = active.status === "stopping" ? "No more cases will start. Active cases will finish and completed evidence will stay saved." : `${live.length} running · ${Math.max(0, active.total - active.completed - live.length)} queued · ${active.concurrency || 1} worker limit`;
    if ($("#job-status").textContent !== text) $("#job-status").textContent = text;
    const phases = { retrieval: "Retrieving evidence", vulnerable_generation: "Generating vulnerable response", secured_generation: "Generating secured response", grading: "Grading response" };
    $("#job-activity").replaceChildren(...live.map(item => el("li", "", `${item.case_id} — ${phases[item.phase] || item.phase}`)));
    $("#live-evidence").disabled = active.completed === 0;
    $("#live-evidence").textContent = `View completed results (${active.completed})`;
    $("#stop-run").disabled = active.status === "stopping";
  }
}
async function poll() {
  try {
    const { active } = await api("/api/progress"); updateProgress(active);
    if (active && ["running", "stopping"].includes(active.status) && state.report?.run_id === active.run_id && state.report.results.length !== active.completed) await loadReport(active.run_id);
    if (active && !["running", "stopping"].includes(active.status) && state.handled !== active.run_id) {
      state.handled = active.run_id;
      if (active.status === "failed") error(active.error || "Experiment failed.");
      else { await refreshRuns(active.run_id); toast(active.status === "cancelled" ? "Experiment stopped. Partial evidence saved." : "Experiment complete. Evidence saved."); }
    }
  } catch (e) { error(`Dashboard connection unavailable: ${e.message}. Restart the Spades server if needed.`); }
  finally { setTimeout(poll, state.active && ["running", "stopping"].includes(state.active.status) ? 1200 : 4000); }
}

document.querySelectorAll(".nav-item").forEach(button => button.addEventListener("click", () => view(button.dataset.view)));
document.querySelectorAll(".new-run").forEach(button => button.addEventListener("click", () => { $("#run-error").textContent = ""; syncSelectionControls(); $("#new-dialog").showModal(); }));
document.querySelectorAll(".close-dialog").forEach(button => button.addEventListener("click", () => button.closest("dialog").close()));
for (const selector of ["#category-filter", "#run-category", "#corpus-category"]) {
  for (const [value, name] of Object.entries(names)) { const option = el("option", "", name); option.value = value; $(selector).append(option); }
}
for (const selector of ["#search", "#category-filter", "#outcome-filter"]) $(selector).addEventListener("input", renderCases);
for (const selector of ["#corpus-search", "#corpus-category", "#corpus-profile"]) $(selector).addEventListener("input", renderCorpus);
$("#report-select").addEventListener("change", () => loadReport($("#report-select").value).catch(e => error(e.message)));
$("#refresh-history").addEventListener("click", () => refreshRuns().catch(e => error(e.message)));
$("#refresh-runtime").addEventListener("click", () => refreshRuntime().catch(e => error(e.message)));
$("#compare-button").addEventListener("click", () => compareRuns().catch(e => error(e.message)));
$("#run-preset").addEventListener("change", () => applyPreset($("#run-preset").value));
for (const id of ["run-mode", "run-policy", "run-threshold", "run-k", "run-limit", "run-category", "run-profile", "run-domain", "run-scope", "run-concurrency"]) {
  document.getElementById(id).addEventListener("input", () => { $("#run-preset").value = ""; queueSelectionPreview(); });
}
$("#run-scope").addEventListener("change", syncSelectionControls);
for (const id of ["run-domain", "run-category"]) document.getElementById(id).addEventListener("change", syncSelectionControls);
$("#scenario-search").addEventListener("input", renderScenarioPicker);
$("#select-visible").addEventListener("click", () => { pickerCases().forEach(c => selectionState.ids.add(c.case_id)); renderScenarioPicker(); queueSelectionPreview(); });
$("#clear-scenarios").addEventListener("click", () => { selectionState.ids.clear(); renderScenarioPicker(); queueSelectionPreview(); });
$("#run-source").addEventListener("change", () => {
  const run = state.runs.find(r => r.run_id === $("#run-source").value), scope = $("#run-scope").value;
  if (run) { configureFromRun(run); $("#run-scope").value = scope; syncSelectionControls(); }
});
$("#run-profile").addEventListener("change", () => {
  const complex = $("#run-profile").value === "complex";
  $("#run-limit").value = 6;
  $("#run-k").value = complex ? 16 : 5;
  $("#profile-description").textContent = complex ? "Enterprise cases retain 21–23 records and typed grading. Six cases are sampled by default; choose exact cases or explicitly select all." : "Foundation cases use short documents and lightweight assertions. Six cases are sampled by default.";
  selectionState.ids.clear(); $("#run-category").value = ""; $("#run-domain").value = "";
  renderDomainOptions(); syncSelectionControls();
});
$("#bookmark-search").addEventListener("input", renderBookmarks);
$("#save-preset").addEventListener("click", async () => {
  const button = $("#save-preset"); button.disabled = true; $("#run-error").textContent = "";
  try {
    const name = $("#preset-name").value.trim();
    const data = await api("/api/preset", { name, config: currentConfig() });
    updateWorkspace(data);
    $("#run-preset").value = data.presets.find(p => p.name === name)?.id || "";
    $("#preset-name").value = ""; toast("Preset saved. Reuse it from the Presets page.");
  } catch(e) { $("#run-error").textContent = e.message; }
  finally { button.disabled = false; }
});
$("#stop-run").addEventListener("click", () => api("/api/stop", {}).then(updateProgress).catch(e => error(e.message)));
$("#live-evidence").addEventListener("click", () => { if (state.active) refreshRuns(state.active.run_id).then(() => view("overview")).catch(e => error(e.message)); });
$("#run-form").addEventListener("submit", async event => {
  event.preventDefault(); const button = $("#launch-run"); button.disabled = true; $("#run-error").textContent = "";
  try {
    const config = currentConfig();
    const active = await api("/api/run", config); updateProgress(active); $("#new-dialog").close(); error("");
    toast("Experiment started. You can continue inspecting saved evidence.");
  } catch (e) { $("#run-error").textContent = e.message; }
  finally { button.disabled = false; }
});

async function boot() {
  state.token = (await api("/api/session")).token;
  await Promise.all([refreshRuns(), refreshRuntime(), api("/api/workspace").then(updateWorkspace), api("/api/corpus").then(data => { state.corpus = data.cases; renderCorpus(); renderDomainOptions(); renderScenarioPicker(); })]);
  syncSelectionControls();
  poll();
}
boot().catch(e => error(e.message));
