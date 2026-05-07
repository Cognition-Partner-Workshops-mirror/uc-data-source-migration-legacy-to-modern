"""
Orchestrator script: runs the full ingestion pipeline in dependency order.

Execution order (respects FK dependencies):
  1. borrowers        (no dependencies)
  2. loan_products    (no dependencies)
  3. loan_accounts    (depends on borrowers, loan_products)
  4. payments         (depends on loan_accounts)

Usage (Databricks notebook or spark-submit):
    spark-submit run_pipeline.py
"""

import importlib
import sys
import time

PIPELINE_STEPS = [
    ("borrowers", "ingest_borrowers"),
    ("loan_products", "ingest_loan_products"),
    ("loan_accounts", "ingest_loan_accounts"),
    ("payments", "ingest_payments"),
]

_LOG_TAG = "[run_pipeline]"


def _log(msg: str) -> None:
    print(f"{_LOG_TAG} {msg}")


def main() -> None:
    _log("=" * 60)
    _log("Starting CDW legacy-to-modern ingestion pipeline")
    _log("=" * 60)

    failed_steps: list[str] = []

    for label, module_name in PIPELINE_STEPS:
        _log(f"--- Step: {label} ({module_name}) ---")
        t0 = time.time()
        try:
            mod = importlib.import_module(module_name)
            mod.main()
            elapsed = time.time() - t0
            _log(f"Step '{label}' completed in {elapsed:.1f}s")
        except Exception as exc:
            elapsed = time.time() - t0
            _log(f"ERROR in step '{label}' after {elapsed:.1f}s: {exc}")
            failed_steps.append(label)
            # Continue to next step to surface all errors in one run

    _log("=" * 60)
    if failed_steps:
        _log(f"Pipeline finished WITH ERRORS in steps: {', '.join(failed_steps)}")
        sys.exit(1)
    else:
        _log("Pipeline finished successfully. All steps passed.")


if __name__ == "__main__":
    main()
