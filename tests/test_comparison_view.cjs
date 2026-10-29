const {test} = require('node:test');
const assert = require('node:assert/strict');
const {filterComparisonCases, comparisonExport} = require('../spades/web/comparison-view.js');

const cases = [
  {case_id:'hr-1', task:'unchanged', attack:'not applicable'},
  {case_id:'hr-2', task:'regressed', attack:'unchanged'},
  {case_id:'api-1', task:'improved', attack:'new match'},
  {case_id:'api-2', task:'unchanged', attack:'resolved match'},
  {case_id:'hr-3', task:'unmeasured', attack:'unmeasured'},
];
const ids = rows => rows.map(row => row.case_id);

test('changed view includes improvements and regressions but excludes unmeasured cases', () => {
  assert.deepEqual(ids(filterComparisonCases(cases)), ['hr-2','api-1','api-2']);
  assert.deepEqual(ids(filterComparisonCases(cases,'unmeasured')), ['hr-3']);
});
test('task and attack regression filters preserve mixed outcomes', () => {
  assert.deepEqual(ids(filterComparisonCases(cases,'regressions')), ['hr-2','api-1']);
  assert.deepEqual(ids(filterComparisonCases(cases,'improvements')), ['api-1','api-2']);
  assert.deepEqual(ids(filterComparisonCases(cases,'attacks')), ['api-1','api-2']);
});
test('search composes with scope and handles empty results', () => {
  assert.deepEqual(ids(filterComparisonCases(cases,'regressions',' API ')), ['api-1']);
  assert.deepEqual(filterComparisonCases(cases,'changed','missing'), []);
  assert.equal(filterComparisonCases(cases,'all').length, 5);
});
test('filtering does not mutate source evidence', () => {
  const original = JSON.stringify(cases);
  filterComparisonCases(cases,'regressions');
  assert.equal(JSON.stringify(cases), original);
});
test('export identifies both runs and distinguishes subset size from full counts', () => {
  const reference = {run_id:'a',model:'qwen',mode:'local',configuration:{policy:'strict'}};
  const candidate = {run_id:'b',model:'qwen',mode:'local',configuration:{policy:'sanitize'}};
  const comparison = {cases,counts:{task_regressions:1,new_attack_matches:1}};
  const result = comparisonExport(comparison,reference,candidate,'regressions','api');
  assert.equal(result.export_type,'filtered_comparison');
  assert.equal(result.reference.run_id,'a');
  assert.equal(result.candidate.configuration.policy,'sanitize');
  assert.equal(result.compared_case_count,5);
  assert.equal(result.exported_case_count,1);
  assert.equal(result.full_comparison_counts.task_regressions,1);
  assert.deepEqual(ids(result.cases),['api-1']);
  assert.deepEqual(result.filters,{scope:'regressions',search:'api'});
  assert.ok(Number.isFinite(Date.parse(result.exported_at)));
});
