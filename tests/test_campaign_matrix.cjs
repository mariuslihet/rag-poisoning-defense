const {test}=require('node:test');
const assert=require('node:assert/strict');
const {parseCampaignSweep,campaignMatrixSize}=require('../spades/web/campaign-matrix.js');

test('blank sweeps inherit base settings while decimal lists preserve operator order',()=>{
  assert.equal(parseCampaignSweep(' ',0,1),null);
  assert.deepEqual(parseCampaignSweep('.9, .5 1',0,1),[.9,.5,1]);
  assert.deepEqual(parseCampaignSweep('5, 20',1,50,true),[5,20]);
});
test('invalid, duplicate and excessive sweep values are rejected',()=>{
  for(const value of ['true','NaN','Infinity','0x1','-1','0,0.0',',,,','2',Array(11).fill('.5').join(',')])assert.throws(()=>parseCampaignSweep(value,0,1));
  assert.throws(()=>parseCampaignSweep('1.5',1,50,true));
});
test('workload multiplication includes all sweep axes and retains legacy counts',()=>{
  const base={models:['a','b'],policies:['strict'],seeds:[1,2,3]};
  assert.equal(campaignMatrixSize(base),6);
  assert.equal(campaignMatrixSize({...base,thresholds:[.5,.9],retrieval_depths:[5,10],temperatures:[0,1]}),48);
});

test('retrieval variants multiply the declared campaign budget',()=>{
  assert.equal(campaignMatrixSize({models:['a'],policies:['strict','sanitize'],seeds:[42],retrieval_variants:[{method:'dense'},{method:'bm25'},{method:'hybrid'}]}),6);
});
