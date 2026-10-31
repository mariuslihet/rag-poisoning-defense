"use strict";

const portableState={selected:new Set(),report:null,cases:new Set(),revision:0,verificationRevision:0};

function portableDownload(data,filename){const url=URL.createObjectURL(data),link=el("a");link.href=url;link.download=filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function renderBundleRuns(){
  const parent=$("#bundle-runs"),query=$("#bundle-search").value.trim().toLowerCase();parent.replaceChildren();
  const runs=state.runs || [],available=new Set(runs.map(run=>run.run_id));for(const id of portableState.selected)if(!available.has(id))portableState.selected.delete(id);
  for(const run of runs.filter(item=>(runName(item)+" "+item.model+" "+item.run_id).toLowerCase().includes(query))){
    const label=el("label","scenario-choice"),check=el("input");check.type="checkbox";check.checked=portableState.selected.has(run.run_id);check.setAttribute("aria-label",`Include ${runName(run)}`);
    check.addEventListener("change",()=>{if(check.checked && portableState.selected.size>=10){check.checked=false;$("#bundle-message").textContent="Select at most ten experiments per bundle.";return;}check.checked?portableState.selected.add(run.run_id):portableState.selected.delete(run.run_id);updateBundleSelection();});
    label.append(check,el("span","",runName(run)));parent.append(label);
  }
  if(!parent.children.length)parent.append(el("p","empty","No saved experiments match this search."));updateBundleSelection();
}
function updateBundleSelection(){$("#bundle-selection").textContent=`${portableState.selected.size} experiments selected · ZIP limit 16 MiB · expanded evidence limit 32 MiB.`;$("#bundle-export").disabled=!portableState.selected.size;}
function renderRegressionCases(){
  const parent=$("#regression-cases");parent.replaceChildren();const rows=portableState.report?.results || [];
  for(const row of rows){const label=el("label","scenario-choice"),check=el("input");check.type="checkbox";check.checked=portableState.cases.has(row.case_id);check.setAttribute("aria-label",`Include regression ${row.case_id}`);check.addEventListener("change",()=>{check.checked?portableState.cases.add(row.case_id):portableState.cases.delete(row.case_id);updateRegressionSelection();});label.append(check,el("span","",`${row.case_id} · ${row.error ? "runtime error":row.secured_utility ? "secured task passed":"secured task requires review"}${row.category!=="baseline" && row.secured_success ? " · attack objective matched":""}`));parent.append(label);}
  if(!rows.length)parent.append(el("p","empty",portableState.report ? "This experiment has no recorded case observations.":"Choose a source experiment to inspect exact recorded scenarios."));updateRegressionSelection();
}
function updateRegressionSelection(){$("#regression-selection").textContent=`${portableState.cases.size} exact scenarios selected. Original references are validated again when the suite is saved.`;$("#regression-save").disabled=!portableState.report || !portableState.cases.size;}
function selectRegressionFailures(){portableState.cases=new Set((portableState.report?.results || []).filter(row=>row.error || row.secured_utility===false || row.secured_leak || (row.category!=="baseline" && row.secured_success)).map(row=>row.case_id));renderRegressionCases();}
function renderPortable(){
  renderBundleRuns();const select=$("#regression-run"),previous=select.value;select.replaceChildren(el("option","","Choose an experiment"));select.firstElementChild.value="";
  for(const run of state.runs || []){const option=el("option","",runName(run));option.value=run.run_id;select.append(option);}if([...select.options].some(option=>option.value===previous))select.value=previous;
  if(portableState.report && !(state.runs || []).some(run=>run.run_id===portableState.report.run_id)){portableState.report=null;portableState.cases.clear();}
  renderRegressionCases();
}
$("#bundle-search").addEventListener("input",renderBundleRuns);
$("#bundle-export").addEventListener("click",async()=>{
  const button=$("#bundle-export");button.disabled=true;$("#bundle-message").textContent="Preparing the selected evidence in memory…";
  try{const response=await fetch("/api/bundle/export",{method:"POST",headers:{"Content-Type":"application/json","X-Spades-Token":state.token},body:JSON.stringify({run_ids:[...portableState.selected],include_findings:$("#bundle-findings").checked})});if(!response.ok){const data=await response.json();throw new Error(data.error || "Bundle export failed");}portableDownload(await response.blob(),"spades-evidence-bundle.zip");$("#bundle-message").textContent="Bundle exported. Fingerprints establish payload integrity only when the manifest is trusted; they do not authenticate a publisher.";}catch(e){$("#bundle-message").textContent=e.message;}finally{updateBundleSelection();}
});
$("#bundle-upload").addEventListener("change",()=>{portableState.verificationRevision++;$("#bundle-verification").replaceChildren();const file=$("#bundle-upload").files[0];$("#bundle-verify").disabled=!file || file.size>16*1024*1024;if(file?.size>16*1024*1024)$("#bundle-verification").append(el("p","error","Choose an archive no larger than 16 MiB."));});
$("#bundle-verify").addEventListener("click",async()=>{
  const file=$("#bundle-upload").files[0];if(!file || file.size>16*1024*1024)return;const revision=++portableState.verificationRevision;$("#bundle-verify").disabled=true;$("#bundle-verification").replaceChildren(el("p","small","Verifying file fingerprints and archive bounds…"));
  try{const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(",")[1]);reader.onerror=()=>reject(new Error("Could not read the selected archive"));reader.readAsDataURL(file);});const result=await api("/api/bundle/verify",{data});if(revision!==portableState.verificationRevision)return;$("#bundle-verification").replaceChildren(el("h3","","Payload integrity verified"),el("p","",result.note),el("pre","",JSON.stringify(result,null,2)));}catch(e){if(revision===portableState.verificationRevision)$("#bundle-verification").replaceChildren(el("p","error",e.message));}finally{if(revision===portableState.verificationRevision)$("#bundle-verify").disabled=false;}
});
$("#regression-run").addEventListener("change",async()=>{
  const runId=$("#regression-run").value,revision=++portableState.revision;portableState.report=null;portableState.cases.clear();renderRegressionCases();$("#regression-message").textContent="";if(!runId)return;
  try{const payload=await api(`/api/report/${runId}`);if(revision!==portableState.revision)return;portableState.report=payload.report || payload;selectRegressionFailures();}catch(e){if(revision===portableState.revision)$("#regression-message").textContent=e.message;}
});
$("#regression-failures").addEventListener("click",selectRegressionFailures);$("#regression-all").addEventListener("click",()=>{portableState.cases=new Set((portableState.report?.results || []).map(row=>row.case_id));renderRegressionCases();});$("#regression-clear").addEventListener("click",()=>{portableState.cases.clear();renderRegressionCases();});
$("#regression-save").addEventListener("click",async()=>{
  if(!portableState.report || !portableState.cases.size)return;const button=$("#regression-save");button.disabled=true;$("#regression-message").textContent="";
  try{const workspace=await api("/api/regression-pack",{run_id:portableState.report.run_id,case_ids:[...portableState.cases],name:$("#regression-name").value,description:$("#regression-description").value});updateWorkspace(workspace);$("#regression-message").textContent="Frozen regression suite saved. Open Test suites to inspect, export or configure its exact scenarios. No inference was launched.";toast("Regression pack saved as a test suite.");}catch(e){$("#regression-message").textContent=e.message;}finally{updateRegressionSelection();}
});
document.querySelector('[data-view="portable"]').addEventListener("click",renderPortable);
renderPortable();
