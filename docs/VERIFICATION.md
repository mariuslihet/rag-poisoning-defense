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
