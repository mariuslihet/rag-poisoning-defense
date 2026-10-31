"use strict";

const findingView={sourceRevision:0,editor:null};
const findingStatuses={open:"Open",investigating:"Investigating",fixed:"Fixed",accepted:"Accepted risk"};

function findingTags(value){return value.split(",").map(tag=>tag.trim()).filter(Boolean);}
function findingDownload(content,name){const url=URL.createObjectURL(new Blob([JSON.stringify(content,null,2)],{type:"application/json"}));const link=el("a");link.href=url;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function findingReferenceText(reference){return `${reference.case_id} · run ${reference.run_id.slice(0,8)} · ${reference.identity.mode==="local" ? reference.identity.model:"DEMONSTRATION"} · ${reference.identity.profile} · dataset ${reference.identity.dataset_version || "not recorded"}`;}
function findingOpenEvidence(reference){return loadReport(reference.run_id).then(()=>{view("overview");const row=state.report.results.find(item=>item.case_id===reference.case_id);if(!row)throw new Error("The linked case is no longer available.");openCase(row);}).catch(e=>{$("#finding-error").textContent=e.message;});}

async function loadFindingCases(selectedCase=null){
  const runId=$("#finding-source-run").value,revision=++findingView.sourceRevision;
  $("#finding-create").disabled=true;$("#finding-source-case").replaceChildren();$("#finding-source-message").textContent="";
  if(!runId)return;
  try{
    const report=await api(`/api/report/${runId}`);if(revision!==findingView.sourceRevision)return;
    for(const row of report.results){const option=el("option","",`${row.case_id} · ${row.error ? "runtime error":row.secured_success ? "attack matched":row.secured_utility ? "task passed":"task needs review"}`);option.value=row.case_id;$("#finding-source-case").append(option);}
    if(selectedCase && report.results.some(row=>row.case_id===selectedCase))$("#finding-source-case").value=selectedCase;
    $("#finding-create").disabled=!report.results.length;$("#finding-source-message").textContent=`${report.results.length} saved observations. The finding keeps an exact fingerprint of its selected case evidence.`;
  }catch(e){if(revision===findingView.sourceRevision)$("#finding-error").textContent=e.message;}
}

async function openFindingDraft(runId,caseId){
  view("findings");renderFindings();
  if(!(state.runs || []).some(run=>run.run_id===runId)){await refreshRuns();renderFindings();}
  $("#finding-source-run").value=runId;$("#finding-title").value=`Review ${caseId}`.slice(0,160);$("#finding-error").textContent="";
  await loadFindingCases(caseId);
  $("#finding-title").focus();
}

function findingHistory(record){
  $("#finding-history-title").textContent=record.title;const parent=$("#finding-history-content");parent.replaceChildren(el("p","small",`Original evidence: ${findingReferenceText(record.source)} · case SHA-256 ${record.source.row_sha256}`));
  for(const event of record.history.slice().reverse()){const card=el("article","panel");card.append(el("h3","",`Revision ${event.revision} · ${findingStatuses[event.status]}`),el("p","small",`${date(event.updated_at)} · ${event.severity} · owner ${event.assignee || "unassigned"}`),el("p","",event.note || "No decision note."));const detail=el("details");detail.append(el("summary","","Inspect immutable event"),el("pre","",JSON.stringify(event,null,2)));card.append(detail);parent.append(card);}
  $("#finding-history-dialog").showModal();
}

function findingStatusControls(){
  const status=$("#finding-edit-status").value;$("#finding-verification-section").hidden=status!=="fixed";
  $("#finding-edit-note").required=status==="accepted";$("#finding-verification-run").required=status==="fixed";
  $("#finding-editor-message").textContent=status==="accepted" ? "Acceptance records an operator decision and requires a written rationale; it does not certify a fix.":status==="fixed" ? "Saving validates the selected original and verification references without running a model.":"Saving retains every earlier state and decision note.";
  if(status==="fixed" && findingView.editor && (!findingView.editor.source.identity.dataset_version || !findingView.editor.source.identity.grading_version))$("#finding-editor-message").textContent="The original experiment lacks a complete recorded dataset/grading identity, so a verified fix cannot be certified from this reference. Keep it under investigation or record an accepted-risk decision with a rationale.";
}

function editFinding(record){
  findingView.editor=record;$("#finding-editor-title").textContent="Update finding";$("#finding-editor-revision").textContent=`Editing revision ${record.revision}. Original source evidence cannot be replaced.`;
  for(const key of ["title","status","severity","assignee","note"])$("#finding-edit-"+key).value=record[key];$("#finding-edit-tags").value=record.tags.join(", ");$("#finding-editor-error").textContent="";
  const select=$("#finding-verification-run");select.replaceChildren(el("option","","Choose a later compatible completed run"));select.firstElementChild.value="";
  for(const run of state.runs || []){
    const c=run.configuration || {},s=record.source.identity;
    if(run.run_id===record.source.run_id || run.status!=="completed" || new Date(run.created_at)<=new Date(record.source.created_at) || (s.mode==="local" && run.mode!=="local") || (c.profile || "foundation")!==s.profile || c.dataset_version!==s.dataset_version || c.grading_version!==s.grading_version)continue;
    const option=el("option","",runName(run));option.value=run.run_id;select.append(option);
  }
  if(record.verification && [...select.options].some(option=>option.value===record.verification.run_id))select.value=record.verification.run_id;
  $("#finding-verification-case").textContent=`Required scenario: ${record.source.case_id}. The server validates that this exact case passed.`;
  findingStatusControls();$("#finding-editor-dialog").showModal();
}

function renderFindings(){
  const records=state.workspace.findings || [],select=$("#finding-source-run"),previous=select.value;
  select.replaceChildren(el("option","","Choose original saved experiment"));select.firstElementChild.value="";
  for(const run of state.runs || []){const option=el("option","",runName(run));option.value=run.run_id;select.append(option);}if([...select.options].some(option=>option.value===previous))select.value=previous;
  const summary=$("#finding-summary");summary.replaceChildren();for(const [status,label] of Object.entries(findingStatuses)){const button=el("button","diagnostic-tile",`${label}: ${records.filter(record=>record.status===status).length}`);button.addEventListener("click",()=>{$("#finding-status-filter").value=status;renderFindings();});summary.append(button);}
  const query=$("#finding-search").value.trim().toLowerCase(),status=$("#finding-status-filter").value,severity=$("#finding-severity-filter").value;
  const visible=records.filter(record=>(!status || record.status===status) && (!severity || record.severity===severity) && [record.title,record.note,record.assignee,record.source.case_id,...record.tags].join(" ").toLowerCase().includes(query)).slice().sort((a,b)=>b.updated_at.localeCompare(a.updated_at));
  $("#finding-count").textContent=`${visible.length} of ${records.length} findings shown. Fixed and accepted findings remain in the register.`;
  const parent=$("#finding-list");parent.replaceChildren();
  for(const record of visible){const card=el("article","panel");card.append(el("span","eyebrow",`${findingStatuses[record.status]} · ${record.severity} · revision ${record.revision}`),el("h3","",record.title),el("p","small",`Owner: ${record.assignee || "unassigned"} · tags: ${record.tags.join(", ") || "none"}`),el("p","",record.note || "No decision note."),el("p","evidence-meta",`Original: ${findingReferenceText(record.source)}`));if(record.verification)card.append(el("p","evidence-meta",`Last verification: ${findingReferenceText(record.verification)}`));
    const actions=el("div","quality-actions"),edit=el("button","primary","Review / update"),source=el("button","secondary","Original evidence"),history=el("button","secondary","Decision history"),download=el("button","secondary","Export finding");edit.addEventListener("click",()=>editFinding(record));source.addEventListener("click",()=>findingOpenEvidence(record.source));history.addEventListener("click",()=>findingHistory(record));download.addEventListener("click",()=>findingDownload({export_type:"finding_record",exported_at:new Date().toISOString(),finding:record},`spades-finding-${record.id}.json`));actions.append(edit,source,history,download);
    if(record.verification){const verified=el("button","secondary","Verification evidence");verified.addEventListener("click",()=>findingOpenEvidence(record.verification));actions.append(verified);}card.append(actions);parent.append(card);
  }
  if(!visible.length)parent.append(el("p","empty",records.length ? "No findings match these filters.":"Create a finding from a saved experiment or an investigation result to begin tracking remediation."));
  $("#finding-export-all").disabled=!records.length;
}

$("#finding-source-run").addEventListener("change",()=>loadFindingCases());
$("#finding-create-form").addEventListener("submit",async event=>{event.preventDefault();const button=$("#finding-create");button.disabled=true;$("#finding-error").textContent="";try{const data=await api("/api/finding",{title:$("#finding-title").value,run_id:$("#finding-source-run").value,case_id:$("#finding-source-case").value,severity:$("#finding-severity").value,assignee:$("#finding-assignee").value,note:$("#finding-note").value,tags:findingTags($("#finding-tags").value)});updateWorkspace(data);renderFindings();$("#finding-title").value="";$("#finding-note").value="";toast("Finding created with its original evidence fingerprint.");}catch(e){$("#finding-error").textContent=e.message;}finally{button.disabled=!$("#finding-source-case").value;}});
$("#finding-edit-status").addEventListener("change",findingStatusControls);
$("#finding-editor-form").addEventListener("submit",async event=>{event.preventDefault();const record=findingView.editor;if(!record)return;const button=$("#finding-editor-save");button.disabled=true;$("#finding-editor-error").textContent="";try{const body={id:record.id,revision:record.revision,status:$("#finding-edit-status").value,title:$("#finding-edit-title").value,severity:$("#finding-edit-severity").value,assignee:$("#finding-edit-assignee").value,note:$("#finding-edit-note").value,tags:findingTags($("#finding-edit-tags").value)};if(body.status==="fixed")body.verification={run_id:$("#finding-verification-run").value,case_id:record.source.case_id};updateWorkspace(await api("/api/finding/update",body));renderFindings();$("#finding-editor-dialog").close();toast("Finding revision saved. Earlier decisions remain in history.");}catch(e){$("#finding-editor-error").textContent=e.message;}finally{button.disabled=false;}});
for(const id of ["finding-search","finding-status-filter","finding-severity-filter"])$("#"+id).addEventListener(id==="finding-search" ? "input":"change",renderFindings);
$("#finding-refresh").addEventListener("click",async()=>{try{updateWorkspace(await api("/api/workspace"));await refreshRuns();renderFindings();toast("Finding register refreshed.");}catch(e){$("#finding-error").textContent=e.message;}});
$("#finding-export-all").addEventListener("click",()=>findingDownload({export_type:"finding_register",exported_at:new Date().toISOString(),findings:state.workspace.findings || []},"spades-finding-register.json"));
document.querySelector('[data-view="findings"]').addEventListener("click",renderFindings);
renderFindings();
