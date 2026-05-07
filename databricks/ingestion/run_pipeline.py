"""
Master pipeline orchestrator — runs all ingestion steps in dependency order.

Usage (Databricks notebook):
    from ingestion.run_pipeline import run_full_pipeline
    report = run_full_pipeline(spark, base_path="dbfs:/mnt/legacy/")

The ``base_path`` should contain subdirectories matching the legacy table names:
    base_path/
        cdw_borr_mstr/
        cdw_ln_prod/
        cdw_ln_acct/
        cdw_pmt_hist/
"""

import logging
import time
from dataclasses import dataclass, field

from pyspark.sql import SparkSession

from .ingest_borrowers import run as ingest_borrowers
from .ingest_loan_accounts import run as ingest_loan_accounts
from .ingest_loan_products import run as ingest_loan_products
from .ingest_payments import run as ingest_payments

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("pipeline")


@dataclass
class StepResult:
    name: str
    row_count: int = 0
    elapsed_seconds: float = 0.0
    status: str = "SUCCESS"
    error: str = ""


@dataclass
class PipelineReport:
    steps: list = field(default_factory=list)
    total_elapsed_seconds: float = 0.0

    def summary(self) -> str:
        lines = ["=" * 60, "PIPELINE EXECUTION SUMMARY", "=" * 60]
        for step in self.steps:
            lines.append(
                f"  {step.name:<25s}  {step.status:<10s}  "
                f"{step.row_count:>8d} rows  {step.elapsed_seconds:>7.1f}s"
            )
        lines.append("-" * 60)
        lines.append(f"  Total elapsed: {self.total_elapsed_seconds:.1f}s")
        overall = "SUCCESS" if all(s.status == "SUCCESS" for s in self.steps) else "FAILED"
        lines.append(f"  Overall status: {overall}")
        lines.append("=" * 60)
        return "\n".join(lines)


def _run_step(name: str, func, **kwargs) -> StepResult:
    """Execute a single ingestion step with timing and error handling."""
    logger.info(">>> Starting step: %s", name)
    start = time.time()
    try:
        df = func(**kwargs)
        row_count = df.count()
        elapsed = time.time() - start
        logger.info("<<< Completed step: %s (%d rows, %.1fs)", name, row_count, elapsed)
        return StepResult(name=name, row_count=row_count, elapsed_seconds=elapsed)
    except Exception as e:
        elapsed = time.time() - start
        logger.error("!!! Failed step: %s — %s", name, str(e))
        return StepResult(
            name=name, elapsed_seconds=elapsed, status="FAILED", error=str(e)
        )


def run_full_pipeline(
    spark: SparkSession,
    base_path: str,
    source_format: str = "csv",
    write_mode: str = "overwrite",
) -> PipelineReport:
    """Run the complete ingestion pipeline in dependency order.

    Order:
        1. borrowers      (no dependencies)
        2. loan_products   (no dependencies)
        3. loan_accounts   (depends on borrowers + loan_products)
        4. payments        (depends on loan_accounts)
    """
    report = PipelineReport()
    pipeline_start = time.time()

    bp = base_path.rstrip("/")

    # Step 1: Borrowers
    result = _run_step(
        "borrowers",
        ingest_borrowers,
        spark=spark,
        source_path=f"{bp}/cdw_borr_mstr/",
        source_format=source_format,
        write_mode=write_mode,
    )
    report.steps.append(result)

    # Step 2: Loan Products
    result = _run_step(
        "loan_products",
        ingest_loan_products,
        spark=spark,
        source_path=f"{bp}/cdw_ln_prod/",
        source_format=source_format,
        write_mode=write_mode,
    )
    report.steps.append(result)

    # Step 3: Loan Accounts (depends on 1 + 2)
    if report.steps[0].status == "SUCCESS" and report.steps[1].status == "SUCCESS":
        result = _run_step(
            "loan_accounts",
            ingest_loan_accounts,
            spark=spark,
            source_path=f"{bp}/cdw_ln_acct/",
            source_format=source_format,
            write_mode=write_mode,
        )
    else:
        result = StepResult(
            name="loan_accounts",
            status="SKIPPED",
            error="Skipped due to upstream failure (borrowers or loan_products)",
        )
    report.steps.append(result)

    # Step 4: Payments (depends on 3)
    if result.status == "SUCCESS":
        result = _run_step(
            "payments",
            ingest_payments,
            spark=spark,
            source_path=f"{bp}/cdw_pmt_hist/",
            source_format=source_format,
            write_mode=write_mode,
        )
    else:
        result = StepResult(
            name="payments",
            status="SKIPPED",
            error="Skipped due to upstream failure (loan_accounts)",
        )
    report.steps.append(result)

    report.total_elapsed_seconds = time.time() - pipeline_start
    logger.info("\n%s", report.summary())
    return report
