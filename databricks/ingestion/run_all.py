"""
Master orchestrator for the Legacy CDW to Delta Lake migration pipeline.

Executes all ingestion scripts in the correct dependency order:
  1. Create the loan_warehouse database (DDL)
  2. Ingest borrowers     (no FK dependencies)
  3. Ingest loan_products  (no FK dependencies)
  4. Ingest loan_accounts  (depends on borrowers + loan_products)
  5. Ingest payments       (depends on loan_accounts)
  6. Run data quality validation checks

Each step logs its progress and any data quality issues.
The pipeline halts on critical errors but continues past non-fatal warnings.
"""

from pyspark.sql import SparkSession
import logging
import sys
import time

# ---------------------------------------------------------------------------
# Configure logging for the full pipeline
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("cdw_migration.run_all")


def run_pipeline(
    spark: SparkSession,
    source_base_path: str = "/mnt/landing/cdw",
    source_format: str = "csv",
    run_quality_checks: bool = True,
) -> dict:
    """
    Execute the complete CDW-to-Delta-Lake migration pipeline.

    Args:
        spark: Active SparkSession.
        source_base_path: Base path to the landing zone containing
                          sub-folders for each legacy table.
        source_format: File format of the source files ("csv" or "parquet").
        run_quality_checks: Whether to execute the data quality framework
                            after ingestion completes.

    Returns:
        Dictionary summarizing row counts and timing for each step.
    """
    results = {}
    pipeline_start = time.time()

    # -----------------------------------------------------------------------
    # Step 0: Create target database
    # -----------------------------------------------------------------------
    logger.info("=" * 70)
    logger.info("Step 0: Creating loan_warehouse database")
    logger.info("=" * 70)
    spark.sql("CREATE DATABASE IF NOT EXISTS loan_warehouse")
    logger.info("Database loan_warehouse is ready.")

    # -----------------------------------------------------------------------
    # Step 1: Ingest borrowers (no FK dependencies)
    # -----------------------------------------------------------------------
    logger.info("=" * 70)
    logger.info("Step 1: Ingesting borrowers from CDW_BORR_MSTR")
    logger.info("=" * 70)
    step_start = time.time()
    try:
        from ingest_borrowers import run as run_borrowers
        borrowers_df = run_borrowers(
            spark,
            source_path=f"{source_base_path}/CDW_BORR_MSTR",
            source_format=source_format,
        )
        results["borrowers"] = {
            "rows": borrowers_df.count(),
            "duration_sec": round(time.time() - step_start, 2),
            "status": "SUCCESS",
        }
    except Exception as e:
        logger.error("CRITICAL: Borrowers ingestion failed: %s", str(e))
        results["borrowers"] = {"status": "FAILED", "error": str(e)}
        # Borrowers is a prerequisite for loan_accounts — halt pipeline
        raise RuntimeError("Pipeline halted: borrowers ingestion failed.") from e

    # -----------------------------------------------------------------------
    # Step 2: Ingest loan products (no FK dependencies)
    # -----------------------------------------------------------------------
    logger.info("=" * 70)
    logger.info("Step 2: Ingesting loan products from CDW_LN_PROD")
    logger.info("=" * 70)
    step_start = time.time()
    try:
        from ingest_loan_products import run as run_products
        products_df = run_products(
            spark,
            source_path=f"{source_base_path}/CDW_LN_PROD",
            source_format=source_format,
        )
        results["loan_products"] = {
            "rows": products_df.count(),
            "duration_sec": round(time.time() - step_start, 2),
            "status": "SUCCESS",
        }
    except Exception as e:
        logger.error("CRITICAL: Loan products ingestion failed: %s", str(e))
        results["loan_products"] = {"status": "FAILED", "error": str(e)}
        raise RuntimeError("Pipeline halted: loan_products ingestion failed.") from e

    # -----------------------------------------------------------------------
    # Step 3: Ingest loan accounts (depends on borrowers + loan_products)
    # -----------------------------------------------------------------------
    logger.info("=" * 70)
    logger.info("Step 3: Ingesting loan accounts from CDW_LN_ACCT")
    logger.info("=" * 70)
    step_start = time.time()
    try:
        from ingest_loan_accounts import run as run_accounts
        accounts_df = run_accounts(
            spark,
            source_path=f"{source_base_path}/CDW_LN_ACCT",
            source_format=source_format,
        )
        results["loan_accounts"] = {
            "rows": accounts_df.count(),
            "duration_sec": round(time.time() - step_start, 2),
            "status": "SUCCESS",
        }
    except Exception as e:
        logger.error("CRITICAL: Loan accounts ingestion failed: %s", str(e))
        results["loan_accounts"] = {"status": "FAILED", "error": str(e)}
        raise RuntimeError("Pipeline halted: loan_accounts ingestion failed.") from e

    # -----------------------------------------------------------------------
    # Step 4: Ingest payments (depends on loan_accounts)
    # -----------------------------------------------------------------------
    logger.info("=" * 70)
    logger.info("Step 4: Ingesting payments from CDW_PMT_HIST")
    logger.info("=" * 70)
    step_start = time.time()
    try:
        from ingest_payments import run as run_payments
        payments_df = run_payments(
            spark,
            source_path=f"{source_base_path}/CDW_PMT_HIST",
            source_format=source_format,
        )
        results["payments"] = {
            "rows": payments_df.count(),
            "duration_sec": round(time.time() - step_start, 2),
            "status": "SUCCESS",
        }
    except Exception as e:
        logger.error("CRITICAL: Payments ingestion failed: %s", str(e))
        results["payments"] = {"status": "FAILED", "error": str(e)}
        raise RuntimeError("Pipeline halted: payments ingestion failed.") from e

    # -----------------------------------------------------------------------
    # Step 5: Data quality validation (optional but recommended)
    # -----------------------------------------------------------------------
    if run_quality_checks:
        logger.info("=" * 70)
        logger.info("Step 5: Running data quality checks")
        logger.info("=" * 70)
        try:
            from quality.data_quality import run_all_checks
            quality_results = run_all_checks(spark)
            results["data_quality"] = quality_results
        except ImportError:
            logger.warning("Data quality module not available. Skipping checks.")
            results["data_quality"] = {"status": "SKIPPED"}
        except Exception as e:
            logger.error("Data quality checks failed: %s", str(e))
            results["data_quality"] = {"status": "FAILED", "error": str(e)}

    # -----------------------------------------------------------------------
    # Pipeline summary
    # -----------------------------------------------------------------------
    total_duration = round(time.time() - pipeline_start, 2)
    logger.info("=" * 70)
    logger.info("PIPELINE COMPLETE — Total duration: %s seconds", total_duration)
    logger.info("=" * 70)
    for table, info in results.items():
        if isinstance(info, dict) and "rows" in info:
            logger.info("  %s: %d rows in %ss [%s]",
                        table, info["rows"], info["duration_sec"], info["status"])
        elif isinstance(info, dict):
            logger.info("  %s: [%s]", table, info.get("status", "UNKNOWN"))

    results["total_duration_sec"] = total_duration
    return results


# ---------------------------------------------------------------------------
# Databricks notebook entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    spark = SparkSession.builder.appName("CDW_Full_Migration_Pipeline").getOrCreate()

    # Configurable via Databricks widgets
    try:
        base_path = dbutils.widgets.get("source_base_path")  # noqa: F821
    except Exception:
        base_path = "/mnt/landing/cdw"
    try:
        fmt = dbutils.widgets.get("source_format")  # noqa: F821
    except Exception:
        fmt = "csv"
    try:
        do_quality = dbutils.widgets.get("run_quality_checks").lower() == "true"  # noqa: F821
    except Exception:
        do_quality = True

    results = run_pipeline(spark, base_path, fmt, do_quality)
