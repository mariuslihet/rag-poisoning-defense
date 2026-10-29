from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from spades.cli import main
from spades.evaluation import run_suite
from spades.providers import DemoModel, MemoryIndex, Ollama
from spades.report import write_report
from spades.server import RunManager, validate_config
from spades.settings import DEFAULT_MODEL, validate_generation, validate_model


class ModelSettingsTests(unittest.TestCase):
    def setUp(self):
        self.options = {"temperature": 0.25, "seed": 42, "think": None, "num_predict": 512, "num_ctx": 8192, "request_timeout": 45}

    def test_profile_defaults_preserve_previous_runtime_limits(self):
        self.assertEqual(validate_generation()["num_predict"], 350)
        self.assertEqual(validate_generation(profile="complex")["num_ctx"], 16384)
        self.assertEqual(validate_generation(profile="complex")["num_predict"], 1400)
        self.assertIsNone(validate_generation()["seed"])
        self.assertEqual(validate_generation()["request_timeout"], 180)

    def test_settings_reject_unknown_nonfinite_boolean_and_out_of_range_values(self):
        for options in ({"temperature": float("nan")}, {"temperature": True}, {"temperature": 3},
                        {"seed": True}, {"seed": -1}, {"seed": 2147483648}, {"request_timeout": 0},
                        {"request_timeout": 601}, {"num_ctx": 1024}, {"num_predict": 0},
                        {"num_predict": 8192, "num_ctx": 8192}, {"num_ctx": 65536}, {"raw_prompt": "override"}, []):
            with self.assertRaises(ValueError):
                validate_generation(options)

    def test_model_identifier_is_a_bounded_local_name(self):
        self.assertEqual(validate_model("qwen3.5:4b"), "qwen3.5:4b")
        for model in ("https://example.com/model", "model\ncommand", "", "x" * 201, True):
            with self.assertRaises(ValueError):
                validate_model(model)

    def test_provider_sends_exact_settings_to_chat_but_not_timeout_as_model_option(self):
        provider = Ollama(model="qwen3.5:4b", generation=self.options)
        with patch.object(provider, "request", return_value={"message": {"content": "READY"}}) as request:
            self.assertEqual(provider.answer("Reply READY", [], True), "READY")
        payload = request.call_args.args[1]
        self.assertEqual(payload["model"], "qwen3.5:4b")
        self.assertEqual(payload["options"], {key:value for key,value in self.options.items() if key not in ("request_timeout", "think")})
        self.assertEqual(self.options["request_timeout"], 45)

    def test_request_timeout_is_applied_to_local_http_calls(self):
        provider = Ollama(generation={"request_timeout": 35})
        provider._model_registry = [{"name":DEFAULT_MODEL,"size":100}]
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = '{"message":{"content":"READY"}}'
        with patch("spades.providers.urllib.request.build_opener", return_value=opener):
            provider.request("/api/chat", {"model": DEFAULT_MODEL})
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 35)

    def test_remote_aliases_and_unverifiable_weights_are_rejected_before_prompt_transmission(self):
        for metadata in ({"remote_host":"https://upstream.invalid","size":100}, {"remote_model":"other","size":100}, {"size":0}):
            provider = Ollama()
            opener = MagicMock()
            opener.open.return_value.__enter__.return_value.read.return_value = json.dumps({"models":[{"name":DEFAULT_MODEL, **metadata}]})
            with patch("spades.providers.urllib.request.build_opener", return_value=opener):
                with self.assertRaisesRegex(ValueError, "local weights"):
                    provider.request("/api/chat", {"model":DEFAULT_MODEL,"messages":[{"role":"user","content":"Synthetic private test"}]})
            self.assertEqual(opener.open.call_count, 1)
            self.assertEqual(opener.open.call_args.args[0], Ollama.base_url + "/api/tags")

    def test_selected_weight_digest_is_in_provider_statistics(self):
        provider = Ollama()
        provider._model_registry = [{"name":DEFAULT_MODEL,"size":100,"digest":"weights-123"}]
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = '{"message":{"content":"READY"}}'
        with patch("spades.providers.urllib.request.build_opener", return_value=opener):
            provider.request("/api/chat", {"model":DEFAULT_MODEL})
        self.assertEqual(provider.statistics()["model_digest"], "weights-123")

    def test_thinking_mode_is_sent_at_top_level_and_recorded_completion_is_explicit(self):
        provider = Ollama(generation={"think":False})
        with patch.object(provider,"request",return_value={"message":{"content":"","thinking":"synthetic"},"done_reason":"length","eval_count":128,"prompt_eval_count":50}) as request:
            provider.answer("Question",[],True)
        self.assertIs(request.call_args.args[1]["think"],False)
        self.assertNotIn("think",request.call_args.args[1]["options"])
        self.assertEqual(provider.response_metadata(),{"done_reason":"length","generated_tokens":128,"prompt_tokens":50,"empty_response":True,"thinking_characters":9})

    def test_completion_metadata_does_not_mix_parallel_case_threads(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        provider = Ollama()
        barrier = threading.Barrier(2)
        def response(endpoint,payload):
            marker = payload["messages"][-1]["content"].split("Question: ")[-1]
            return {"message":{"content":marker},"done_reason":marker,"eval_count":int(marker)}
        def evaluate(marker):
            provider.answer(marker,[],True)
            barrier.wait(timeout=2)
            return provider.response_metadata()
        with patch.object(provider,"request",side_effect=response), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(evaluate,["1","2"]))
        self.assertEqual([result["generated_tokens"] for result in results],[1,2])

    def test_default_provider_does_not_invent_a_seed_and_keeps_enterprise_defaults(self):
        provider = Ollama()
        with patch.object(provider, "request", return_value={"message": {"content": "{}"}}) as request:
            provider.answer("Question", [], True, schema={"type": "object"})
        options = request.call_args.args[1]["options"]
        self.assertNotIn("seed", options)
        self.assertEqual((options["num_predict"], options["num_ctx"]), (1400, 16384))

    def test_runner_passes_settings_and_records_the_selected_model(self):
        provider = DemoModel()
        provider.model = "qwen3.5:4b"
        with tempfile.TemporaryDirectory() as folder, patch("spades.evaluation.Ollama", return_value=provider) as factory, patch("spades.evaluation.ChromaIndex", side_effect=lambda chunks,*args: MemoryIndex(chunks)):
            report = run_suite(mode="local", output=Path(folder), model=provider.model, generation=self.options, limit=1)
        self.assertEqual(factory.call_args.kwargs["generation"], self.options)
        self.assertEqual(report["configuration"]["generation"], self.options)
        self.assertTrue(report["configuration"]["generation_applied"])
        self.assertEqual(report["model"], provider.model)
        self.assertEqual(report["metrics"]["error_cases"], 0)

    def test_local_continuations_require_same_model_and_generation_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = RunManager(Path(folder))
            report = run_suite(limit=1)
            report.update(mode="local", model="qwen3.5:4b")
            report["configuration"]["generation"] = self.options
            write_report(report, Path(folder) / "source")
            config = {"mode":"local", "model":"qwen3.5:4b", "generation":self.options,
                      "selection_scope":"remaining", "source_run_id":report["run_id"]}
            _, cases, previous = manager.resolve_selection(config)
            self.assertEqual(len(cases), 6)
            self.assertEqual(previous, [report["results"][0]["case_id"]])
            for change in ({"model":DEFAULT_MODEL}, {"generation":{**self.options,"seed":43}}):
                with self.assertRaisesRegex(ValueError, "generation settings"):
                    manager.resolve_selection({**config,**change})

    def test_presets_preserve_settings_and_demo_marks_them_unapplied(self):
        config = validate_config({"model":"qwen3.5:4b", "generation":self.options})
        with tempfile.TemporaryDirectory() as folder:
            manager = RunManager(Path(folder))
            manager.save_preset({"name":"Seeded model", "config":config})
            self.assertEqual(RunManager(Path(folder)).workspace()["presets"][-1]["config"]["generation"], self.options)
        report = run_suite(limit=1, generation=self.options)
        self.assertFalse(report["configuration"]["generation_applied"])
        self.assertEqual(report["configuration"]["generation"], self.options)

    def test_cli_generation_controls_reach_the_saved_report(self):
        with tempfile.TemporaryDirectory() as folder:
            argv = ["spades", "run", "--mode", "demo", "--profile", "foundation", "--limit", "1", "--output", folder,
                    "--seed", "42", "--temperature", "0.25", "--max-tokens", "512", "--context-window", "8192", "--request-timeout", "45"]
            with patch("sys.argv", argv), redirect_stdout(io.StringIO()):
                main()
            report = json.loads((Path(folder)/"report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["configuration"]["generation"], self.options)
