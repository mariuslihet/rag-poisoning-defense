# Selective async execution

Spades 0.5 defaults to six scenarios, real local inference, and two concurrent scenario workers. Full scenario documents, prompts, context budgets and grading criteria are preserved.

## Choose what runs

Open **New experiment** and select one of these scopes:

| Scope | Behavior |
| --- | --- |
| Small balanced batch | Sample at most the chosen batch size across matching domains and families; default six |
| Choose exact scenarios | Run only checked scenario IDs, regardless of the sample-size input |
| All matching scenarios | Explicit full campaign for the current profile/domain/family filters |
| Untested scenarios | Exclude completed cases from a previous experiment and its compatible continuation batches; sample the next batch |
| Retry runtime errors | Select execution-error cases that have not subsequently completed in the continuation lineage |

The preview shows the exact case count, two model responses per case and the worker bound. Launch stays disabled while the selection is being checked. Changing profile resets the sample size to six. Older saved presets without selection metadata are capped to six when applied in the interface.

Individual case evidence includes **Run only this scenario**. Experiment history includes **Run untested**, which restores the source profile, execution mode, retrieval depth, policy and trust threshold before proposing the next batch. Continuation requires matching evaluation settings and dataset/grading definitions. A completed assessment with incorrect model answers is still a tested case; use exact selection to deliberately re-evaluate it.

## Async behavior

The native async runner uses a bounded queue with 1–4 worker coroutines. Blocking local model and index operations run through `asyncio.to_thread`. Each scenario retains its paired vulnerable/secured execution. Independent scenarios overlap; a single scenario's two arms execute sequentially.

The server accepts one experiment at a time and keeps the interface responsive. Its activity panel reports each active scenario's retrieval, vulnerable-generation, secured-generation or grading phase, plus queued counts. **View completed results** opens checkpointed evidence while other cases are still running.

Stopping prevents further dispatch. Already active cases finish both arms, then the partial result is saved. Cancellation does not forcibly kill Ollama or other applications. Closing the process can interrupt active requests; completed case checkpoints remain readable.

## Durable progress

Before publishing completed progress, the runner atomically replaces its `report.json` with a checkpoint. Final CSV and standalone HTML exports are generated when the run ends. On restart, a checkpoint whose worker no longer exists is shown as interrupted.

Continuation records the source run and covered case IDs. Compatible completed descendants are included in coverage, so returning to the same original partial run does not repeatedly schedule its first continuation batch. Each child report contains its own fresh responses and points to the historical coverage; older model responses are not silently counted as fresh results.

## Embedding reuse

The local cache is SQLite with WAL and explicit connection closure. Keys combine the exact text with the embedding model's digest from Ollama. Changed or unknown model identities cannot silently reuse old entries. Concurrent identical requests reuse the saved vectors. Invalid cached vectors are treated as misses.

The cache stores vectors and hashes, not trusted approvals. Every case creates a fresh provenance registry and repeats authentication, access checks and grading. Chat responses are not cached. The model's existing output limit and context size are unchanged; `keep_alive` retains the loaded chat model for thirty minutes between requests.

The dashboard shares its embedding cache under `output/.cache`. CLI runs reuse the cache within their chosen output directory. Cache files are not exposed by the report API.

## Measured observations

| Measurement | Baseline | Updated path | Scope |
| --- | ---: | ---: | --- |
| Six-case controlled I/O scheduler, two trials | 0.499 / 0.492 s, one worker | 0.252 / 0.256 s, two workers | Synthetic 40 ms delay per model call; identical responses, verdicts and order |
| Twelve enterprise text embeddings, median of three trials | 0.155 s without reuse, model already resident | 0.004 s from the local cache | Same texts and model digest; vectors identical |
| Two selected enterprise cases in the browser | No controlled serial comparator | 45.485 s, four chat requests, zero execution errors | Real Qwen2.5 inference with two workers; includes 21 reused embedding vectors |

The scheduler benchmark does not measure Qwen tokens per second. Embedding reuse reduces preparation work; it does not make generation itself 40 times faster. The initial uncached embedding trial took 1.521 seconds, including approximately 1.214 seconds of model loading, so the table uses the resident-model baseline instead.

Measurements are preserved under `output/performance/async-scheduler-benchmark.json` and `output/performance/embedding-benchmark.json`. The real enterprise run is `0a1863f041ee4c759e56fe2fd83a817d`; original paired responses and timings remain in its report.

Ollama can queue requests depending on its own parallelism setting and available memory; its documented `OLLAMA_NUM_PARALLEL` default is one. Spades' worker setting bounds submitted work and does not change that global service setting. See [Ollama's concurrency documentation](https://docs.ollama.com/faq). No shared Ollama service was restarted or reconfigured for this update.

## CLI examples

```powershell
# Default six-case async batch
.\.venv\Scripts\python.exe -m spades run --profile complex --mode local --concurrency 2

# One exact scenario
.\.venv\Scripts\python.exe -m spades run --profile complex --mode local --case-id enterprise-procurement-1-baseline

# Two exact scenarios
.\.venv\Scripts\python.exe -m spades run --profile complex --mode local --case-id enterprise-procurement-1-baseline --case-id enterprise-privacy-1-baseline --concurrency 2

# Small domain-specific batch
.\.venv\Scripts\python.exe -m spades run --profile complex --domain contracts --limit 3

# Explicitly run the whole matching suite
.\.venv\Scripts\python.exe -m spades run --profile complex --all --concurrency 2
```

Async Python callers can await `spades.evaluation.run_suite_async(...)` directly. Synchronous callers and the CLI use `run_suite(...)`. Both share selection, grading, checkpoint callbacks and bounded scheduling.
