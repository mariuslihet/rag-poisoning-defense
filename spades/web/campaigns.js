"use strict";

const campaignViewState={items:[],selected:null,detail:null,timer:null,loading:false};

function campaignInterval(interval) { return interval ? `${percent(interval.lower)}–${percent(interval.upper)}` : "N/A"; }

function renderCampaigns() {
  const suiteSelect=$("#campaign-suite"),previous=suiteSelect.value;
  suiteSelect.replaceChildren(el("option","","Current New experiment selection")); suiteSelect.firstElementChild.value="";
  for (const suite of state.workspace.suites || []) { const option=el("option","",`${suite.name} · revision ${suite.revision} · ${suite.case_ids.length} scenarios`); option.value=suite.id; suiteSelect.append(option); }
  if ([...suiteSelect.options].some(option=>option.value===previous)) suiteSelect.value=previous;
  if (!$("#campaign-models").value.trim()) $("#campaign-models").value=$("#run-model").value || "qwen2.5:7b-instruct-q4_K_M";
  if (!$("#view-campaigns").hidden) refreshCampaigns().catch(e=>$("#campaign-error").textContent=e.message);
}

async function campaignBody() {
  const base=currentConfig();
  const suiteId=$("#campaign-suite").value;
  if (suiteId) {
    const suite=await api("/api/suite/resolve",{id:suiteId});
    if (suite.profile!==base.profile) base.generation={...base.generation,num_predict:suite.profile==="complex" ? 1400 : 350,num_ctx:suite.profile==="complex" ? 16384 : 4096};
    Object.assign(base,{profile:suite.profile,case_ids:suite.case_ids,selection_scope:"selected",source_run_id:null,category:null,domain:null,limit:suite.case_ids.length});
    if (suite.case_definitions) base.case_definitions=suite.case_definitions; else delete base.case_definitions;
  }
  const models=$("#campaign-models").value.split(/\r?\n/).map(item=>item.trim()).filter(Boolean);
  const seeds=$("#campaign-seeds").value.split(/[,\s]+/).filter(Boolean).map(value=>{
    if (!/^\d+$/.test(value)) throw new Error("Trial seeds must be whole numbers separated by commas."); return Number(value);
  });
  const policies=[]; if ($("#campaign-strict").checked) policies.push("strict"); if ($("#campaign-sanitize").checked) policies.push("sanitize");
  if (!models.length || !policies.length || !seeds.length) throw new Error("Choose generation models, a defense policy and at least one trial seed.");
  if (new Set(models).size!==models.length || new Set(seeds).size!==seeds.length) throw new Error("Model names and trial seeds must be unique.");
  const body={name:$("#campaign-name").value,base_config:base,models,policies,seeds};
  const variants=$("#campaign-retrieval-variants").value.trim();if(variants){try{body.retrieval_variants=JSON.parse(variants);}catch(e){throw new Error("Retrieval variants must be a JSON array.");}if(!Array.isArray(body.retrieval_variants) || !body.retrieval_variants.length || body.retrieval_variants.length>10)throw new Error("Provide 1–10 retrieval variants.");}
  for(const [key,id,min,max,integer] of [["thresholds","campaign-thresholds",0,1,false],["retrieval_depths","campaign-depths",1,50,true],["temperatures","campaign-temperatures",0,2,false]]) {
    const values=parseCampaignSweep($("#"+id).value,min,max,integer);if(values)body[key]=values;
  }
  if (campaignMatrixSize(body)>100) throw new Error(`This matrix contains ${campaignMatrixSize(body)} trial jobs. Reduce it to at most 100.`);
  return body;
}

async function previewCampaign() {
  const body=await campaignBody(), preview=await api("/api/campaign/preview",body);
  const parent=$("#campaign-plan");parent.replaceChildren(el("p","",`${preview.trial_jobs} trial jobs · ${preview.scenario_plan.scenarios} fixed scenarios per trial · ${preview.scenario_evaluations} scenario evaluations · ${preview.model_responses} model responses · ${preview.generation_applied ? "REAL LOCAL inference":"DEMONSTRATION responses; generation parameters are not applied"}. Trials execute sequentially with bounded scenario workers.`),
    el("p","small",`Trust thresholds: ${preview.axes.thresholds.join(", ")} · retrieval depths: ${preview.axes.retrieval_depths.join(", ")} · temperatures: ${preview.axes.temperatures.join(", ")} · retrieval variants: ${preview.axes.retrieval_variants.length}.`));
  const details=el("details");details.append(el("summary","","Inspect every planned trial configuration"),el("pre","",JSON.stringify(preview.configurations,null,2)));parent.append(details,el("p","small",preview.note));
  body.base_config=preview.base_config;
  return body;
}

function scheduleCampaignRefresh() {
  clearTimeout(campaignViewState.timer);
  if ($("#view-campaigns").hidden) return;
  if (campaignViewState.items.some(item=>["queued","running","stopping"].includes(item.status))) {
    campaignViewState.timer=setTimeout(()=>refreshCampaigns().catch(e=>$("#campaign-error").textContent=e.message),2000);
  }
}

async function refreshCampaigns() {
  if (campaignViewState.loading) return;
  campaignViewState.loading=true;
  try {
    const data=await api("/api/campaigns"); campaignViewState.items=data.campaigns;
    const select=$("#campaign-select"),previous=campaignViewState.selected || select.value;
    select.replaceChildren();
    for (const item of data.campaigns) { const option=el("option","",`${item.name} · ${item.status} · ${item.attempts} attempts`); option.value=item.id; select.append(option); }
    if (!data.campaigns.length) { const option=el("option","","No campaigns yet"); option.value=""; select.append(option); }
    if (data.campaigns.some(item=>item.id===previous)) select.value=previous;
    campaignViewState.selected=select.value || null;
    $("#campaign-list").replaceChildren(el("p","small muted",`${data.campaigns.length} saved campaigns. Interrupted campaigns require an explicit resume; interrupted trials require an explicit retry.`));
    if (campaignViewState.selected) {
      const selected=campaignViewState.selected, detail=await api(`/api/campaign/${selected}`);
      if (selected===campaignViewState.selected) { campaignViewState.detail=detail; renderCampaignDetail(detail); }
    } else $("#campaign-detail").replaceChildren(el("p","empty","No campaigns have been created."));
  } finally { campaignViewState.loading=false; scheduleCampaignRefresh(); }
}

async function campaignAction(action,jobId) {
  const selected=campaignViewState.selected; if (!selected) return;
  try {
    const detail=await api("/api/campaign/action",{id:selected,action,...(jobId ? {job_id:jobId} : {})});
    campaignViewState.detail=detail; renderCampaignDetail(detail); await refreshCampaigns();
  } catch(e) { $("#campaign-error").textContent=e.message; }
}

function renderCampaignDetail(record) {
  const parent=$("#campaign-detail"); parent.replaceChildren();
  parent.append(el("h3","",record.name),el("p","small",`${record.status} · ${record.scenario_count} fixed scenarios per trial · ${record.original_job_count} original trials · ${record.jobs.length} total attempts`));
  const actions=el("div","quality-actions"),cancel=el("button","secondary","Cancel campaign"),resume=el("button","secondary","Resume queued trials"),download=el("button","secondary","Export campaign evidence");
  cancel.disabled=!["queued","running","stopping","interrupted"].includes(record.status);
  resume.disabled=!["interrupted"].includes(record.status) || !record.jobs.some(job=>job.status==="queued");
  cancel.addEventListener("click",()=>campaignAction("cancel")); resume.addEventListener("click",()=>campaignAction("resume"));
  download.addEventListener("click",()=>{
    const url=URL.createObjectURL(new Blob([JSON.stringify(record,null,2)],{type:"application/json"}));
    const link=el("a"); link.href=url; link.download=`spades-campaign-${record.id}.json`; document.body.append(link); link.click(); link.remove(); setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  actions.append(cancel,resume,download); parent.append(actions);
  const table=el("table"),head=el("thead"),titles=el("tr"),body=el("tbody");
  for (const name of ["Trial / attempt","Model / defense / parameters","Status","Evidence / action"]) { const th=el("th","",name); th.scope="col"; titles.append(th); }
  head.append(titles); table.append(head); const latest=new Map(record.jobs.map(job=>[job.trial_id,job.id]));
  for (const job of record.jobs) {
    const row=el("tr"),operations=el("td");
    if (job.run_id) { const open=el("button","case-link",`Open ${job.run_id.slice(0,8)}`); open.addEventListener("click",async()=>{try {await loadReport(job.run_id);view("overview");} catch(e){error(e.message);}}); operations.append(open); }
    if (["queued","starting","running","stopping"].includes(job.status)) { const stop=el("button","secondary","Cancel trial"); stop.addEventListener("click",()=>campaignAction("cancel_job",job.id)); operations.append(stop); }
    if (["failed","interrupted","cancelled","completed_with_errors"].includes(job.status) && latest.get(job.trial_id)===job.id) { const retry=el("button","secondary","Retry as new attempt"); retry.addEventListener("click",()=>campaignAction("retry_job",job.id)); operations.append(retry); }
    const status=el("td","",job.status); if (job.error) status.append(el("p","small error",job.error));
    row.append(el("td","",`${job.trial_id.slice(0,8)} · attempt ${job.attempt}`),el("td","",`${job.config.model} · ${job.config.policy} · seed ${job.config.generation.seed} · trust ${job.config.threshold ?? record.base_config.threshold} · top ${job.config.k ?? record.base_config.k} · temperature ${job.config.generation.temperature}`),status,operations); body.append(row);
  }
  table.append(body); const scroll=el("div","table-scroll"); scroll.append(table); parent.append(scroll);
  const reliability=record.reliability;
  parent.append(el("h3","","Configuration comparison"),el("p","small muted","Each row groups identical settings across seeds. Rates describe measured complete trials; exclusions and weight changes remain visible below. These observations do not establish a statistically superior configuration."));
  const comparison=el("table"),comparisonHead=el("thead"),comparisonTitles=el("tr"),comparisonBody=el("tbody");
  for(const name of ["Model / defense","Trust / depth / temperature","Complete / planned trials","Task success / descriptive interval"]){const th=el("th","",name);th.scope="col";comparisonTitles.append(th);}
  comparisonHead.append(comparisonTitles);comparison.append(comparisonHead);
  for(const group of reliability.groups){const c=group.configuration,row=el("tr");row.append(el("td","",`${c.model} · ${c.policy}${c.mode==="demo" ? " · DEMO":""}${group.identity_changed ? " · WEIGHTS CHANGED":""}`),el("td","",`${c.threshold} / ${c.k} / ${c.generation.temperature} · ${c.retrieval.method} · ${c.retrieval.chunk_size}/${c.retrieval.overlap} · ${c.retrieval.rerank}`),el("td","",`${group.completed_trials} / ${group.planned_trials}`),el("td","",`${percent(group.task_trial_rate)} · ${campaignInterval(group.task_trial_interval)}`));comparisonBody.append(row);}
  comparison.append(comparisonBody);const comparisonScroll=el("div","table-scroll");comparisonScroll.append(comparison);parent.append(comparisonScroll);
  parent.append(el("h3","","Repeated-trial reliability"),el("p","small muted",`${reliability.logical_trials} logical trials · ${reliability.attempts} attempts · ${reliability.superseded_attempts} superseded attempts. A successful trial must pass every frozen case.`));
  for (const group of reliability.groups) {
    const section=el("section","panel");
    section.append(el("h4","",`${group.configuration.model} · ${group.configuration.policy} · ${group.configuration.mode==="demo" ? "DEMONSTRATION" : "LOCAL MODEL"}`),
      el("p","small",`Trust ${group.configuration.threshold} · top ${group.configuration.k} chunks · temperature ${group.configuration.generation.temperature}`),
      el("p","small",`${group.successful_trials}/${group.completed_trials} completed trials passed every task · ${percent(group.task_trial_rate)} · descriptive 95% Wilson interval ${campaignInterval(group.task_trial_interval)}`),
      el("p","small muted",`${group.planned_trials} logical trials · ${group.excluded_trials.length} excluded · seeds ${group.seeds.join(", ")}`));
    if (group.identity_changed) section.append(el("p","error","Recorded model weights changed within this configuration. These results contain mixed identities and are not a controlled comparison."));
    const cases=el("table"),caseHead=el("thead"),caseTitles=el("tr"),caseBody=el("tbody");
    for (const title of ["Scenario","Task passes / failures","Task pass rate / interval","Attack matches"]) { const th=el("th","",title); th.scope="col"; caseTitles.append(th); }
    caseHead.append(caseTitles); cases.append(caseHead);
    for (const item of group.per_case) { const tr=el("tr"); tr.append(el("td","",item.case_id),el("td","",`${item.task_passes} / ${item.task_failures}`),el("td","",`${percent(item.task_pass_rate)} · ${campaignInterval(item.task_interval)}`),el("td","",`${item.attack_matches}/${item.attack_observations} · ${percent(item.attack_match_rate)}`)); caseBody.append(tr); }
    cases.append(caseBody); const wrap=el("div","table-scroll"); wrap.append(cases); section.append(wrap);
    if (group.excluded_trials.length) { const excluded=el("details"); excluded.append(el("summary","","Inspect excluded trials")); group.excluded_trials.forEach(item=>excluded.append(el("p","small",`${item.job_id.slice(0,8)} · seed ${item.seed}: ${item.reason}`))); section.append(excluded); }
    parent.append(section);
  }
  const limits=el("ul","small muted"); reliability.limitations.forEach(text=>limits.append(el("li","",text))); parent.append(limits);
}

$("#refresh-campaigns").addEventListener("click",()=>refreshCampaigns().catch(e=>$("#campaign-error").textContent=e.message));
$("#campaign-select").addEventListener("change",()=>{campaignViewState.selected=$("#campaign-select").value;refreshCampaigns().catch(e=>$("#campaign-error").textContent=e.message);});
$("#campaign-edit-base").addEventListener("click",()=>{syncSelectionControls();$("#new-dialog").showModal();});
$("#preview-campaign").addEventListener("click",async()=>{try {$("#campaign-error").textContent="";await previewCampaign();} catch(e){$("#campaign-error").textContent=e.message;}});
$("#campaign-form").addEventListener("submit",async event=>{
  event.preventDefault(); const button=$("#create-campaign"); button.disabled=true; $("#campaign-error").textContent="";
  try {const body=await previewCampaign(); const created=await api("/api/campaign/create",body);campaignViewState.selected=created.id;await refreshCampaigns();toast("Campaign queued. Trials execute sequentially using the frozen selection.");}
  catch(e){$("#campaign-error").textContent=e.message;}
  finally{button.disabled=false;}
});
document.querySelector('.nav-item[data-view="campaigns"]').addEventListener("click",renderCampaigns);
renderCampaigns();
