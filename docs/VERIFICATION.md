# Verification record

Date: 2026-10-28. Scope: Spades 0.5.0, selective async execution, checkpoint recovery and enterprise evaluation.

## Software checks

**81 automated software tests passed.** JavaScript syntax was checked with Node.js.

Enterprise checks include:

- 96 unique cases, six business workflows, 16 distractors per case and four typed assertions per case.
- Independent procurement, recovery, leave, capacity, renewal and privacy reference calculations.
- Category/domain-balanced subsets and profile dispatch through the real dashboard API.
- Adaptive chunk reconstruction, authenticated originals and tamper rejection.
- Hybrid dense/lexical retrieval and a per-source selection bound.
- Typed numeric/boolean comparisons, explicit tolerances, duplicate keys, non-finite numeric overflow and malformed contracts.
- Required citations, valid chunk-ID citations, invented references, attack discussion versus adopted values and canary leakage.
- Model requests checked for absence of the computed procurement reference answer.
- Persistent presets and bookmark notes, CSV formula neutralization, loopback Host/origin/session protections, job conflicts and cancellation.

## Real model measurements

The requested Qwen2.5 and nomic models are installed and used with persistent ChromaDB. Eight selected enterprise cases were measured under the final hybrid-retrieval/typed-grading contract: a balanced six-workflow sample plus role-impersonation and cross-document cases. Each execution completed without runtime errors. Individual model assessments include failures.

The balanced six-case sample retrieved every required source into the secured context. Its field accuracy was 54.2%, citation coverage 70.8%, valid output rate 100% and complete rubric pass rate 0%. One of its five secured attack cases matched its target. The role-impersonation case also matched its objective after filtering. The detailed [measurement record](ENTERPRISE_RESULTS.md) identifies the scope and evidence files.

The entire 96-case enterprise profile is available to run. The measurement record makes no claim that all 96 cases have been executed or passed. Earlier 100-case foundation runs remain historical evidence with their original dataset and grading definitions.

## Browser checks

The running dashboard was inspected in the in-app browser. Checks covered text-only branding, the navy/blue/off-white layout, the enterprise metrics panel, complex-case responses, field-level expected/observed values, missing citation messages, source-record context, review-note persistence and saving an enterprise preset.

## Delivery assessment

| Criterion | Score | Evidence and remaining limits |
| --- | --- | --- |
| Accuracy | 4/5 | Typed and citation checks have independent tests; explanatory prose is not comprehensively semantically judged. |
| Completeness | 4/5 | Professional interface, detailed records, adversarial variants and real complex execution are implemented; fixtures are authored locally and the full 96-case local campaign has not been measured in this verification. |
| Clarity | 4/5 | Component grades distinguish execution, factual fields, citations and safety; interpreting conflicting business narratives still requires review. |
| Actionability | 5/5 | Models/dependencies are installed, the dashboard runs locally and a six-domain preset is saved. |
| Conciseness | 4/5 | The interface exposes summaries and expandable detail; complex evidence necessarily produces larger reports. |

Overall: 4.2/5. The laboratory supports meaningful complex evaluations and records model/defense failures transparently. It does not certify the default model as reliable for autonomous enterprise decisions.

## Async and selection verification

- Native `run_suite_async` tests prove overlapping work stays within the configured bound. Serial and parallel variants preserve case order, responses and assessment outcomes in the deterministic correctness gate.
- Cancellation finishes only already active cases; checkpoints include every completed case. A real HTTP test reads one completed result while another worker remains blocked.
- Domain and exact-ID selection, six-case defaults, explicit full-suite scope, error-only retries, incompatible-continuation rejection and lineage coverage are exercised. Reopening an original partial run skips cases completed by later child batches.
- Embedding tests verify persistence, ordering, changed-model invalidation, unknown-digest bypass, concurrent reuse and invalid-vector rejection. SQLite connections close explicitly; Chroma runtime creation and cleanup are serialized to avoid its shared-runtime startup race.
- Real local validation completed two exact foundation cases and two exact full-size enterprise cases with two workers and zero execution errors. The enterprise browser run recorded four chat requests, 45.485 seconds of evaluation wall time and 21 reused embedding vectors. These observations are not a controlled whole-model speed comparison.
- Browser checks confirmed a default preview of six scenarios, selection of precisely two procurement controls, worker phases, completion of two results, and a continuation preview excluding the user's five saved cases.
- Performance observations and their measurement scope are recorded in [ASYNC_EXECUTION.md](ASYNC_EXECUTION.md).


## Authoring, ingestion, campaigns and revision recovery — 2026-10-30

- Added cross-module tests for canonical authored execution and dataset identity, portable frozen suite round trips, field-definition changes, immutable revision archives, restoring as a new revision, stale restores, large local ingestion requests and preserved limits on ordinary run endpoints.
- Campaign tests cover exact frozen selection, per-trial seeds, sequential scheduling, active/queued cancellation, unrelated manual-run isolation, restart recovery, explicit retries and shutdown during readiness. An integrated four-job simulator matrix uses the actual RunManager and persists four complete reports. A Windows reader/atomic-rename race found by this test was fixed with a bounded retry that preserves the last complete checkpoint.
- Repeated-trial summaries exclude partial, erroneous, mismatched-settings and changed-dataset evidence; compare complete trial units and per-case frequencies; deduplicate explicit retries; and flag mixed model weight identities. Wilson intervals are descriptive and seed changes do not prove independence.
- The authoring and ingestion tests cover independent numeric and boolean references, absence of reference values from model schemas, strict source identity, revision conflicts, immutable histories, original-byte hashes, literal CSV content, DOCX archive/XML limits, PDF timeout/memory bounds and actual text-PDF extraction. PDF does not perform OCR.
- Browser verification saved an authored two-source procurement control, froze it into a portable suite, edited its description, compared revisions 1 and 2, then restored revision 1 as revision 3 while retaining both earlier revisions. The browser also configured the exact custom ID, previewed the campaign workload, started two real local trials and opened detailed field/source comparison evidence.
- Real campaign `fafee411e856438ea1cee89572496bde` used `qwen3.5:4b`, strict defense, seeds 42/43, thinking disabled, 768 response tokens, 4096 context tokens and 60-second request timeout. Runs `4b287ff0ebee4819b42f5d9a9c6f78c2` and `cabbf1ad4e89451fb7478300a45f8f18` each completed one authored scenario with zero runtime errors and passed both typed fields and required citations. This is a small functional integration check, not evidence of broad enterprise-model reliability. The displayed descriptive 95% Wilson interval for 2/2 successful trials was 34.2%–100%.
- New dashboard views and the suite history dialog were checked in the running browser. The authoring default trust-step mismatch found during browser testing was corrected, allowing its default 0.98 source trust value to be saved.

Final regression: **201 Python tests and nine JavaScript tests passed**. All four dashboard scripts pass syntax checks; the assembled HTML has 233 unique IDs and no duplicate fragment controls. The CSV staging/add/save workflow was also exercised in the browser: scenario revision 2 retained original-file provenance, while its earlier suite and campaign kept their frozen two-source definition.


## Coverage planning — 2026-10-30

Ten focused coverage tests verify exact scenario/response budgets, no-inference planning, partial-run preservation, per-case latest evidence, date normalization, safety-first ordering, domain/family tie balancing, separate errors/unmeasured states, strict execution/defense/retrieval/generation identity, seed allowance, weight-digest isolation, field/citation details and frozen custom-reference identity. The existing large-body HTTP integration test now verifies authored coverage planning and invalid-budget rejection. Existing endpoint protections apply unchanged.

Browser checks calculated the full 96-case enterprise scope with a three-scenario budget and configured exactly three cases/six paired responses in the existing experiment dialog, without starting inference. Using the displayed authored Qwen3.5 experiment restored its exact frozen definition and generation settings; coverage recognized one passed case with its recorded model digest and suggested no unseen work. Coverage export and the balanced default plan were checked separately. Coverage is a snapshot of latest compatible observations, not an aggregate model benchmark.

Final coverage regression: **211 Python tests and nine JavaScript tests passed**. The browser-exported six-case plan contains six distinct business domains and six scenario families with 12 paired responses. No model run was started during planner verification.


## Campaign parameter sweeps — 2026-10-30

- Added server-validated trust-threshold, retrieval-depth and temperature axes. The complete Cartesian product is rejected above 100 jobs; booleans, nonfinite numbers, duplicates, invalid ranges, fractional retrieval depths, empty arrays and oversized integer inputs are rejected before persistence or execution.
- Preview uses the creation planner without scheduling or saving jobs, returns every configuration and workload totals, and supplies the exact frozen scenario scope used by the dashboard on creation.
- New campaign tests run all 16 combinations of two thresholds, depths, temperatures and seeds, check eight separate reliability groups, enforce the whole-matrix limit and ensure a closed scheduler cannot accept new jobs. Real RunManager integration verifies preview is read-only and that per-trial settings survive saved reports and campaign reload.
- Three new JavaScript tests exercise sweep parsing, inherited defaults, invalid lists and workload multiplication. HTTP integration verifies the protected preview endpoint without creating a campaign.
- Browser validation created campaign `231b2cd69b6f46759b2a7a0a4da82088`: one foundation control, strict defense, seed 42, thresholds 0.5/0.9, depths 5/10 and temperatures 0/0.5. All eight simulator jobs completed and appear as eight separate configuration rows. This validates the queue and grouping; demo temperatures are recorded but are not applied to responses.
- The full regression exposed a Windows reset when rejecting an unauthenticated small POST body. Rejection now drains one bounded small read without parsing the content or weakening Host, Origin or token checks. A regression test repeats rejected token, origin and content-type requests and verifies status delivery with no workspace mutation.

Final sweep regression: **218 Python tests and 12 JavaScript tests passed**. Browser export after restart retained all three parameter axes, eight completed jobs and eight separate reliability groups. Campaign evidence is stored locally; no live model inference was used for the sweep smoke check.


## Evidence investigations — 2026-10-30

Eight focused tests cover literal response/field/source search, exact filters, UTC date boundaries, overlapping diagnostic findings, pagination with full-match counts, independent observations across runs, invalid-record skipping, no report mutation, strict request validation, view persistence, duplicate names and stale revisions. Existing HTTP integration now checks protected search/save-view routes and invalid filters.

Browser verification searched local enterprise field failures and found 21 case observations across six runs. Opening a matching result returned to its original case evidence. The filter set was saved as `Enterprise field failures`. Search and saved-view operations made no model calls. Page exports are explicitly scoped to displayed observations, and the interface warns against pooling mixed experiment configurations as a performance estimate.

Final regression: **226 Python tests and 12 JavaScript tests passed**. Investigation script syntax checks and repository whitespace checks also passed.

Additional browser checks: full-history search returned 433 observations in 26 runs; next-page navigation showed observations 26–50. The exported page contained 25 records with total 433, offset 25 and explicit `investigation_page` type. Reloading and reopening the saved view restored its filters and refreshed the original 21-observation search.


## Six-feature expansion — 2026-10-31

- Multi-turn authoring retains 1–8 stages, introduced source boundaries, unsigned simulated tool outputs and independent final references. Runner tests verify separate arm histories and that an intermediate leak cannot be erased by a later correct answer. Workload planning counts two responses per stage.
- Exact capture/replay tests verify submitted payload equality and canonical fingerprints, refusal to reconstruct missing historical captures, rejection of altered fingerprints and changed local weights, no retrieval during replay, shared execution capacity, separate durable artifacts and source-report preservation. Terminal replay state is published only after persistence.
- Retrieval tests cover BM25 ranking, chunk/overlap validation, no vector initialization or embedding calls in keyword-only local runs, reranking controls, base-setting inheritance and separate campaign/reliability identities. Runtime-view tests allow BM25 without embedding/vector dependencies.
- Ten findings tests exercise revision history, immutable source references, verification compatibility, nonpassing/unsafe verification rejection, local-vs-demo separation, unknown historical identities, metadata bounds and acceptance rationale. Thirteen portable tests cover frozen independent regression references, stale dataset rejection, bounded ZIP structure, path/ratio checks, tampering and actual payload verification. Cross-feature HTTP testing exercises replay, finding creation/fix verification, suite creation and bundle export/verification without changing original reports.
- Browser-created scenario `custom-162f02e2f8cf479191e489239a6e4377` (Staged procurement review) contains two turns, a later approved review record and an unsigned parser-status tool result. Real run `db8d9378e37945ce86bc241b9c5f3be0` used Qwen3.5:4b, seed42, thinking disabled, response768/context8192/timeout60, BM25 chunk900/overlap100 and term-coverage reranking. Four chat calls and zero embedding calls completed without runtime errors; the final two typed fields passed and the simulated tool result was rejected by defense.
- Diagnostic replay `bcf0e1536efe4ca98f906056a215ab8a` repeated the final secured request, verified recorded model digest `d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04`, and produced an unchanged response. The replay remains separate from graded report history.
- Browser checks saved Staged procurement regression with the original conversation and independent references. A two-experiment bundle included that live run and a historical overblocking finding; the verifier checked seven payload files, 41,198 archive bytes and 421,815 expanded bytes, with SHA-256 `b6e50d522862090b668c12ed9fb2bb31c12e299e608d5e8ff6075d104169d47e`. Nothing was extracted or executed by verification. The historical finding retains open/investigating revisions and cannot be certified fixed because its original report lacks grading identity.

Final expansion verification: **274 Python tests and 14 JavaScript tests passed**. All ten browser scripts passed syntax checks; the integrated page has 359 unique element IDs. Repository whitespace checks passed. The new attack-availability regression confirms that an earlier coincidental answer cannot count as a tool attack before its material arrives. After restarting the server, the saved replay, regression suite and experiment history remained available. Browser campaign preview combined three retrieval variants with one frozen two-turn case and one seed: three trial jobs and twelve model responses, without starting inference.
