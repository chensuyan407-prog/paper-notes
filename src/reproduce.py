#!/usr/bin/env python3
"""Reproduce the bundle's recorded results.

1. tests/run_tests.py  - synthetic two-column paper + adversarial note perturbations, encrypted and scanned inputs.
2. outline check       - optional: for any real PDFs given with --pdfs (e.g. arXiv 1502.03167, 1405 GloVe), print the
                         outline before (parser) and after (paper-notes repair) so the heading fixes can be inspected.
Writes execution/results/metrics.json and execution/run.log.
"""
import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "submission", "scripts"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdfs", nargs="*", default=[])
    a = ap.parse_args()
    out = os.path.join(ROOT, "execution", "results")
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "run_tests.py")], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith(("PASS", "FAIL"))]
    metrics = {"self_test": {"passed": sum(ln.startswith("PASS") for ln in lines), "total": len(lines),
                             "exit_code": r.returncode, "lines": lines}}
    if a.pdfs:
        import parse_pdf
        import notes_lib as L
        metrics["outline_repair"] = []
        for p in a.pdfs:
            d = os.path.join(out, "outline_check", os.path.splitext(os.path.basename(p))[0])
            parse_pdf.parse(p, d, preview=False)
            raw = json.load(open(os.path.join(d, "doc.json"), encoding="utf-8"))["sections"]
            D = L.Doc(d)
            metrics["outline_repair"].append({
                "pdf": os.path.basename(p),
                "parser_outline": [f"{s.get('number') or ''} {s['title']}".strip() for s in raw],
                "repaired_outline": [f"{s.get('number') or ''} {s['title']}".strip() for s in D.sections],
                "fixes": D.outline_fixes})
    metrics["seconds"] = round(time.time() - t0, 2)
    with open(os.path.join(out, "metrics.json"), "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(ROOT, "execution", "run.log"), "w", encoding="utf-8") as fh:
        fh.write(r.stdout + "\n" + r.stderr)
    print(f"self-test {metrics['self_test']['passed']}/{metrics['self_test']['total']} (exit {r.returncode}); "
          f"metrics -> {os.path.join(out, 'metrics.json')}")
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
