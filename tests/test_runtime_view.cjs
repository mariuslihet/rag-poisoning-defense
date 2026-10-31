const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../spades/web/app.js'),'utf8');
const start=source.indexOf('async function refreshRuntime()');
const end=source.indexOf('\nfunction updateProgress',start);
assert.ok(start>=0 && end>start,'runtime function must exist for regression coverage');

async function render(models,{ollama=true,chromadb=true,method='hybrid'}={}) {
  const elements=new Map();
  const element=()=>({value:'',children:[],options:[],disabled:false,textContent:'',classList:{toggle(){}},
    replaceChildren(...items){this.children=items;this.options=this.children;},append(...items){this.children.push(...items);this.options=this.children;}});
  for (const id of ['#runtime-pill','#run-model','#runtime-components','#runtime-error','#run-mode','#run-retrieval-method']) elements.set(id,element());
  elements.get('#run-retrieval-method').value=method;
  elements.get('#run-model').value='qwen2.5:7b-instruct-q4_K_M';
  const localOption=element(); elements.get('#run-mode').querySelector=()=>localOption;
  const context={state:{},api:async()=>({models,ollama,chromadb,ready:false,error:null}),$:id=>elements.get(id),
    el:(tag,cls,text)=>Object.assign(element(),{tag,className:cls,textContent:text}),
    setModelChoice:value=>{elements.get('#run-model').value=value;}};
  const refresh=vm.runInNewContext(source.slice(start,end)+'\nrefreshRuntime;',context);
  await refresh();
  return {elements,localOption};
}

test('runtime cards initialize without a readiness variable collision',async()=>{
  const {elements,localOption}=await render(['qwen2.5:7b-instruct-q4_K_M','nomic-embed-text:latest']);
  assert.equal(elements.get('#runtime-components').children.length,3);
  assert.equal(localOption.disabled,false);
  assert.match(elements.get('#runtime-pill').textContent,/ready/);
});
test('an alternative installed model is usable even when default weights are absent',async()=>{
  const {elements,localOption}=await render(['qwen3.5:4b','nomic-embed-text:latest']);
  assert.equal(localOption.disabled,false);
  assert.deepEqual(Array.from(elements.get('#run-model').children,option=>option.value),['qwen3.5:4b']);
});
test('missing embedding weights disable local execution without breaking the page',async()=>{
  const {elements,localOption}=await render(['qwen3.5:4b']);
  assert.equal(localOption.disabled,true);
  assert.equal(elements.get('#runtime-components').children.length,3);
  assert.match(elements.get('#runtime-pill').textContent,/setup needed/);
});

test('BM25 can use installed generation weights without embeddings or vector runtime',async()=>{
  const {localOption}=await render(['qwen3.5:4b'],{chromadb:false,method:'bm25'});
  assert.equal(localOption.disabled,false);
});
