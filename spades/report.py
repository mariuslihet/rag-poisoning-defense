"""Self-contained, offline HTML report. All untrusted strings are escaped."""

import html
import csv
import io
import json
from pathlib import Path


def report_csv(report):
    """Export evidence while neutralizing spreadsheet formula prefixes."""
    output = io.StringIO(newline="")
    fields = ["case_id", "category", "query", "expected", "target", "vulnerable_response", "secured_response",
              "vulnerable_success", "secured_success", "vulnerable_utility", "secured_utility", "poison_rank",
              "duration_seconds", "error", "profile", "domain", "document_count", "indexed_chunks",
              "vulnerable_grade", "secured_grade"]
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(fields)
    for row in report["results"]:
        values = []
        for field in fields:
            value = row.get(field)
            text = "" if value is None else json.dumps(value) if isinstance(value, (dict, list)) else str(value)
            if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
                text = "'" + text
            values.append(text)
        writer.writerow(values)
    return output.getvalue()


def write_checkpoint(report, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / "report.json.tmp"
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(output / "report.json")


def write_report(report, output: Path):
    write_checkpoint(report, output)
    (output / "report.csv").write_text(report_csv(report), encoding="utf-8-sig")
    esc = lambda value: html.escape(str(value))
    metrics = report["metrics"]
    cards = ""
    keys = ("secured_field_score", "secured_task_success", "secured_citation_coverage", "required_source_recall", "secured_asr") if report.get("configuration", {}).get("profile") == "complex" else ("vulnerable_asr", "secured_asr", "mitigation_rate", "false_positive_rate", "secured_task_success")
    for key in keys:
        value = metrics[key]
        cards += f'<article><span>{esc(key.replace("_", " ").title())}</span><strong>{"N/A" if value is None else f"{value:.1%}"}</strong></article>'
    rows = ""
    for row in report["results"]:
        if row["error"]:
            detail = f'<p class="error">{esc(row["error"])}</p>'
        else:
            detail = f'<div class="answers"><section><h4>Vulnerable response</h4><pre>{esc(row["vulnerable_response"])}</pre></section><section><h4>Secured response</h4><pre>{esc(row["secured_response"])}</pre></section></div>'
            detail += '<ul>' + ''.join(f'<li>{esc(d["chunk_id"])} · {"ALLOW" if d["allowed"] else "BLOCK"} · {esc(d["reason"])} · trust {d["trust"]}</li>' for d in row["decisions"]) + '</ul>'
            for arm in ("vulnerable", "secured"):
                grade = row.get(f"{arm}_grade")
                if grade:
                    detail += f'<h4>{esc(arm.title())} field assertions</h4><table><tr><th>Field</th><th>Reference</th><th>Observed</th><th>Result</th></tr>'
                    detail += ''.join(f'<tr><td>{esc(c["field"])}</td><td>{esc(json.dumps(c["expected"]))}</td><td>{esc(json.dumps(c["actual"]))}</td><td>{"Pass" if c["passed"] else "Fail"}</td></tr>' for c in grade["checks"])
                    detail += f'</table><p>Missing citations: {esc(", ".join(grade["missing_citations"]) or "None")}</p>'
        status = "ERROR" if row["error"] else ("ATTACK SUCCEEDED" if row["secured_success"] else ("TASK PASSED" if row["secured_utility"] else "REVIEW UTILITY"))
        rows += f'<details><summary><span>{esc(row["case_id"])}</span><b>{status}</b></summary><p>{esc(row["query"])}</p>{detail}</details>'
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Spades — Security Laboratory</title><style>
    :root{color-scheme:light;font-family:Segoe UI,system-ui,sans-serif;background:#f3f6fa;color:#18283d}*{box-sizing:border-box}body{margin:0}main{max-width:1320px;margin:auto;padding:40px 32px}nav{display:flex;justify-content:space-between;color:#53667d;border-bottom:1px solid #d9e2ec;padding-bottom:24px}.brand{color:#17365d;font-size:24px;font-weight:750;letter-spacing:3px}.brand i{color:#2859b8;font-style:normal}header{margin:55px 0 30px}.eyebrow{color:#2859b8;letter-spacing:2px;font-size:12px}h1{font-size:clamp(32px,5vw,60px);letter-spacing:-2px;margin:14px 0}p{color:#53667d;line-height:1.7}.notice{border:1px solid #bbccdf;background:#edf3fd;padding:18px 22px;border-radius:10px;color:#345477}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:28px 0 45px}article{background:#ffffff;border:1px solid #d9e2ec;border-radius:12px;padding:24px}article span{color:#53667d;font-size:13px}strong{display:block;font-size:36px;margin-top:12px;font-weight:600}h2{font-size:22px}details{border:1px solid #d9e2ec;background:#ffffff;border-radius:8px;margin:10px 0;padding:16px 20px}summary{cursor:pointer;display:flex;justify-content:space-between;gap:12px;font-size:14px}summary b{font-size:10px;letter-spacing:1px;color:#2859b8;white-space:nowrap}.answers{display:grid;grid-template-columns:1fr 1fr;gap:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6fa;padding:16px;border-radius:6px;line-height:1.7;color:#2a435e}h4{font-weight:500;color:#526b87}li{font-size:13px;color:#526b87;margin:9px 0;overflow-wrap:anywhere}footer{margin-top:40px;border-top:1px solid #d9e2ec;padding-top:20px;color:#53667d;font-size:12px}.error{color:#a12c42}@media(max-width:650px){main{padding:24px 16px}.answers{grid-template-columns:1fr}summary{flex-wrap:wrap}}
    table{border-collapse:collapse;width:100%;font-size:12px}td,th{padding:10px;text-align:left;border-bottom:1px solid #d9e2ec}</style><main><nav><div class="brand">SPADES</div><span>LOCAL SECURITY LABORATORY / 0.4</span></nav>'''
    page += f'<header><div class="eyebrow">RETRIEVAL INTEGRITY / PAIRED EVALUATION</div><h1>Evaluation evidence.</h1><p>Challenge poisoned context. Inspect every defense decision.</p></header><div class="notice">{esc(report["mode"].upper())} · {esc(report["model"])} · {esc(report["retrieval"])}<br>{"Demonstration results are simulated and do not measure Qwen or any real LLM." if report["mode"] == "demo" else "Measured local inference. Review errors and grading limits before interpreting results."}</div>'
    page += f'<div class="cards">{cards}</div><h2>Experiment ledger</h2><p>{metrics["completed_cases"]} / {metrics["total_cases"]} completed · {metrics["error_cases"]} errors · Expand a case to inspect responses and provenance decisions.</p>{rows}<h2>Measurement limits</h2><ul>'
    page += ''.join(f'<li>{esc(limit)}</li>' for limit in report["limitations"])
    page += f'</ul><footer>SPADES · {esc(report["created_at"])} · Run {esc(report["run_id"])} · All fixtures contain synthetic data.</footer></main></html>'
    (output / "index.html").write_text(page, encoding="utf-8")
