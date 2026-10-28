import asyncio
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from spades.cache import EmbeddingCache
from spades.corpus import build_suite
from spades.evaluation import run_suite, run_suite_async, select_cases
from spades.providers import ChromaIndex, DemoModel, Ollama
from spades.report import write_checkpoint, write_report
from spades.server import RunManager, validate_config


class AsyncExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_async_entry_overlaps_requests_with_a_bound(self):
        lock = threading.Lock()
        active, peak = 0, 0
        original = DemoModel.answer
        def delayed(model, *args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.025)
            try:
                return original(model, *args, **kwargs)
            finally:
                with lock:
                    active -= 1
        with patch.object(DemoModel, "answer", delayed):
            report = await run_suite_async(limit=6, concurrency=2)
        self.assertEqual(peak, 2)
        self.assertEqual(report["metrics"]["completed_cases"], 6)
        self.assertEqual(report["configuration"]["concurrency"], 2)

    async def test_parallel_results_preserve_sequential_assessments_and_order(self):
        serial = await run_suite_async(limit=6, concurrency=1, policy="sanitize")
        parallel = await run_suite_async(limit=6, concurrency=3, policy="sanitize")
        def evidence(report):
            return [(r["case_id"], r["vulnerable_response"], r["secured_response"], r["secured_success"],
                     r["secured_utility"], [(d["allowed"], d["reason"]) for d in r["decisions"]]) for r in report["results"]]
        self.assertEqual(evidence(serial), evidence(parallel))

    async def test_cancellation_finishes_only_in_flight_cases(self):
        lock, entered, release, cancel = threading.Lock(), threading.Event(), threading.Event(), threading.Event()
        first_calls = 0
        original = DemoModel.answer
        def blocked(model, *args, **kwargs):
            nonlocal first_calls
            with lock:
                first_calls += 1
                if first_calls >= 2:
                    entered.set()
            release.wait(3)
            return original(model, *args, **kwargs)
        with patch.object(DemoModel, "answer", blocked):
            task = asyncio.create_task(run_suite_async(limit=6, concurrency=2, cancelled=cancel.is_set))
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            cancel.set()
            release.set()
            report = await task
        self.assertEqual(report["status"], "cancelled")
        self.assertEqual(report["metrics"]["total_cases"], 2)
        self.assertEqual(report["planned_cases"], 6)

    async def test_checkpoints_are_atomic_and_include_each_completed_case(self):
        saved = []
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            def checkpoint(report):
                write_checkpoint(report, folder)
                saved.append(json.loads((folder / "report.json").read_text(encoding="utf-8")))
            report = await run_suite_async(limit=4, concurrency=2, checkpoint=checkpoint)
        self.assertEqual([len(r["results"]) for r in saved], [0, 1, 2, 3, 4, 4])
        self.assertEqual(saved[-1]["status"], "completed")
        self.assertEqual(report["metrics"]["completed_cases"], 4)

    async def test_failed_case_does_not_abort_other_cases(self):
        original = DemoModel.answer
        def failure(model, query, *args, **kwargs):
            if "annual leave" in query:
                raise AttributeError("Synthetic provider failure")
            return original(model, query, *args, **kwargs)
        with patch.object(DemoModel, "answer", failure):
            report = await run_suite_async(case_ids=["hr-baseline-concise", "api-baseline-concise"], concurrency=2)
        self.assertEqual(report["metrics"]["error_cases"], 1)
        self.assertEqual(report["metrics"]["completed_cases"], 1)


class EmbeddingReuseTests(unittest.TestCase):
    def provider(self, path, digest="weights-a"):
        provider = Ollama(cache_path=path)
        provider._fingerprint = MagicMock(return_value=digest)
        provider._embedding_digest = digest
        provider.request = MagicMock(side_effect=lambda endpoint, body: {"embeddings": [[float(len(t)), 0.25] for t in body["input"]]})
        return provider

    def test_vectors_reuse_across_provider_instances_and_preserve_order(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.sqlite3"
            first = self.provider(path)
            original = first.embed(["alpha", "beta"])
            second = self.provider(path)
            self.assertEqual(second.embed(["beta", "alpha"]), list(reversed(original)))
            second.request.assert_not_called()
            self.assertEqual(second.statistics()["embedding_cache_hits"], 2)

    def test_changed_model_digest_is_not_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.sqlite3"
            self.provider(path, "weights-a").embed(["same text"])
            changed = self.provider(path, "weights-b")
            changed.embed(["same text"])
            self.assertEqual(changed.request.call_count, 1)

    def test_unknown_digest_disables_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            provider = self.provider(Path(folder) / "cache.sqlite3", None)
            provider.embed(["same"])
            provider.embed(["same"])
            self.assertEqual(provider.request.call_count, 2)
            self.assertFalse(provider.statistics()["embedding_cache_enabled"])

    def test_concurrent_identical_embedding_requests_are_coalesced(self):
        with tempfile.TemporaryDirectory() as folder:
            provider = self.provider(Path(folder) / "cache.sqlite3")
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: provider.embed(["shared input"]), range(2)))
            self.assertEqual(results[0], results[1])
            self.assertEqual(provider.request.call_count, 1)

    def test_invalid_vectors_are_not_cached(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = EmbeddingCache(Path(folder) / "cache.sqlite3")
            for value in ([], [float("nan")], [True], ["invalid"]):
                with self.assertRaises(ValueError):
                    cache.put_many("digest", ["text"], [value])

    def test_chroma_runtime_initialization_is_serialized(self):
        lock, active, peak = threading.Lock(), 0, 0
        client = MagicMock()
        def factory(**kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return client
        fake = SimpleNamespace(PersistentClient=factory, Settings=MagicMock())
        with patch.dict("sys.modules", {"chromadb": fake}):
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda n: ChromaIndex([], MagicMock(), Path("unused"), f"case-{n}"), range(2)))
        self.assertEqual(peak, 1)


class SelectionAndRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.manager = RunManager(Path(self.directory.name))

    def tearDown(self):
        self.directory.cleanup()

    def store(self, report, label):
        write_report(report, self.manager.output / label)

    def test_defaults_are_six_cases_and_two_workers(self):
        config, cases, _ = self.manager.resolve_selection({})
        self.assertEqual(config["limit"], 6)
        self.assertEqual(config["concurrency"], 2)
        self.assertEqual(len(cases), 6)
        self.assertEqual(run_suite()["planned_cases"], 6)

    def test_all_scenarios_requires_explicit_scope(self):
        _, cases, _ = self.manager.resolve_selection({"profile": "complex", "selection_scope": "all"})
        self.assertEqual(len(cases), 96)

    def test_exact_selection_is_not_reduced_to_the_sample_limit(self):
        ids = [c.case_id for c in build_suite()[:8]]
        _, cases, _ = self.manager.resolve_selection({"selection_scope": "selected", "case_ids": ids, "limit": 1})
        self.assertEqual([c.case_id for c in cases], ids)

    def test_domain_filter_and_invalid_ids(self):
        cases = select_cases(profile="complex", domain="privacy", limit=3)
        self.assertEqual(len(cases), 3)
        self.assertTrue(all(c.domain == "privacy" for c in cases))
        for ids in ([], ["unknown"], ["hr-baseline-concise"] * 2):
            with self.assertRaises(ValueError):
                select_cases(case_ids=ids)

    def test_repeated_continuations_never_retest_covered_ids(self):
        first = run_suite(limit=2)
        self.store(first, "first")
        config = {"selection_scope": "remaining", "source_run_id": first["run_id"], "limit": 2}
        _, second_cases, covered = self.manager.resolve_selection(config)
        first_ids = {r["case_id"] for r in first["results"]}
        self.assertFalse(first_ids & {c.case_id for c in second_cases})
        second = run_suite(case_ids=[c.case_id for c in second_cases], previous_case_ids=covered)
        self.store(second, "second")
        _, third_cases, covered = self.manager.resolve_selection({**config, "source_run_id": second["run_id"]})
        self.assertEqual(len(covered), 4)
        self.assertFalse(set(covered) & {c.case_id for c in third_cases})

    def test_retry_errors_selects_only_incomplete_runtime_results(self):
        report = run_suite(limit=3)
        report["results"][1]["error"] = "Synthetic connection error"
        self.store(report, "failed")
        _, cases, _ = self.manager.resolve_selection({"selection_scope": "errors", "source_run_id": report["run_id"]})
        self.assertEqual([c.case_id for c in cases], [report["results"][1]["case_id"]])

    def test_reopening_original_run_also_skips_its_completed_children(self):
        first = run_suite(limit=2)
        self.store(first, "root")
        config = {"selection_scope": "remaining", "source_run_id": first["run_id"], "limit": 2}
        _, second_cases, previous = self.manager.resolve_selection(config)
        second = run_suite(case_ids=[c.case_id for c in second_cases], previous_case_ids=previous,
                           selection_scope="remaining", source_run_id=first["run_id"])
        self.store(second, "child")
        _, third_cases, previous = self.manager.resolve_selection(config)
        self.assertEqual(len(previous), 4)
        self.assertFalse(set(previous) & {c.case_id for c in third_cases})

    def test_continuation_rejects_incompatible_policy(self):
        report = run_suite(limit=2)
        self.store(report, "source")
        with self.assertRaises(ValueError):
            self.manager.resolve_selection({"selection_scope": "remaining", "source_run_id": report["run_id"], "policy": "sanitize"})

    def test_interrupted_checkpoint_is_readable_and_recoverable(self):
        report = run_suite(limit=2)
        report["status"] = "running"
        report["planned_cases"] = 6
        write_checkpoint(report, self.manager.output / "interrupted")
        recovered = RunManager(self.manager.output)
        self.assertEqual(recovered.history()[0]["status"], "interrupted")
        _, cases, _ = recovered.resolve_selection({"selection_scope": "remaining", "source_run_id": report["run_id"]})
        self.assertEqual(len(cases), 6)
        self.assertFalse({c.case_id for c in cases} & {r["case_id"] for r in report["results"]})

    def test_bad_worker_counts_and_missing_selection_are_rejected(self):
        for concurrency in (0, 5, True, "2"):
            with self.assertRaises(ValueError):
                validate_config({"concurrency": concurrency})
        with self.assertRaises(ValueError):
            validate_config({"selection_scope": "selected"})
        with self.assertRaises(ValueError):
            validate_config({"selection_scope": "remaining"})


if __name__ == "__main__":
    unittest.main()
