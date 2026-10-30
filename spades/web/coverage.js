"use strict";

const coverageState={result:null,selected:new Set(),revision:0};
const coverageLabels={unseen:"No compatible observation",review:"Review required",runtime_error:"Runtime error",unmeasured:"Unmeasured",passed:"Task passed"};

function invalidateCoverage() {
  coverageState.revision++; coverageState.result=null; coverageState.selected.clear();
  $("#coverage-results").replaceChildren(el("p","empty","Refresh coverage after choosing a source and execution settings."));
  $("#coverage-configure").disabled=true;$("#coverage-export").disabled=true;
  $("#coverage-cases").replaceChildren();$("#coverage-selection").textContent="";$("#coverage-visible").textContent="";
}

function coverageSources() {
  const select=$("#coverage-source"),previous=select.value;
  select.replaceChildren();
  for(const [value,name] of [["complex","Enterprise library · all 96 scenarios"],["foundation","Foundation library · all 100 scenarios"],["current","Current experiment selection"]]) {
    const option=el("option","",name);option.value=value;select.append(option);
  }
  for(const suite of state.workspace.suites || []) {const option=el("option","",`${suite.name} · revision ${suite.revision}`);option.value=`suite:${suite.id}`;select.append(option);}
  if([...select.options].some(option=>option.value===previous))select.value=previous;
}

async function coverageConfig() {
  const source=$("#coverage-source").value,base=currentConfig();
  if(source==="current")return base;
  let suite=null;
  if(source.startsWith("suite:"))suite=await api("/api/suite/resolve",{id:source.slice(6)});
  return {...base,profile:suite?.profile || source,case_definitions:suite?.case_definitions || null,
    selection_scope:suite ? "selected":"all",case_ids:suite?.case_ids || null,category:null,domain:null,source_run_id:null};
}

function updateCoverageSelection() {
  const result=coverageState.result;if(!result)return;
  $("#coverage-selection").textContent=`${coverageState.selected.size} selected · ${coverageState.selected.size*2} paired responses · budget ${result.budget}. Review the exact selection before execution.`;
  $("#coverage-configure").disabled=!coverageState.selected.size;
}

function renderCoverageCases() {
  const result=coverageState.result;if(!result)return;
  const parent=$("#coverage-cases");parent.replaceChildren();
  const search=$("#coverage-search").value.trim().toLowerCase(),status=$("#coverage-status").value;
  const rows=result.cases.filter(item=>(!status || item.status===status) && [item.case_id,item.domain,item.category,...item.failed_fields,...item.issues].join(" ").toLowerCase().includes(search));
  $("#coverage-visible").textContent=`${rows.length} of ${result.scope_count} scenarios shown`;
  for(const item of rows) {
    const card=el("article","diagnostic-case"),label=el("label","check-label"),check=el("input");check.type="checkbox";check.checked=coverageState.selected.has(item.case_id);
    check.setAttribute("aria-label",`Select ${item.case_id}`);
    check.addEventListener("change",()=>{if(check.checked && coverageState.selected.size>=result.budget){check.checked=false;$("#coverage-error").textContent="The selection reached its scenario budget. Deselect a scenario or increase the budget and refresh.";return;}$("#coverage-error").textContent="";check.checked?coverageState.selected.add(item.case_id):coverageState.selected.delete(item.case_id);updateCoverageSelection();});
    label.append(check,el("strong","",item.case_id));card.append(label,el("p","small",`${item.domain} · ${names[item.category] || item.category} · ${coverageLabels[item.status]}`));
    if(item.issues.length)card.append(el("p","small",item.issues.join(" · ")));
    if(item.failed_fields.length)card.append(el("p","small",`Failed fields: ${item.failed_fields.join(", ")}`));
    if(item.missing_citations.length)card.append(el("p","small",`Missing required citations: ${item.missing_citations.join(", ")}`));
    if(item.error)card.append(el("p","error",item.error));
    if(item.run_id){const open=el("button","secondary","Inspect latest evidence");open.addEventListener("click",async()=>{try{await loadReport(item.run_id);view("overview");openCase(state.report.results.find(row=>row.case_id===item.case_id));}catch(e){$("#coverage-error").textContent=e.message;}});card.append(el("p","evidence-meta",`${date(item.observed_at)} · run ${item.run_id.slice(0,8)}`),open);}
    parent.append(card);
  }
  if(!rows.length)parent.append(el("p","empty","No scenarios match these filters."));
}

function renderCoverage(result) {
  const parent=$("#coverage-results");parent.replaceChildren();
  const summary=el("div","diagnostic-grid");
  for(const [status,label] of Object.entries(coverageLabels)) {const button=el("button","diagnostic-tile",`${label}: ${result.states[status] || 0}`);button.addEventListener("click",()=>{$("#coverage-status").value=status;renderCoverageCases();});summary.append(button);}
  parent.append(el("h2","","Coverage and follow-up plan"),summary,
    el("p","small",`${result.evidence_run_ids.length} contributing saved runs · ${result.scope_count} scenarios in scope · ${result.eligible_count} eligible for this focus · ${result.selected_ids.length} suggested within budget.`),
    el("p","evidence-meta",`${result.identity.mode==="local" ? result.identity.model:"DEMONSTRATION simulator"} · weight identity ${result.identity.model_digest || "not recorded / not applicable"}`),
    el("p","small",`${result.config.profile==="complex" ? "Enterprise":"Foundation"} · ${result.config.policy} defense · trust ≥ ${result.config.threshold} · top ${result.config.k} chunks · snapshot ${date(result.generated_at)}. Seed differences are allowed; local generation settings otherwise match.`));
  const groups=el("div","coverage-groups");
  for(const [key,title] of [["domains","Domain coverage"],["families","Scenario-family coverage"]]) {
    const details=el("details");details.append(el("summary","",title));
    for(const group of result[key])details.append(el("p","small",`${names[group.name] || group.name}: ${group.measured}/${group.scenarios} measured · ${group.states.unseen || 0} unseen · ${group.states.review || 0} needing review · ${group.states.runtime_error || 0} runtime errors`));groups.append(details);
  }
  const excluded=el("details");excluded.append(el("summary","","Excluded report groups and planning limits"));
  for(const [reason,count] of Object.entries(result.excluded_reports))excluded.append(el("p","small",`${count} reports: ${reason}`));
  const limits=el("ul","small muted");result.limitations.forEach(text=>limits.append(el("li","",text)));excluded.append(limits);parent.append(groups,excluded);
  $("#coverage-export").disabled=false;updateCoverageSelection();renderCoverageCases();
}

$("#coverage-refresh").addEventListener("click",async()=>{
  const button=$("#coverage-refresh");button.disabled=true;$("#coverage-error").textContent="";
  const revision=++coverageState.revision;
  try {
    const result=await api("/api/coverage",{config:await coverageConfig(),focus:$("#coverage-focus").value,budget:Number($("#coverage-budget").value)});
    if(revision!==coverageState.revision)return;
    coverageState.result=result;coverageState.selected=new Set(result.selected_ids);renderCoverage(result);
  } catch(e){if(revision===coverageState.revision){invalidateCoverage();$("#coverage-error").textContent=e.message;}}
  finally{button.disabled=false;}
});
$("#coverage-settings").addEventListener("click",()=>{$("#new-dialog").showModal();});
$("#coverage-from-report").addEventListener("click",()=>{
  if(!state.report){$("#coverage-error").textContent="Open a saved experiment first.";return;}
  const ids=state.report.planned_case_ids || state.report.results.map(row=>row.case_id);
  if(!ids.length){$("#coverage-error").textContent="This experiment has no recorded scenario scope.";return;}
  configureFromRun(state.report);$("#run-source").value="";$("#run-scope").value="selected";
  $("#run-domain").value="";$("#run-category").value="";selectionState.ids=new Set(ids);syncSelectionControls();
  $("#coverage-source").value="current";invalidateCoverage();
  $("#coverage-error").textContent=`Loaded ${ids.length} exact scenarios and recorded settings from ${runName(state.report)}. Refresh coverage to inspect comparable evidence.`;
});
$("#coverage-configure").addEventListener("click",()=>{
  const result=coverageState.result;if(!result || !coverageState.selected.size)return;
  const config=result.config;
  configureFromRun({mode:config.mode,model:config.model,configuration:{...config,trust_threshold:config.threshold,retrieval_k:config.k}});
  $("#run-source").value="";$("#run-scope").value="selected";$("#run-domain").value="";$("#run-category").value="";
  $("#run-concurrency").value=config.concurrency;selectionState.ids=new Set(coverageState.selected);syncSelectionControls();
  $("#profile-description").textContent=`Coverage follow-up: ${coverageState.selected.size} exact scenarios. Review execution settings before starting or saving as a suite.`;
  $("#new-dialog").showModal();
});
$("#coverage-export").addEventListener("click",()=>{
  if(!coverageState.result)return;
  const ids=[...coverageState.selected];
  const content={...coverageState.result,exported_at:new Date().toISOString(),operator_selected_ids:ids,
    execution_config:ids.length ? {...coverageState.result.config,case_ids:ids,limit:ids.length}:null};
  const url=URL.createObjectURL(new Blob([JSON.stringify(content,null,2)],{type:"application/json"}));const link=el("a");link.href=url;link.download="spades-coverage-plan.json";document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
for(const id of ["coverage-source","coverage-focus","coverage-budget"])$("#"+id).addEventListener("change",invalidateCoverage);
$("#run-form").addEventListener("input",invalidateCoverage);$("#run-form").addEventListener("change",invalidateCoverage);
$("#coverage-search").addEventListener("input",renderCoverageCases);$("#coverage-status").addEventListener("change",renderCoverageCases);
$("#coverage-clear").addEventListener("click",()=>{coverageState.selected.clear();updateCoverageSelection();renderCoverageCases();});
$("#coverage-suggested").addEventListener("click",()=>{if(!coverageState.result)return;coverageState.selected=new Set(coverageState.result.selected_ids);updateCoverageSelection();renderCoverageCases();});
document.querySelector('[data-view="coverage"]').addEventListener("click",coverageSources);
coverageSources();invalidateCoverage();
