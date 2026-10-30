"use strict";

function isComparisonRegression(item) {
  return item.task === "regressed" || item.attack === "new match" || (item.field_changes || []).some(change=>change.change==="regressed");
}

function filterComparisonCases(cases, scope = "changed", query = "") {
  const search = query.trim().toLowerCase();
  return cases.filter(item => {
    const regression = isComparisonRegression(item);
    const improvement = item.task === "improved" || item.attack === "resolved match" || (item.field_changes || []).some(change=>change.change==="improved");
    const fields = (item.field_changes || []).length>0;
    const evidence = Boolean(item.citation_changes?.changed || item.decision_changes?.length);
    const unmeasured = item.task === "unmeasured";
    const matches = scope === "all" || (scope === "changed" && (regression || improvement || fields || evidence)) ||
      (scope === "regressions" && regression) || (scope === "improvements" && improvement) ||
      (scope === "attacks" && ["new match", "resolved match"].includes(item.attack)) ||
      (scope === "fields" && fields) || (scope === "evidence" && evidence) ||
      (scope === "unmeasured" && unmeasured);
    return matches && [item.case_id, item.task, item.attack,...(item.field_changes || []).map(change=>change.field)].join(" ").toLowerCase().includes(search);
  });
}

function comparisonExport(comparison, reference, candidate, scope, query) {
  const cases = filterComparisonCases(comparison.cases, scope, query);
  return {export_type: "filtered_comparison", exported_at: new Date().toISOString(),
    reference: {run_id: reference.run_id, model: reference.model, mode: reference.mode, configuration: reference.configuration},
    candidate: {run_id: candidate.run_id, model: candidate.model, mode: candidate.mode, configuration: candidate.configuration},
    filters: {scope, search: query}, full_comparison_counts: comparison.counts,
    compared_case_count: comparison.cases.length, exported_case_count: cases.length, cases};
}

if (typeof module !== "undefined" && module.exports) module.exports = {filterComparisonCases, comparisonExport, isComparisonRegression};
