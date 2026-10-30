# Campaigns and repeated-trial reliability

A campaign captures a fixed selection of scenario IDs and a matrix of generation model names, strict/sanitize defense policies, and explicit integer seeds. Creating a campaign is the explicit action that starts scheduling; opening the campaign page, inspecting saved evidence, or restarting the server does not start inference.

Campaigns support 1–10 unique model names, 1–2 unique defense policies, 1–20 unique seeds, and at most 100 original trial jobs. Each job is a full paired evaluation of the frozen selection. Trial jobs run sequentially; each job retains the ordinary bounded concurrent-scenario setting from its base experiment configuration. Model availability is checked by the ordinary runner, and an unavailable model fails its job without abandoning later jobs.

The full base configuration, exact source definitions when applicable, and scenario IDs are stored once under `output/campaigns/<campaign_id>.json`. Each job stores only its model, policy and generation overrides, avoiding repeated copies of source text. Source fixtures and previous report files are not modified.

## Queue and cancellation

- A campaign waits while the ordinary run manager is busy. Cancelling a waiting campaign never stops an unrelated manual run.
- Cancel an individual queued job to exclude that trial before it starts. Cancelling a starting/running job requests the runner's ordinary stop-after-in-flight behavior; active model calls may need to finish or time out.
- Cancel a campaign to cancel queued jobs and request a stop only for its own active run.
- After a process restart, previously active campaigns are marked interrupted. Queued jobs remain available for explicit **Resume queued trials**. Interrupted trials keep their saved run IDs/checkpoints and are not silently rerun.
- **Retry as new attempt** is explicit and creates another saved attempt of the same logical trial. Earlier attempts remain visible. Only the newest attempt can be retried, and a completed logical trial is not automatically duplicated.

Campaigns retain at most 300 attempts including retries and up to 200 campaign records. These bounds do not authorize automatically running the full built-in corpus; the selection follows the current experiment scope or explicitly chosen suite.

## Reliability semantics

Reliability groups trials by declared model, defense policy, profile, trust threshold, retrieval depth, exact case IDs and generation settings excluding the intentionally varied seed. A trial is successful only if every frozen scenario has a successful secured-task assessment and no runtime error.

Only the latest explicit attempt of each logical trial enters its denominator. Cancelled, partial, interrupted, missing-report, mismatched-identity and runtime-error trials are excluded and listed with reasons. Superseded attempts remain evidence, but they are not additional statistically independent trials.

The report contains the all-cases task success frequency and descriptive 95% Wilson score interval, plus per-scenario task pass/failure frequencies and attack-match frequencies. Legitimate controls have no attack-rate denominator. A zero-observation denominator is N/A. Recorded model-weight changes within a configuration are flagged as mixed identity.

Wilson intervals describe the observed outcome counts. Changing seeds alone does not establish independent samples, generalization to other scenarios, or a causal effect of a model/defense setting. Demonstration-mode repetition measures the deterministic simulator, not an LLM. No timing speedup is inferred from campaign totals.

## Local endpoints

- `GET /api/campaigns`: compact saved campaign queue.
- `GET /api/campaign/<id>`: full frozen campaign, job attempts and derived reliability.
- `POST /api/campaign/create`: `{name, base_config, models, policies, seeds}`.
- `POST /api/campaign/action`: `{id, action, job_id?}`, where action is `cancel`, `resume`, `cancel_job`, or `retry_job`.

All mutations use the dashboard's existing loopback, same-origin and session-token protections. Exported campaign evidence can contain frozen custom source definitions and grading references; review it before sharing it outside the local laboratory.


## Parameter sweeps and authoritative previews

Optional create/preview fields `thresholds`, `retrieval_depths` and `temperatures` accept 1–10 unique bounded values. Omitted axes inherit validated base settings. The Cartesian product, including model/policy/seed dimensions, must contain at most 100 jobs. Each job stores full generation settings and its own threshold/depth; immutable base selection and authored definitions remain shared. Legacy campaigns without per-job threshold/depth retain their original base settings.

POST `/api/campaign/preview` uses the same validation and expansion as creation, but never persists a campaign or starts its scheduler. Its response includes axes, full trial configurations, workload counts, the scenario plan and a frozen base configuration. The UI uses that exact frozen scope when starting from the preview. Preview does not check local model readiness; each real trial checks readiness before execution. API callers that submit an unresolved dynamic selection directly to create will resolve it at creation time.

The configuration table reports groups separately for threshold, depth and temperature. Rates summarize complete measured trials only; inspect exclusions, weight changes and descriptive intervals. Demo generation parameters are recorded but not applied. No automatically selected winning configuration or significance claim is produced.
