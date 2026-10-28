"""English-only command line interface."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .corpus import build_suite
from .evaluation import run_suite, select_cases
from .report import write_report, write_checkpoint


def main():
    parser = argparse.ArgumentParser(description="Spades — Local retrieval security laboratory")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check installed local model/runtime components")
    sub.add_parser("prepare-models", help="Download the required public Ollama models")
    run = sub.add_parser("run", help="Run paired vulnerable and secured experiments")
    run.add_argument("--mode", choices=["demo", "local"], default="local")
    run.add_argument("--threshold", type=float, default=0.7)
    run.add_argument("--k", type=int, default=20)
    run.add_argument("--profile", choices=["foundation", "complex"], default="complex")
    run.add_argument("--model", default="qwen2.5:7b-instruct-q4_K_M")
    run.add_argument("--output", type=Path, default=Path("output"))
    run.add_argument("--limit", type=int, default=6, help="Maximum sampled cases (default: 6)")
    selection = run.add_mutually_exclusive_group()
    selection.add_argument("--all", action="store_true", help="Explicitly run all matching scenarios")
    selection.add_argument("--case-id", action="append", help="Run only these scenario IDs; repeat for multiple cases")
    run.add_argument("--domain", help="Restrict scenarios to one business domain")
    run.add_argument("--concurrency", type=int, choices=range(1, 5), default=2, help="Maximum concurrent scenarios (default: 2)")
    run.add_argument("--category", help="Run one scenario category")
    run.add_argument("--policy", choices=["strict", "sanitize"], default="strict")
    corpus = sub.add_parser("corpus", help="Export generated synthetic documents and query suite")
    corpus.add_argument("--output", type=Path, default=Path("output/corpus.json"))
    corpus.add_argument("--profile", choices=["foundation", "complex"], default="complex")
    serve = sub.add_parser("serve", help="View an existing report on loopback")
    serve.add_argument("--output", type=Path, default=Path("output"))
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.command == "doctor":
        from .runtime import doctor
        print(json.dumps(doctor(), indent=2))
    elif args.command == "prepare-models":
        from .runtime import prepare_models
        prepare_models()
    elif args.command == "run":
        if not 0 <= args.threshold <= 1:
            parser.error("Threshold must be between 0 and 1")
        if not 1 <= args.k <= 50:
            parser.error("Retrieval depth must be between 1 and 50")
        limit = None if args.all or args.case_id else args.limit
        try:
            chosen = select_cases(args.category, limit, args.profile, args.domain, args.case_id)
        except ValueError as exc:
            parser.error(str(exc))
        print(f"Selected {len(chosen)} scenarios / {len(chosen) * 2} model responses / {args.concurrency} concurrent workers", flush=True)
        if args.mode == "local":
            from .providers import Ollama
            try:
                import chromadb  # noqa: F401
                provider = Ollama(model=args.model)
                provider.embed(["Spades readiness check"])
                provider.answer("Reply with READY.", [], True)
            except (ImportError, OSError, ValueError, KeyError) as exc:
                parser.exit(2, f"Local mode unavailable: {exc}\nInstall the local extra and start Ollama with both required models.\n")
        report = run_suite(args.mode, args.threshold, args.k, args.output, args.model,
                           category=args.category, limit=limit, domain=args.domain, case_ids=args.case_id,
                           policy=args.policy, profile=args.profile,
                           concurrency=args.concurrency,
                           selection_scope="all" if args.all else "selected" if args.case_id else "sample",
                           checkpoint=lambda report: write_checkpoint(report, args.output),
                           progress=lambda done, total, case: print(f"[{done}/{total}] {case}", flush=True))
        write_report(report, args.output)
        print(json.dumps(report["metrics"], indent=2))
        print(f"Report: {(args.output / 'index.html').resolve()}")
        if report["metrics"]["error_cases"]:
            raise SystemExit(1)
    elif args.command == "corpus":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps([asdict(c) for c in build_suite(args.profile)], indent=2), encoding="utf-8")
        print(f"Corpus: {args.output.resolve()}")
    else:
        from .server import serve
        serve(args.output, args.port)


if __name__ == "__main__":
    main()
