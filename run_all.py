"""Run the whole pipeline: python run_all.py

1. clean        event log -> one row per incident + star-schema CSVs (downloads raw data if missing)
2. analyze      every number used in the docs -> data/clean/metrics.json, doc charts
3. excel        reports/service_desk_monthly_report.xlsx (live formulas, checked against pandas)
4. docs         README, data notes, RCA and runbook re-rendered from metrics.json
5. powerbi      regenerate the PBIP, validate it against Microsoft's schemas, and - if Power BI
                Desktop has it open - refresh the model and test every visual's query
"""
import subprocess
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
STEPS = [
    ("clean", ["clean.py"]),
    ("analyze", ["analyze.py"]),
    ("excel", ["build_excel.py"]),
    ("docs", ["render_docs.py"]),
    ("powerbi", ["build_pbip.py", "validate_pbir.py", "check_powerbi.py"]),
]


def main():
    t0 = time.time()
    for name, scripts in STEPS:
        for s in scripts:
            print(f"\n== {name}: {s}")
            r = subprocess.run([sys.executable, s], cwd=SRC)
            if r.returncode != 0:
                sys.exit(f"Step '{name}' failed in {s}")
    print(f"\nDone in {time.time() - t0:.0f}s.")


if __name__ == "__main__":
    main()
