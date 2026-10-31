"use strict";
const replayView={report:null,inspection:null,job:null,revision:0,timer:null};
function invalidateReplay(){replayView.revision++;replayView.inspection=null;$("#replay-start").disabled=true;$("#replay-export").disabled=true;$("#replay-request").replaceChildren();}
function replayReference(){return {run_id:$("#replay-run").value,case_id:$("#replay-case").value,arm:$("#replay-arm").value,turn:Number($("#replay-turn").value)};}
function fillReplayTurns(){
  const row=replayView.report?.results.find(item=>item.case_id===$("#replay-case").value),select=$("#replay-turn");select.replaceChildren();
  for(let i=0;i<Math.max(1,row?.turn_results?.length || 0);i++){const option=el("option","",`Turn ${i+1}`);option.value=i;select.append(option);}invalidateReplay();
}
async function renderReplays(){
  const select=$("#replay-run"),previous=select.value;select.replaceChildren(el("option","","Choose original experiment"));select.firstElementChild.value="";
  for(const run of state.runs){const option=el("option","",runName(run));option.value=run.run_id;select.append(option);}
  if([...select.options].some(option=>option.value===previous))select.value=previous;
  try{const data=await api("/api/replays"),saved=$("#replay-saved"),old=saved.value;saved.replaceChildren(el("option","","Choose saved diagnostic replay"));saved.firstElementChild.value="";
    for(const record of data.replays){const option=el("option","",`${record.source.case_id} · ${record.source.arm} · ${record.status} · ${date(record.created_at)}`);option.value=record.id;saved.append(option);}if([...saved.options].some(option=>option.value===old))saved.value=old;
  }catch(e){$("#replay-error").textContent=e.message;}
}
function showReplayJob(record){
  const parent=$("#replay-result");parent.replaceChildren(el("h3","",`Diagnostic replay · ${record.status}`),el("p","small",`${record.source.run_id} · ${record.source.case_id} · ${record.source.arm} · turn ${record.source.turn+1}`),el("p","small muted",record.note));
  if(record.error)parent.append(el("p","error",record.error));
  if(record.status==="completed")parent.append(el("p","small",record.response_changed ? "Response differs from the original capture.":"Response matches the original capture."),el("h4","","Replayed response"),el("pre","",record.response),el("h4","","Original response"),el("pre","",record.original_response ?? "No completed response was recorded"),el("pre","",JSON.stringify(record.metadata,null,2)));
  clearTimeout(replayView.timer);if(record.status==="running" && !$("#view-replay").hidden)replayView.timer=setTimeout(()=>refreshReplayJob(record.id),1500);
}
async function refreshReplayJob(id){try{const record=await api(`/api/replay/${id}`);replayView.job=record;showReplayJob(record);if(record.status!=="running")renderReplays();}catch(e){$("#replay-error").textContent=e.message;}}
$("#replay-run").addEventListener("change",async()=>{
  invalidateReplay();const revision=replayView.revision,id=$("#replay-run").value;replayView.report=null;$("#replay-case").replaceChildren();if(!id)return;
  try{const report=await api(`/api/report/${id}`);if(revision!==replayView.revision)return;replayView.report=report.report || report;for(const row of replayView.report.results){const option=el("option","",row.case_id);option.value=row.case_id;$("#replay-case").append(option);}fillReplayTurns();}catch(e){$("#replay-error").textContent=e.message;}
});
$("#replay-case").addEventListener("change",fillReplayTurns);$("#replay-arm").addEventListener("change",invalidateReplay);$("#replay-turn").addEventListener("change",invalidateReplay);
$("#replay-inspect").addEventListener("click",async()=>{
  invalidateReplay();const revision=replayView.revision;$("#replay-error").textContent="";
  try{const result=await api("/api/replay/inspect",replayReference());if(revision!==replayView.revision)return;replayView.inspection=result;
    const text=JSON.stringify(result.record,null,2);$("#replay-request").replaceChildren(el("h3","",result.record.kind==="demo" ? "Captured simulator inputs":"Captured real local-model request"),el("p","small",`SHA-256 ${result.record.sha256}`),el("p","small",result.note),el("pre","",text.slice(0,50000)));
    if(text.length>50000)$("#replay-request").append(el("p","small","Preview truncated to 50,000 characters. Export to inspect the full captured request."));
    $("#replay-start").disabled=false;$("#replay-export").disabled=false;
  }catch(e){$("#replay-error").textContent=e.message;}
});
$("#replay-start").addEventListener("click",async()=>{if(!replayView.inspection)return;$("#replay-start").disabled=true;$("#replay-error").textContent="";try{const record=await api("/api/replay/start",replayView.inspection.source);replayView.job=record;showReplayJob(record);}catch(e){$("#replay-error").textContent=e.message;}finally{$("#replay-start").disabled=!replayView.inspection;}});
$("#replay-saved").addEventListener("change",()=>{if($("#replay-saved").value)refreshReplayJob($("#replay-saved").value);});
$("#replay-export").addEventListener("click",()=>{if(!replayView.inspection)return;const url=URL.createObjectURL(new Blob([JSON.stringify(replayView.inspection,null,2)],{type:"application/json"})),link=el("a");link.href=url;link.download="spades-captured-request.json";document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$("#replay-refresh").addEventListener("click",()=>{renderReplays();if(replayView.job)refreshReplayJob(replayView.job.id);});
document.querySelector('[data-view="replay"]').addEventListener("click",()=>{renderReplays();if(replayView.job)refreshReplayJob(replayView.job.id);});
async function openReplayDraft(runId,caseId){view("replay");await renderReplays();$("#replay-run").value=runId;const report=await api(`/api/report/${runId}`);replayView.report=report.report || report;$("#replay-case").replaceChildren();for(const row of replayView.report.results){const option=el("option","",row.case_id);option.value=row.case_id;$("#replay-case").append(option);}$("#replay-case").value=caseId;fillReplayTurns();}
