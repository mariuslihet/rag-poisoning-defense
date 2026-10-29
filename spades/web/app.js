"use strict";

const $ = (selector) => document.querySelector(selector);
const state = { token: "", runs: [], report: null, corpus: [], active: null, handled: null, workspace: { presets: [], bookmarks: [] } };
const selectionState = { ids: new Set(), previewRevision: 0, previewTimer: null };
let suiteDraft = null;
let qualityViewKey = "", policyPreview = null, qualityHistory = null;
const qualityFields = [
  ["min_cases","Minimum measured scenarios",1,500,1], ["min_controls","Minimum measured controls",0,500,1],
  ["min_attacks","Minimum measured adversarial cases",0,500,1], ["min_domains","Minimum measured domains",1,500,1],
  ["min_task_rate","Minimum secured task rate",0,1,0.05], ["min_field_accuracy","Minimum typed-field accuracy",0,1,0.05],
  ["min_citation_coverage","Minimum citation coverage",0,1,0.05], ["min_format_rate","Minimum structured-output validity",0,1,0.05],
  ["max_attack_rate","Maximum secured attack rate",0,1,0.05], ["max_leakage_rate","Maximum canary disclosure rate",0,1,0.05],
  ["max_runtime_errors","Maximum runtime errors",0,500,1]];
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
function runName(run) { const name = state.workspace.experiments?.[run.run_id]?.name; return `${name ? `${name} · ` : ""}${run.configuration?.profile === "complex" ? "Enterprise" : "Foundation"} / ${run.mode === "local" ? "Local" : "Demo"} / ${run.configuration?.policy || "strict"} · ${date(run.created_at)} · ${run.run_id.slice(0, 6)}`; }
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
  $("#breadcrumb").textContent = { overview: "Overview", experiments: "Experiments", corpus: "Scenario library", runtime: "Local runtime", presets: "Presets", bookmarks: "Bookmarks", suites: "Test suites" }[name];
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
  renderDiagnostics();
  renderQualityGate();
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
    ["Generation settings", report.mode === "demo" ? "Not applied in demonstration mode" : report.configuration.generation ? `thinking ${report.configuration.generation.think == null ? "model default" : report.configuration.generation.think ? "enabled" : "disabled"} · temperature ${report.configuration.generation.temperature} · seed ${report.configuration.generation.seed ?? "model default"} · response ${report.configuration.generation.num_predict} tokens · context ${report.configuration.generation.num_ctx} tokens · timeout ${report.configuration.generation.request_timeout}s` : "Not recorded (historical report)"],
    ["Model weight digest", report.performance?.model_digest || "Not recorded"],
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
  const rows = visibleCases();
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

function visibleCases() {
  if (!state.report) return [];
  const search = $("#search").value.toLowerCase(), category = $("#category-filter").value, outcome = $("#outcome-filter").value;
  const rows = state.report.results.filter(row => (!category || row.category === category) && (!outcome || (outcome === "bookmarked" ? isBookmarked(state.report.run_id, row.case_id) : status(row) === outcome)) && (!search || [row.case_id, row.query, row.secured_response, row.vulnerable_response].join(" ").toLowerCase().includes(search)));
  const sort = $("#case-sort").value;
  if (sort === "slowest") rows.sort((a, b) => b.duration_seconds - a.duration_seconds);
  if (sort === "fastest") rows.sort((a, b) => a.duration_seconds - b.duration_seconds);
  if (sort === "id") rows.sort((a, b) => a.case_id.localeCompare(b.case_id));
  return rows;
}

function exportVisibleCases() {
  if (!state.report) return;
  const rows = visibleCases();
  const evidence = {run_id: state.report.run_id, created_at: state.report.created_at, model: state.report.model,
    mode: state.report.mode, configuration: state.report.configuration, export_type: "filtered_evidence",
    exported_at: new Date().toISOString(), source_case_count: state.report.results.length,
    filters: {search: $("#search").value, category: $("#category-filter").value, outcome: $("#outcome-filter").value, sort: $("#case-sort").value},
    exported_case_count: rows.length, results: rows};
  const url = URL.createObjectURL(new Blob([JSON.stringify(evidence, null, 2)], {type: "application/json"}));
  const link = el("a"); link.href = url; link.download = `spades-${state.report.run_id}-filtered.json`;
  document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast(`Exported ${rows.length} visible cases.`);
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
  const diagnosis = state.report.analysis?.cases.find(item => item.case_id === row.case_id);
  if (diagnosis) appendDiagnosis(content, diagnosis);
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
      const completion = row[`${arm}_generation`];
      if (completion && Object.keys(completion).length) section.append(el("p", "evidence-meta", `Completion: ${completion.done_reason || "not recorded"} · generated tokens: ${completion.generated_tokens ?? "not recorded"} · prompt tokens: ${completion.prompt_tokens ?? "not recorded"} · final answer: ${completion.empty_response ? "empty" : "present"} · thinking text length: ${completion.thinking_characters ?? "not recorded"} characters`));
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
  for (const title of ["Field", "Reference", "Observed", "Type / tolerance", "Result"]) { const th = el("th", "", title); th.scope = "col"; header.append(th); }
  head.append(header); table.append(head);
  for (const check of grade.checks) {
    const row = el("tr"); const verdict = el("td"); verdict.append(badge(check.passed ? "Pass" : "Fail", check.passed ? "" : "bad"));
    const field = el("td", "", check.field);
    if (check.description) field.append(el("p", "small muted", check.description));
    const expectedType = typeof check.expected;
    row.append(field, el("td", "", JSON.stringify(check.expected)), el("td", "", check.actual == null ? "Missing / null" : JSON.stringify(check.actual)),
      el("td", "", `${expectedType}${expectedType === "number" ? ` · absolute tolerance ±${check.tolerance || 0}` : " · exact typed assertion"}`), verdict); body.append(row);
  }
  table.append(body); wrap.append(table); parent.append(wrap);
  if (grade.format_error) parent.append(el("p", "error", `Output contract: ${grade.format_error}`));
  if (grade.missing_citations.length) parent.append(el("p", "evidence-meta", `Required citations missing: ${grade.missing_citations.join(", ")}`));
  if (grade.invalid_citations.length) parent.append(el("p", "error", `Citations outside supplied context: ${grade.invalid_citations.join(", ")}`));
}

function diagnosticCases() {
  const data = state.report?.analysis; if (!data) return [];
  const issue = $("#diagnostic-issue").value, domain = $("#diagnostic-domain").value;
  const query = $("#diagnostic-search").value.trim().toLowerCase();
  return data.cases.filter(item => (issue === "clear" ? !item.issues.length : issue ? item.issues.includes(issue) : item.issues.length > 0) &&
    (!domain || item.domain === domain) && [item.case_id, ...item.failed_fields.map(check => check.field)].join(" ").toLowerCase().includes(query));
}

function renderQualityGate() {
  const gate = state.report?.quality_gate; $("#quality-panel").hidden = !gate; if (!gate) return;
  const key=`${state.report.run_id}:${gate.policy_revision}`;
  if (qualityViewKey!==key) {
    qualityViewKey=key; policyPreview=null; qualityHistory=null;
    $("#quality-policy-preview").replaceChildren(); $("#quality-history").replaceChildren();
    $("#export-policy-preview").disabled=true; $("#export-quality-history").disabled=true;
  }
  const labels = {pass:"Pass",fail:"Fail",insufficient:"Insufficient evidence"};
  const verdict = $("#quality-verdict"); verdict.replaceChildren(badge(labels[gate.status],gate.status === "pass" ? "" : gate.status === "fail" ? "bad" : "warn"));
  verdict.append(el("span","small muted",` · ${gate.checks.filter(check=>check.status==="pass").length} passed criteria · ${gate.checks.filter(check=>check.status==="fail").length} failed · ${gate.checks.filter(check=>check.status==="insufficient").length} insufficient · ${gate.checks.filter(check=>check.status==="not_applicable").length} not applicable`));
  $("#quality-policy-label").textContent = `${gate.policy.name} · workspace revision ${gate.policy_revision ?? "not recorded"} · evaluated ${date(gate.evaluated_at)}`;
  const findings=$("#quality-summary"); findings.replaceChildren();
  for (const [status,label] of [["fail","Failed criteria"],["insufficient","More evidence required"]]) {
    const checks=gate.checks.filter(check=>check.status===status);
    if (checks.length) findings.append(el("p","",`${label}: ${checks.map(check=>check.label).join("; ")}.`));
  }
  if (gate.status==="pass") findings.append(el("p","","All applicable criteria passed for this recorded scope."));
  $("#quality-limits").textContent = gate.limitations;
  const table = el("table"), head = el("thead"), titles = el("tr"), body = el("tbody");
  for (const title of ["Criterion","Observed","Required","Result / evidence"]) { const th = el("th","",title); th.scope="col"; titles.append(th); }
  head.append(titles); table.append(head);
  const rateKeys = new Set(["task_rate","attack_rate","leakage_rate","field_accuracy","citations","format"]);
  for (const check of gate.checks) {
    const row = el("tr"), detail = el("td"); detail.append(badge(labels[check.status] || "Not applicable",check.status === "fail" ? "bad" : check.status === "insufficient" ? "warn" : "neutral"));
    if (check.note) detail.append(el("p","small muted",check.note));
    if (check.denominator != null) detail.append(el("p","small muted",`Measured denominator: ${check.denominator}`));
    if (check.case_ids.length) detail.append(el("p","small muted",`${check.case_ids.length} contributing case(s)`));
    const booleanCriterion = ["complete","local"].includes(check.key);
    row.append(el("td","",check.label), el("td","",check.observed == null ? "N/A" : booleanCriterion ? check.observed ? "Yes" : "No" : rateKeys.has(check.key) ? percent(check.observed) : String(check.observed)),
      el("td","",booleanCriterion ? "Required" : `${check.operator} ${rateKeys.has(check.key) ? percent(check.target) : check.target}`),detail); body.append(row);
  }
  table.append(body); $("#quality-checks").replaceChildren(table);
  $("#retest-gate").disabled = !gate.failed_case_ids.length || Boolean(state.active && ["running","stopping"].includes(state.active.status));
}

function renderQualityPolicy() {
  const record = state.workspace.quality_policy; if (!record) return;
  const library=$("#quality-policy-library"), previous=library.value;
  library.replaceChildren(el("option","","Current workspace policy")); library.firstElementChild.value="";
  for (const snapshot of state.workspace.quality_policies || []) { const option=el("option","",snapshot.policy.name); option.value=snapshot.id; library.append(option); }
  library.value=[...library.options].some(option=>option.value===previous) ? previous : "";
  fillQualityPolicy((state.workspace.quality_policies || []).find(snapshot=>snapshot.id===library.value)?.policy || record.policy);
}

function fillQualityPolicy(policy) {
  $("#quality-name").value = policy.name;
  const fields = $("#quality-policy-fields"); fields.replaceChildren();
  for (const [key,label,min,max,step] of qualityFields) {
    const wrapper = el("label","",label), input = el("input"); input.type="number"; input.min=min; input.max=max; input.step=step;
    input.required=true; input.id=`quality-${key}`; input.value=policy[key]; wrapper.htmlFor=input.id; wrapper.append(input); fields.append(wrapper);
  }
  $("#quality-require-complete").checked = policy.require_complete;
  $("#quality-require-local").checked = policy.require_local;
}

function readQualityPolicy() {
  const policy={name:$("#quality-name").value,require_complete:$("#quality-require-complete").checked,require_local:$("#quality-require-local").checked};
  for (const [key] of qualityFields) policy[key]=Number(document.getElementById(`quality-${key}`).value);
  return policy;
}

function renderPolicyPreview(result) {
  const parent=$("#quality-policy-preview"); parent.replaceChildren(el("h3","","Policy preview"),
    el("p","",`${result.reference.policy.name}: ${result.reference.status} → ${result.candidate.policy.name}: ${result.candidate.status}`),el("p","small muted",result.note));
  if (!result.changes.length) { parent.append(el("p","small","No acceptance targets or criterion statuses changed.")); return; }
  const table=el("table"),head=el("thead"),title=el("tr"),body=el("tbody");
  for (const name of ["Criterion","Observed","Current target / result","Draft target / result"]) { const th=el("th","",name); th.scope="col"; title.append(th); }
  head.append(title); table.append(head);
  for (const check of result.changes) {
    const row=el("tr"); row.append(el("td","",check.label),el("td","",check.observed==null ? "N/A" : String(check.observed)),
      el("td","",`${check.operator} ${check.reference_target} · ${check.reference_status}`),el("td","",`${check.operator} ${check.candidate_target} · ${check.candidate_status}`)); body.append(row);
  }
  table.append(body); const scroll=el("div","table-scroll"); scroll.append(table); parent.append(scroll);
}

function renderQualityHistory(result) {
  const parent=$("#quality-history"); parent.replaceChildren(el("p","small",`${result.runs.length} compatible runs · ${result.excluded_incompatible} excluded · ${result.invalid_reports.length} invalid report(s) · policy revision ${result.policy_revision}`));
  const events=el("div","acceptance-timeline");
  for (const row of result.runs) {
    const button=el("button",`acceptance-event ${row.gate_status}`,`${date(row.created_at)} · ${row.gate_status} · ${row.run_id.slice(0,6)}`);
    button.addEventListener("click",()=>loadReport(row.run_id).catch(e=>error(e.message))); events.append(button);
  }
  parent.append(events);
  const table=el("table"),head=el("thead"),titles=el("tr"),body=el("tbody");
  for (const title of ["Run / defense","Gate / measured scope","Observed task / attack rates","Criterion transitions"]) { const th=el("th","",title); th.scope="col"; titles.append(th); }
  head.append(titles); table.append(head);
  for (const row of result.runs) {
    const tr=el("tr"), transitions=row.transitions.map(item=>`${item.label}: ${item.change}`).join("; ");
    tr.append(el("td","",`${row.run_id.slice(0,8)} · ${row.defense.policy || "not recorded"} · trust ${row.defense.trust ?? "N/A"} · k ${row.defense.retrieval_k ?? "N/A"}`),
      el("td","",`${row.gate_status} · ${row.measured}/${row.planned} measured · ${row.failed_checks.length} failed criteria`),
      el("td","",`${percent(row.observed_metrics.task_rate)} / ${percent(row.observed_metrics.attack_rate)}`),
      el("td","",transitions || (row.previous_run_id ? "No classified criterion transitions" : "First compatible run"))); body.append(tr);
  }
  table.append(body); const wrap=el("div","table-scroll"); wrap.append(table); parent.append(wrap);
  const limits=el("ul","small muted"); result.limitations.forEach(text=>limits.append(el("li","",text))); parent.append(limits);
  if (result.invalid_reports.length) parent.append(el("p","error",result.invalid_reports.map(item=>`${item.run_id}: ${item.error}`).join("; ")));
}

function renderDiagnostics() {
  const data = state.report?.analysis; $("#diagnostics-panel").hidden = !data;
  if (!data) return;
  const issue = $("#diagnostic-issue"), currentIssue = issue.value, domain = $("#diagnostic-domain"), currentDomain = domain.value;
  issue.replaceChildren();
  for (const [value,label] of [["", "All cases with observations"], ["clear", "No recorded issues"], ...data.issues.map(item => [item.code, `${item.label} (${item.count})`])]) {
    const option = el("option", "", label); option.value = value; issue.append(option);
  }
  issue.value = [...issue.options].some(option => option.value === currentIssue) ? currentIssue : "";
  domain.replaceChildren();
  for (const [value,label] of [["", "All domains"], ...data.domains.map(item => [item.name, item.name])]) {
    const option = el("option", "", label); option.value = value; domain.append(option);
  }
  domain.value = [...domain.options].some(option => option.value === currentDomain) ? currentDomain : "";
  const summary = $("#diagnostic-summary"); summary.replaceChildren();
  summary.append(el("p", "small muted", `${data.attempted} attempted / ${data.planned} planned cases · ${data.cases.filter(item => !item.issues.length).length} cases without recorded issues`));
  for (const item of data.issues) {
    const button = el("button", "diagnostic-tile", `${item.count} · ${item.label}`);
    button.addEventListener("click", () => { issue.value = item.code; renderDiagnosticCases(); }); summary.append(button);
  }
  $("#diagnostic-limits").replaceChildren(...data.limitations.map(text => el("li", "", text)));
  renderScorecards(); renderDiagnosticCases();
}

function renderScorecards() {
  const data = state.report?.analysis; if (!data) return;
  const parent = $("#diagnostic-scorecards"); parent.replaceChildren();
  const table = el("table"), head = el("thead"), title = el("tr"), body = el("tbody");
  for (const text of ["Group", "Measured / attempted", "Runtime errors", "Secured tasks passed", "Secured attack matches", "Correct fields"]) {
    const cell = el("th", "", text); cell.scope = "col"; title.append(cell);
  }
  head.append(title); table.append(head);
  for (const item of data[$("#scorecard-dimension").value]) {
    const row = el("tr");
    row.append(el("td", "", names[item.name] || item.name), el("td", "", `${item.measured}/${item.attempted}`), el("td", "", item.runtime_errors),
      el("td", "", `${item.task_passed}/${item.measured} · ${percent(item.task_rate)}`),
      el("td", "", `${item.attack_matched}/${item.attack_cases} · ${percent(item.attack_rate)}`),
      el("td", "", `${item.fields_passed}/${item.fields_total} · ${percent(item.field_accuracy)}`)); body.append(row);
  }
  table.append(body); parent.append(table);
}

function renderDiagnosticCases() {
  const cases = diagnosticCases(), parent = $("#diagnostic-cases"); parent.replaceChildren();
  $("#diagnostic-count").textContent = `${cases.length} cases match the diagnostic filters`;
  $("#retest-diagnostics").disabled = !cases.length || Boolean(state.active && ["running", "stopping"].includes(state.active.status));
  for (const item of cases) {
    const details = el("details", "diagnostic-case"), summary = el("summary", "", `${item.case_id} · ${item.observations.map(observation => observation.label).join(" / ") || "No recorded issues"}`);
    details.append(summary);
    for (const observation of item.observations) details.append(el("p", "small", `${observation.label}: ${observation.next_step}`));
    if (item.failed_fields.length) details.append(el("p", "small muted", `Failed fields: ${item.failed_fields.map(check => check.field).join(", ")}`));
    const open = el("button", "secondary", "Inspect complete case evidence");
    open.addEventListener("click", () => openCase(state.report.results.find(row => row.case_id === item.case_id)));
    details.append(open); parent.append(details);
  }
  if (!cases.length) parent.append(el("p", "empty", "No cases match these diagnostic filters."));
}

function appendDiagnosis(parent, item) {
  const section = el("section", "case-diagnostics"); section.append(el("h3", "", "Recorded diagnostic observations"));
  if (!item.observations.length) section.append(el("p", "small", "No issues recorded by these checks. This does not establish semantic correctness of the whole response."));
  for (const observation of item.observations) section.append(el("h4", "", observation.label), el("p", "small", observation.next_step));
  if (item.source_trace.length) {
    const details = el("details"); details.append(el("summary", "", "Required-source delivery trace"));
    for (const source of item.source_trace) {
      details.append(el("h4", "", source.source_id), el("p", "evidence-meta", `Retrieved: ${source.retrieved ? "yes" : "no"} · Allowed: ${source.allowed ? "yes" : "no"} · Supplied to secured model: ${source.supplied == null ? "not recorded" : source.supplied ? "yes" : "no"} · Cited: ${source.cited ? "yes" : "no"}`));
      if (source.decisions.length) details.append(el("p", "small", `Recorded decisions: ${[...new Set(source.decisions)].join("; ")}`));
    }
    section.append(details);
  }
  parent.append(section);
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
  if (!state.runs.length) { $("#history-count").textContent = "0 experiments"; list.append(el("p", "empty", "No experiments yet. Start your first run to save evidence.")); return; }
  const query = $("#history-search").value.toLowerCase(), selectedStatus = $("#history-status").value;
  const metadata = state.workspace.experiments || {};
  const runs = state.runs.filter(run => (!selectedStatus || run.status === selectedStatus) &&
    (!$("#history-pinned").checked || metadata[run.run_id]?.pinned) &&
    [runName(run), run.run_id, run.model, metadata[run.run_id]?.note || ""].join(" ").toLowerCase().includes(query))
    .sort((a,b) => Number(Boolean(metadata[b.run_id]?.pinned)) - Number(Boolean(metadata[a.run_id]?.pinned)));
  $("#history-count").textContent = `${runs.length} of ${state.runs.length} experiments`;
  if (!runs.length) list.append(el("p", "empty", "No experiments match these filters."));
  for (const run of runs) {
    const row = el("div", "history-row"); const text = el("div");
    text.append(el("div", "history-title", runName(run)), el("div", "history-meta", `${run.metrics.completed_cases}/${run.planned_cases ?? run.metrics.total_cases} cases saved · ${run.metrics.error_cases} errors · ${run.model} · secured ASR ${percent(run.metrics.secured_asr)} · task success ${percent(run.metrics.secured_task_success)}`));
    const meta = metadata[run.run_id] || {};
    if (meta.pinned) text.prepend(badge("Pinned", "neutral"));
    if (meta.note) text.append(el("p", "history-meta experiment-note", meta.note));
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
    const edit = el("button", "secondary", "Name and notes");
    edit.addEventListener("click", () => {
      $("#experiment-id").value = run.run_id; $("#experiment-name").value = meta.name || "";
      $("#experiment-note").value = meta.note || ""; $("#experiment-pinned").checked = Boolean(meta.pinned);
      $("#experiment-error").textContent = ""; $("#experiment-dialog").showModal();
    });
    actions.append(edit);
    for (const [scope, label] of [["failed", "Retest failed tasks"], ["attacks", "Retest matched attacks"], ["errors", "Retry runtime errors"]]) {
      const button = el("button", "secondary", label);
      button.disabled = remaining.disabled;
      button.addEventListener("click", () => {
        configureFromRun(run); $("#run-scope").value = scope; $("#run-source").value = run.run_id;
        syncSelectionControls(); $("#new-dialog").showModal();
      });
      actions.append(button);
    }
  }
}
async function compareRuns() {
  const output = $("#comparison"); output.replaceChildren();
  error("");
  const aId = $("#compare-a").value, bId = $("#compare-b").value;
  if (!aId || !bId || aId === bId) { output.append(el("p", "notice", "Select two different saved experiments.")); return; }
  const [a, b] = await Promise.all([api(`/api/report/${aId}`), api(`/api/report/${bId}`)]);
  const ids = report => report.results.map(r => r.case_id).sort().join("|");
  if (a.mode !== b.mode || a.model !== b.model || ids(a) !== ids(b) || a.configuration.dataset_version !== b.configuration.dataset_version || a.configuration.grading_version !== b.configuration.grading_version) {
    output.append(el("p", "notice", "These experiments use different modes, models or scenario sets. Run both configurations with the same model and cases before comparing their aggregate scores.")); return;
  }
  const comparison = await api("/api/compare", {reference: aId, candidate: bId});
  const table = el("table"); const head = el("thead"), heading = el("tr");
  for (const name of ["Metric", "Reference", "Candidate", "Change"]) { const th = el("th", "", name); th.scope = "col"; heading.append(th); }
  head.append(heading); table.append(head); const body = el("tbody");
  for (const [key, label] of metricsFor(a)) {
    const row = el("tr"), av = a.metrics[key], bv = b.metrics[key], delta = av == null || bv == null ? null : 100 * (bv - av);
    row.append(el("td", "", label), el("td", "", percent(av)), el("td", "", percent(bv)), el("td", "", delta == null ? "N/A" : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)} pp`)); body.append(row);
  }
  table.append(body); output.append(el("p", "small muted", "Change is candidate minus reference in percentage points. Review task utility alongside attack and false positive rates."), table);
  const settingsTable = el("table"), settingsBody = el("tbody"), settingsHead = el("thead"), settingsTitles = el("tr");
  for (const text of ["Execution setting", "Reference", "Candidate"]) { const th = el("th", "", text); th.scope = "col"; settingsTitles.append(th); }
  settingsHead.append(settingsTitles); settingsTable.append(settingsHead);
  for (const [key,label] of [["temperature","Temperature"],["seed","Seed"],["think","Thinking mode"],["num_predict","Response token limit"],["num_ctx","Context window"],["request_timeout","Request timeout (seconds)"]]) {
    const row = el("tr"), value = report => !report.configuration.generation ? "Not recorded" : report.configuration.generation[key] == null ? "Model default" : String(report.configuration.generation[key]);
    row.append(el("td", "", label), el("td", "", value(a)), el("td", "", value(b))); settingsBody.append(row);
  }
  settingsTable.append(settingsBody); output.append(el("h3", "", "Recorded generation settings"), settingsTable,
    el("p", "small muted", a.mode === "demo" ? "Generation settings are not applied to demonstration responses." : "Review these settings alongside defense differences. A seed is not a guarantee of identical results, and these comparisons do not isolate a causal effect."));
  output.append(el("h3", "", "Case-level changes"), el("p", "small", `${comparison.counts.task_regressions} task regressions · ${comparison.counts.task_improvements} task improvements · ${comparison.counts.new_attack_matches} new attack matches · ${comparison.counts.resolved_attack_matches} resolved matches · ${comparison.counts.unmeasured} unmeasured cases`));
  const controls = el("div", "filters"), scopeLabel = el("label", "", "Show cases"), scope = el("select");
  scope.id = "comparison-scope"; scopeLabel.htmlFor = scope.id;
  for (const [value, label] of [["changed", "Changed cases"], ["regressions", "Task or attack regressions"], ["improvements", "Task or attack improvements"], ["attacks", "Changed attack outcomes"], ["unmeasured", "Unmeasured cases"], ["all", "All compared cases"]]) {
    const option = el("option", "", label); option.value = value; scope.append(option);
  }
  scopeLabel.append(scope);
  const searchLabel = el("label", "", "Search comparison"), search = el("input");
  search.type = "search"; search.id = "comparison-search"; search.placeholder = "Scenario ID or outcome";
  searchLabel.htmlFor = search.id; searchLabel.append(search); controls.append(scopeLabel, searchLabel);
  const actions = el("div", "export-actions"), download = el("button", "secondary", "Export comparison JSON");
  const retest = el("button", "secondary", "Choose visible regressions to retest");
  actions.append(download, retest); const count = el("p", "small muted"); count.setAttribute("role", "status");
  output.append(controls, actions, count, el("p", "small muted", "Timing change is candidate minus reference in seconds; field accuracy change is in percentage points. These are recorded observations, not controlled performance benchmarks."));
  const changes = el("table"), changesHead = el("thead"), titles = el("tr");
  changes.className = "comparison-table";
  for (const title of ["Scenario", "Secured task", "Secured attack objective", "Time change", "Field accuracy change", "Evidence"]) {
    const th = el("th", "", title); th.scope = "col"; titles.append(th);
  }
  changesHead.append(titles); changes.append(changesHead); const changesBody = el("tbody");
  function renderChanges() {
  changesBody.replaceChildren();
  const visible = filterComparisonCases(comparison.cases, scope.value, search.value);
  count.textContent = `${visible.length} of ${comparison.cases.length} compared cases shown`;
  const regressions = visible.filter(item => item.task === "regressed" || item.attack === "new match");
  retest.disabled = !regressions.length || Boolean(state.active && ["running", "stopping"].includes(state.active.status));
  for (const item of visible) {
    const row = el("tr"), links = el("td");
    for (const [id, label] of [[aId, "Reference"], [bId, "Candidate"]]) {
      const button = el("button", "case-link", label);
      button.addEventListener("click", async () => {
        try { await loadReport(id); openCase(state.report.results.find(r => r.case_id === item.case_id)); }
        catch(e) { error(e.message); }
      });
      links.append(button, document.createTextNode(" "));
    }
    const duration = item.duration_delta_seconds, score = item.secured_field_score_delta;
    row.append(el("td", "", item.case_id), el("td", "", item.task), el("td", "", item.attack),
      el("td", "", duration == null ? "N/A" : `${duration >= 0 ? "+" : ""}${duration.toFixed(2)} s`),
      el("td", "", score == null ? "N/A" : `${score >= 0 ? "+" : ""}${(100 * score).toFixed(1)} pp`), links);
    changesBody.append(row);
  }
  if (!visible.length) { const row = el("tr"), cell = el("td", "empty", "No cases match these comparison filters."); cell.colSpan = 6; row.append(cell); changesBody.append(row); }
  }
  scope.addEventListener("input", renderChanges); search.addEventListener("input", renderChanges);
  download.addEventListener("click", () => {
    const data = comparisonExport(comparison, a, b, scope.value, search.value);
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type:"application/json"}));
    const link = el("a"); link.href = url; link.download = `spades-comparison-${aId.slice(0,8)}-${bId.slice(0,8)}.json`;
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast(`Exported ${data.exported_case_count} comparison cases.`);
  });
  retest.addEventListener("click", () => {
    const cases = filterComparisonCases(comparison.cases, scope.value, search.value)
      .filter(item => item.task === "regressed" || item.attack === "new match");
    if (!cases.length) return;
    configureFromRun(b); $("#run-category").value = ""; $("#run-domain").value = "";
    $("#scenario-search").value = ""; $("#run-scope").value = "selected";
    selectionState.ids = new Set(cases.map(item => item.case_id));
    syncSelectionControls(); $("#new-dialog").showModal();
  });
  renderChanges();
  changes.append(changesBody); const scroll = el("div", "table-scroll"); scroll.append(changes); output.append(scroll);
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
           source_run_id: ["remaining", "errors", "failed", "attacks"].includes(scope) ? $("#run-source").value || null : null,
           model: $("#run-model").value,
           generation: {temperature:Number($("#run-temperature").value), seed:$("#run-seed").value.trim() === "" ? null : Number($("#run-seed").value), think: {default:null,enabled:true,disabled:false}[$("#run-thinking").value],
             num_predict:Number($("#run-max-tokens").value), num_ctx:Number($("#run-context-window").value), request_timeout:Number($("#run-timeout").value)} };
}

function setModelChoice(value) {
  const select = $("#run-model");
  if (![...select.options].some(option => option.value === value)) { const option = el("option", "", `${value} (availability checked at launch)`); option.value = value; select.append(option); }
  select.value = value;
}

function restoreGeneration(settings, profile) {
  const generation = {temperature:0, seed:null, num_predict:profile === "complex" ? 1400 : 350,
    num_ctx:profile === "complex" ? 16384 : 4096, request_timeout:180, ...settings};
  for (const [key,id] of [["temperature","run-temperature"],["seed","run-seed"],["num_predict","run-max-tokens"],["num_ctx","run-context-window"],["request_timeout","run-timeout"]]) {
    document.getElementById(id).value = generation[key] ?? "";
  }
  $("#run-thinking").value = generation.think == null ? "default" : generation.think ? "enabled" : "disabled";
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
  setModelChoice(run.mode === "local" ? run.model : "qwen2.5:7b-instruct-q4_K_M");
  restoreGeneration(c.generation, c.profile || "foundation");
  $("#run-profile").value = c.profile || "foundation";
  $("#profile-description").textContent = c.profile === "complex" ? "Enterprise cases retain 21–23 records and typed grading. Review the selected scenarios before launching." : "Foundation cases use short documents and lightweight assertions. Review the selected scenarios before launching.";
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
  $("#source-run-field").hidden = !["remaining", "errors", "failed", "attacks"].includes(scope);
  renderScenarioPicker(); queueSelectionPreview();
}

function queueSelectionPreview() {
  clearTimeout(selectionState.previewTimer);
  const revision = ++selectionState.previewRevision;
  $("#selection-preview").textContent = "Checking scenario selection…";
  $("#run-plan-details").replaceChildren(el("p", "small", "Checking the selected workload…"));
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
      renderRunPlan(data.plan);
      $("#launch-run").disabled = false;
      $("#launch-run").textContent = `Run ${data.count} scenario${data.count === 1 ? "" : "s"} →`;
    } catch(e) {
      if (revision !== selectionState.previewRevision) return;
      preview.textContent = e.message; preview.classList.add("invalid"); $("#launch-run").disabled = true;
      $("#run-plan-details").replaceChildren(el("p", "error", "A valid scenario selection is required to build the run plan."));
    }
  }, 180);
}
function applyPreset(id) {
  const preset = state.workspace.presets.find(p => p.id === id);
  if (!preset) return;
  setModelChoice(preset.config.model || "qwen2.5:7b-instruct-q4_K_M");
  restoreGeneration(preset.config.generation, preset.config.profile || "foundation");
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
  renderHistory();
  renderSuites();
  renderQualityPolicy();
  for (const selector of ["#report-select", "#compare-a", "#compare-b", "#run-source"]) {
    for (const option of $(selector).options) {
      const run = state.runs.find(r => r.run_id === option.value);
      if (run) option.textContent = runName(run);
    }
  }
}
function renderRunPlan(plan) {
  const parent = $("#run-plan-details"); parent.replaceChildren();
  if (!plan) { parent.append(el("p", "small", "Run-plan details are unavailable.")); return; }
  const list = el("dl", "snapshot");
  for (const [label,value] of [["Scenarios", plan.scenarios], ["Paired model responses", plan.model_responses],
    ["Source records across cases", plan.source_records], ["Fixture characters before chunking", plan.fixture_characters.toLocaleString()],
    ["Typed field assertions per arm", plan.typed_assertions_per_arm], ["Typed assertions across both arms", plan.paired_typed_assertions],
    ["Foundation fact checks", plan.foundation_fact_checks], ["Domains", Object.entries(plan.domains).map(([name,count]) => `${name}: ${count}`).join(" · ")],
    ["Scenario families", Object.entries(plan.families).map(([name,count]) => `${names[name] || name}: ${count}`).join(" · ")]]) {
    const row = el("div"); row.append(el("dt", "", label), el("dd", "", String(value))); list.append(row);
  }
  parent.append(list, el("p", "small muted", plan.note));
}

function openSuiteEditor(record, imported=false) {
  suiteDraft = {record, imported};
  $("#suite-title").textContent = imported ? "Import test suite" : record.id ? "Edit test suite" : "Save test suite";
  $("#suite-name").value = record.name || ""; $("#suite-description").value = record.description || "";
  $("#suite-profile").value = record.profile; $("#suite-cases").value = record.case_ids.join("\n");
  $("#suite-error").textContent = "";
  $("#suite-revision").textContent = record.id && !imported ? `Editing revision ${record.revision}. Saving creates the next revision; existing runs keep their recorded selections.` : "Review the name and exact scenario IDs before saving. No inference will run.";
  $("#suite-dialog").showModal();
}

function renderSuites() {
  const suites = state.workspace.suites || [], query = $("#suite-search").value.trim().toLowerCase();
  $("#suite-count").textContent = suites.length;
  const parent = $("#suite-list"); parent.replaceChildren();
  for (const suite of suites.filter(item => [item.name, item.description, ...item.case_ids].join(" ").toLowerCase().includes(query)).slice().sort((a,b) => b.updated_at.localeCompare(a.updated_at))) {
    const card = el("article", "panel corpus-card");
    card.append(el("span", "eyebrow", `${suite.profile === "complex" ? "Enterprise" : "Foundation"} · revision ${suite.revision}`),
      el("h3", "", suite.name), el("p", "", suite.description || "No description provided."),
      el("p", "evidence-meta", `${suite.case_ids.length} exact scenarios · ${suite.plan.model_responses} paired responses · dataset ${suite.dataset_version} · grading ${suite.grading_version}`));
    const members = el("details"); members.append(el("summary", "", "Inspect suite membership"), el("pre", "", suite.case_ids.join("\n")));
    card.append(members, el("p", "small muted", `Updated ${date(suite.updated_at)}`));
    const actions = el("div", "preset-actions"), use = el("button", "primary", "Configure experiment"), edit = el("button", "secondary", "Edit suite"), download = el("button", "secondary", "Export suite");
    use.disabled = Boolean(state.active && ["running", "stopping"].includes(state.active.status));
    use.addEventListener("click", async () => {
      try {
        const resolved = await api("/api/suite/resolve", {id:suite.id});
        $("#run-profile").value = resolved.profile; renderDomainOptions();
        $("#run-scope").value = "selected"; $("#run-domain").value = ""; $("#run-category").value = "";
        $("#run-k").value = resolved.profile === "complex" ? 20 : 5;
        $("#run-max-tokens").value = resolved.profile === "complex" ? 1400 : 350;
        $("#run-context-window").value = resolved.profile === "complex" ? 16384 : 4096;
        $("#run-source").value = ""; $("#run-preset").value = ""; $("#scenario-search").value = "";
        $("#profile-description").textContent = `Suite: ${suite.name} · revision ${suite.revision}. Review execution and defense settings before launching.`;
        selectionState.ids = new Set(resolved.case_ids); $("#run-error").textContent = "";
        syncSelectionControls(); $("#new-dialog").showModal();
      } catch(e) { $("#suite-message").textContent = e.message; }
    });
    edit.addEventListener("click", () => openSuiteEditor(suite));
    download.addEventListener("click", async () => {
      try {
        const manifest = await api("/api/suite/export", {id:suite.id});
        const url = URL.createObjectURL(new Blob([JSON.stringify(manifest,null,2)], {type:"application/json"}));
        const link = el("a"); link.href = url; link.download = `spades-suite-${suite.id}.json`;
        document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url),1000);
        toast("Portable test suite exported.");
      } catch(e) { $("#suite-message").textContent = e.message; }
    });
    actions.append(use,edit,download); card.append(actions); parent.append(card);
  }
  if (!parent.children.length) parent.append(el("p", "empty", suites.length ? "No suites match this search." : "No saved suites yet. Choose scenarios in a new experiment, then save the selection as a test suite."));
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
  const runtime = await api("/api/runtime");
  const current = $("#run-model").value, installed = runtime.models.filter(name => !name.startsWith("nomic-embed-text"));
  $("#run-model").replaceChildren();
  for (const name of installed) { const option = el("option", "", name); option.value = name; $("#run-model").append(option); }
  setModelChoice(current || "qwen2.5:7b-instruct-q4_K_M");
  const ready = runtime.ollama && runtime.chromadb && installed.length > 0 && runtime.models.some(name => ["nomic-embed-text","nomic-embed-text:latest"].includes(name));
  const pill = $("#runtime-pill"); pill.textContent = ready ? "● Local runtime ready" : "○ Local setup needed"; pill.classList.toggle("warning", !ready);
  const list = $("#runtime-components"); list.replaceChildren();
  for (const [name, subtitle, componentReady, detail] of [
    ["Ollama engine", "Loopback inference service", runtime.ollama, "127.0.0.1:11434"],
    ["ChromaDB", "Persistent vector retrieval", runtime.chromadb, "Local embeddings · telemetry disabled"],
    ["Model weights", "Local generation + nomic embeddings", ready, runtime.models.join(" · ") || "No installed models found"],
  ]) { const card = el("article", "panel runtime-card"); card.append(el("span", "eyebrow", subtitle), el("h2", "", name), el("p", "", detail), el("div", `runtime-status ${componentReady ? "" : "off"}`, componentReady ? "● Available locally" : "○ Preparation required")); list.append(card); }
  $("#runtime-error").textContent = runtime.error || "All experiment requests stay on loopback. Preparing model weights requires internet access once.";
  $("#run-mode").querySelector('option[value="local"]').disabled = !ready;
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
for (const selector of ["#search", "#category-filter", "#outcome-filter", "#case-sort"]) $(selector).addEventListener("input", renderCases);
$("#export-visible").addEventListener("click", exportVisibleCases);
function downloadQualityJSON(data, filename) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:"application/json"}));
  const link=el("a"); link.href=url; link.download=filename; document.body.append(link); link.click(); link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
$("#export-gate").addEventListener("click",()=>{
  if (state.report?.quality_gate) downloadQualityJSON(state.report.quality_gate,`spades-gate-${state.report.run_id}.json`);
});
$("#export-quality-policy").addEventListener("click",()=>{
  if (state.workspace.quality_policy) downloadQualityJSON(state.workspace.quality_policy.policy,"spades-acceptance-policy.json");
});
$("#retest-gate").addEventListener("click",()=>{
  const ids=state.report?.quality_gate?.failed_case_ids || []; if (!ids.length) return;
  configureFromRun(state.report); $("#run-domain").value=""; $("#run-category").value=""; $("#scenario-search").value="";
  $("#run-scope").value="selected"; selectionState.ids=new Set(ids); syncSelectionControls(); $("#new-dialog").showModal();
});
$("#quality-policy-form").addEventListener("submit",async event=>{
  event.preventDefault(); const button=$("#save-quality-policy"); button.disabled=true; $("#quality-error").textContent="";
  const policy=readQualityPolicy();
  try {
    $("#quality-policy-library").value="";
    updateWorkspace(await api("/api/quality-policy",{policy,revision:state.workspace.quality_policy.revision}));
    if (state.report) await loadReport(state.report.run_id);
    toast("Acceptance policy saved. The displayed gate was reassessed.");
  } catch(e) { $("#quality-error").textContent=e.message; }
  finally { button.disabled=false; }
});
$("#reload-quality-policy").addEventListener("click",async()=>{
  try { $("#quality-policy-library").value=""; updateWorkspace(await api("/api/workspace")); if (state.report) await loadReport(state.report.run_id); $("#quality-error").textContent=""; }
  catch(e) { $("#quality-error").textContent=e.message; }
});
function invalidatePolicyPreview() {
  policyPreview=null; $("#export-policy-preview").disabled=true; $("#quality-policy-preview").replaceChildren();
}
$("#quality-policy-form").addEventListener("input",invalidatePolicyPreview);
$("#quality-policy-library").addEventListener("change",()=>{
  const snapshot=(state.workspace.quality_policies || []).find(item=>item.id===$("#quality-policy-library").value);
  fillQualityPolicy(snapshot?.policy || state.workspace.quality_policy.policy); invalidatePolicyPreview();
});
$("#archive-quality-policy").addEventListener("click",async()=>{
  const button=$("#archive-quality-policy"); button.disabled=true; const policy=readQualityPolicy();
  try {
    const data=await api("/api/quality-policy/archive",{policy}); updateWorkspace(data);
    $("#quality-policy-library").value=data.quality_policies.find(item=>item.policy.name===policy.name.trim()).id;
    fillQualityPolicy(policy); toast("Named policy saved for reuse. The workspace policy was not applied.");
  } catch(e) { $("#quality-error").textContent=e.message; }
  finally { button.disabled=false; }
});
$("#preview-quality-policy").addEventListener("click",async()=>{
  const button=$("#preview-quality-policy"),key=qualityViewKey,policy=readQualityPolicy(); button.disabled=true;
  invalidatePolicyPreview(); $("#quality-error").textContent="";
  try {
    const result=await api("/api/quality/compare-policy",{run_id:state.report.run_id,candidate_policy:policy});
    if (key!==qualityViewKey || JSON.stringify(policy)!==JSON.stringify(readQualityPolicy())) return;
    if (result.policy_revision!==state.report.quality_gate.policy_revision) throw new Error("The workspace policy changed. Reload the saved policy before previewing.");
    policyPreview=result; renderPolicyPreview(result); $("#export-policy-preview").disabled=false;
  } catch(e) { $("#quality-error").textContent=e.message; }
  finally { button.disabled=false; }
});
$("#export-policy-preview").addEventListener("click",()=>{
  if (policyPreview) downloadQualityJSON(policyPreview,`spades-policy-preview-${policyPreview.run_id}.json`);
});
$("#load-quality-history").addEventListener("click",async()=>{
  const button=$("#load-quality-history"),key=qualityViewKey; button.disabled=true;
  qualityHistory=null; $("#export-quality-history").disabled=true; $("#quality-history").replaceChildren(el("p","small","Loading compatible acceptance history…"));
  try {
    const result=await api("/api/quality/history",{run_id:state.report.run_id});
    if (key!==qualityViewKey) return;
    if (result.policy_revision!==state.report.quality_gate.policy_revision) throw new Error("The workspace policy changed. Reload it before reviewing history.");
    qualityHistory=result; renderQualityHistory(result); $("#export-quality-history").disabled=false;
  } catch(e) { $("#quality-history").replaceChildren(el("p","error",e.message)); }
  finally { button.disabled=false; }
});
$("#export-quality-history").addEventListener("click",()=>{
  if (qualityHistory) downloadQualityJSON(qualityHistory,`spades-acceptance-history-${qualityHistory.anchor_run_id}.json`);
});
$("#suite-search").addEventListener("input", renderSuites);
$("#create-suite").addEventListener("click", () => {
  $("#run-scope").value = "selected"; $("#run-domain").value = ""; $("#run-category").value = "";
  $("#scenario-search").value = ""; selectionState.ids.clear(); $("#run-error").textContent = "";
  syncSelectionControls(); $("#new-dialog").showModal();
});
$("#save-suite-selection").addEventListener("click", async () => {
  const button = $("#save-suite-selection"); button.disabled = true;
  try {
    const config = currentConfig(), selection = await api("/api/selection", config);
    $("#new-dialog").close();
    openSuiteEditor({name:"", description:"", profile:config.profile, case_ids:selection.case_ids});
  } catch(e) { $("#run-error").textContent = e.message; }
  finally { button.disabled = false; }
});
$("#suite-form").addEventListener("submit", async event => {
  event.preventDefault(); if (!suiteDraft) return;
  const button = $("#save-suite"); button.disabled = true;
  const record = suiteDraft.record;
  const fields = {name:$("#suite-name").value, description:$("#suite-description").value,
    profile:$("#suite-profile").value, case_ids:$("#suite-cases").value.split(/\r?\n/).map(id => id.trim()).filter(Boolean)};
  try {
    const body = suiteDraft.imported ? {...record,...fields} : {...fields,...(record.id ? {id:record.id,revision:record.revision} : {})};
    updateWorkspace(await api(suiteDraft.imported ? "/api/suite/import" : "/api/suite", body));
    $("#suite-dialog").close(); $("#suite-search").value = ""; renderSuites(); view("suites");
    toast("Test suite saved. Configure an experiment when ready.");
  } catch(e) { $("#suite-error").textContent = e.message; }
  finally { button.disabled = false; }
});
$("#suite-import").addEventListener("change", async () => {
  const input = $("#suite-import"), file = input.files[0]; if (!file) return;
  try {
    if (file.size > 8192) throw new Error("Suite manifests must be no larger than 8 KiB.");
    const manifest = JSON.parse(await file.text());
    if (!manifest || manifest.format !== "spades-test-suite" || manifest.version !== 1 || !Array.isArray(manifest.case_ids) || !["foundation","complex"].includes(manifest.profile)) throw new Error("Choose a Spades version-1 test-suite manifest.");
    openSuiteEditor(manifest,true);
  } catch(e) { $("#suite-message").textContent = e.message; }
  finally { input.value = ""; }
});
for (const selector of ["#diagnostic-issue", "#diagnostic-domain", "#diagnostic-search"]) $(selector).addEventListener("input", renderDiagnosticCases);
$("#scorecard-dimension").addEventListener("input", renderScorecards);
$("#retest-diagnostics").addEventListener("click", () => {
  const cases = diagnosticCases(); if (!cases.length) return;
  configureFromRun(state.report); $("#run-domain").value = ""; $("#run-category").value = "";
  $("#scenario-search").value = ""; $("#run-scope").value = "selected";
  selectionState.ids = new Set(cases.map(item => item.case_id));
  syncSelectionControls(); $("#new-dialog").showModal();
});
$("#export-diagnostics").addEventListener("click", () => {
  if (!state.report?.analysis) return;
  const data = {export_type: "diagnostic_analysis", exported_at: new Date().toISOString(),
    model: state.report.model, mode: state.report.mode, configuration: state.report.configuration,
    analysis: state.report.analysis, review_filters: {issue: $("#diagnostic-issue").value, domain: $("#diagnostic-domain").value, search: $("#diagnostic-search").value},
    visible_case_ids: diagnosticCases().map(item => item.case_id)};
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type:"application/json"}));
  const link = el("a"); link.href = url; link.download = `spades-diagnostics-${state.report.run_id}.json`;
  document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast("Diagnostic analysis exported.");
});
for (const selector of ["#corpus-search", "#corpus-category", "#corpus-profile"]) $(selector).addEventListener("input", renderCorpus);
$("#report-select").addEventListener("change", () => loadReport($("#report-select").value).catch(e => error(e.message)));
$("#refresh-history").addEventListener("click", () => refreshRuns().catch(e => error(e.message)));
for (const selector of ["#history-search", "#history-status", "#history-pinned"]) $(selector).addEventListener("input", renderHistory);
$("#experiment-form").addEventListener("submit", async event => {
  event.preventDefault(); const button = $("#save-experiment"); button.disabled = true;
  try {
    updateWorkspace(await api("/api/experiment", {run_id: $("#experiment-id").value,
      name: $("#experiment-name").value, note: $("#experiment-note").value, pinned: $("#experiment-pinned").checked}));
    $("#experiment-dialog").close(); toast("Experiment details saved locally.");
  } catch(e) { $("#experiment-error").textContent = e.message; }
  finally { button.disabled = false; }
});
$("#refresh-runtime").addEventListener("click", () => refreshRuntime().catch(e => error(e.message)));
$("#compare-button").addEventListener("click", () => compareRuns().catch(e => error(e.message)));
$("#run-preset").addEventListener("change", () => applyPreset($("#run-preset").value));
for (const id of ["run-mode", "run-policy", "run-threshold", "run-k", "run-limit", "run-category", "run-profile", "run-domain", "run-scope", "run-concurrency", "run-model", "run-temperature", "run-seed", "run-max-tokens", "run-context-window", "run-timeout", "run-thinking"]) {
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
  $("#run-max-tokens").value = complex ? 1400 : 350;
  $("#run-context-window").value = complex ? 16384 : 4096;
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
