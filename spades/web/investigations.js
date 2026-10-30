"use strict";

const investigationState={result:null,revision:0,view:null};
const investigationKeys=["query","mode","profile","model","policy","domain","category","issue","from_date","to_date"];
const investigationIssues={runtime:"Runtime error",generation_limit:"Response limit reached",empty_answer:"Empty answer",leakage:"Restricted data disclosed",attack:"Attack objective matched",retrieval:"Required source not retrieved",defense:"Required source blocked",budget:"Required source omitted",format:"Invalid output contract",fields:"Incorrect answer fields",citations:"Citation problems",utility:"Foundation fact failed"};

function investigationFilters(){return Object.fromEntries(investigationKeys.map(key=>[key,$("#investigation-"+key).value]));}
function invalidateInvestigation(){investigationState.revision++;investigationState.result=null;$("#investigation-results").replaceChildren(el("p","empty","Search to load an evidence snapshot."));$("#investigation-export").disabled=true;$("#investigation-previous").disabled=true;$("#investigation-next").disabled=true;$("#investigation-count").textContent="";}
function renderInvestigationLibrary(){
  const select=$("#investigation-library"),previous=select.value;select.replaceChildren(el("option","","Choose a saved investigation"));select.firstElementChild.value="";
  for(const record of state.workspace.investigations || []){const option=el("option","",`${record.name} · revision ${record.revision}`);option.value=record.id;select.append(option);}
  if([...select.options].some(option=>option.value===previous))select.value=previous;
}
async function searchInvestigation(offset=0){
  const revision=++investigationState.revision,button=$("#investigation-search-button");button.disabled=true;$("#investigation-error").textContent="";
  try{
    const result=await api("/api/investigation/search",{filters:investigationFilters(),offset,limit:25});if(revision!==investigationState.revision)return;
    investigationState.result=result;const parent=$("#investigation-results");parent.replaceChildren();
    $("#investigation-count").textContent=`${result.total} matching observations in ${result.matching_runs} runs · ${result.results.length ? result.offset+1:0}–${result.offset+result.results.length} shown. Repeated scenario IDs in different runs remain separate observations.`;
    const counts=el("div","diagnostic-grid");for(const [code,count] of Object.entries(result.issue_counts)){const button=el("button","diagnostic-tile",`${investigationIssues[code] || code}: ${count}`);button.addEventListener("click",()=>{$("#investigation-issue").value=code;invalidateInvestigation();searchInvestigation();});counts.append(button);}parent.append(counts);
    const limits=el("details");limits.append(el("summary","","Search boundaries and exclusions"));const list=el("ul","small muted");result.limitations.forEach(text=>list.append(el("li","",text)));limits.append(el("p","small",`${result.skipped_invalid_records} invalid records skipped · snapshot ${date(result.generated_at)}`),list);parent.append(limits);
    for(const item of result.results){
      const card=el("article","panel investigation-card");card.append(el("h3","",item.case_id),el("p","small",`${item.mode==="local" ? "LOCAL MODEL":"DEMONSTRATION"} · ${item.model} · ${item.policy} · ${item.domain} · ${date(item.created_at)}`),el("p","",item.query),el("pre","investigation-excerpt",item.excerpt));
      card.append(el("p","small",item.issues.length ? item.issues.map(code=>investigationIssues[code] || code).join(" · "):"No recorded diagnostic issues"));
      if(item.failed_fields.length)card.append(el("p","small",`Failed fields: ${item.failed_fields.map(check=>check.field).join(", ")}`));
      const details=el("details");details.append(el("summary","","Inspect recorded identity and findings"),el("pre","",JSON.stringify({run_id:item.run_id,configuration:item.configuration,failed_fields:item.failed_fields,source_trace:item.source_trace,error:item.error},null,2)));card.append(details);
      const open=el("button","secondary","Open original case evidence");open.addEventListener("click",async()=>{try{await loadReport(item.run_id);view("overview");openCase(state.report.results.find(row=>row.case_id===item.case_id));}catch(e){$("#investigation-error").textContent=e.message;}});card.append(open);parent.append(card);
    }
    if(!result.results.length)parent.append(el("p","empty","No observations match these filters."));
    $("#investigation-export").disabled=false;$("#investigation-previous").disabled=offset===0;$("#investigation-next").disabled=result.next_offset===null;
  }catch(e){if(revision===investigationState.revision){invalidateInvestigation();$("#investigation-error").textContent=e.message;}}
  finally{button.disabled=false;}
}
$("#investigation-form").addEventListener("submit",event=>{event.preventDefault();searchInvestigation();});
$("#investigation-form").addEventListener("input",invalidateInvestigation);$("#investigation-form").addEventListener("change",invalidateInvestigation);
$("#investigation-previous").addEventListener("click",()=>{if(investigationState.result)searchInvestigation(Math.max(0,investigationState.result.offset-25));});
$("#investigation-next").addEventListener("click",()=>{if(investigationState.result?.next_offset!==null && investigationState.result)searchInvestigation(investigationState.result.next_offset);});
$("#investigation-export").addEventListener("click",()=>{if(!investigationState.result)return;const content={export_type:"investigation_page",...investigationState.result,exported_count:investigationState.result.results.length};const url=URL.createObjectURL(new Blob([JSON.stringify(content,null,2)],{type:"application/json"}));const link=el("a");link.href=url;link.download="spades-investigation-page.json";document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$("#investigation-library").addEventListener("change",()=>{
  const record=(state.workspace.investigations || []).find(item=>item.id===$("#investigation-library").value);if(!record){investigationState.view=null;$("#investigation-name").value="";return;}
  investigationState.view=record;for(const key of investigationKeys)$("#investigation-"+key).value=record.filters[key] || "";$("#investigation-name").value=record.name;invalidateInvestigation();$("#investigation-error").textContent="";toast("Saved filters loaded. Search again to read current evidence.");
});
async function saveInvestigation(asNew){
  $("#investigation-error").textContent="";const record=asNew ? null:investigationState.view;
  try{const data=await api("/api/investigation/view",{name:$("#investigation-name").value,filters:investigationFilters(),...(record ? {id:record.id,revision:record.revision}:{})});updateWorkspace(data);renderInvestigationLibrary();const saved=data.investigations.find(item=>item.name===$("#investigation-name").value.trim());investigationState.view=saved;$("#investigation-library").value=saved.id;toast("Investigation filters saved. Evidence remains in its original reports.");}catch(e){$("#investigation-error").textContent=e.message;}
}
$("#investigation-save").addEventListener("click",()=>saveInvestigation(false));$("#investigation-save-new").addEventListener("click",()=>saveInvestigation(true));
document.querySelector('[data-view="investigations"]').addEventListener("click",renderInvestigationLibrary);
for(const [code,label] of Object.entries(investigationIssues)){const option=el("option","",label);option.value=code;$("#investigation-issue").append(option);}
renderInvestigationLibrary();invalidateInvestigation();
