"""
Orchestrator: runs the full ingestion + quality pipeline in order.

Execution order:
  1. DDL (create schema and tables)
  2. Ingest borrowers (no FK dependencies)
  3. Ingest loan products (no FK dependencies)
  4. Ingest loan accounts (depends on borrowers + products)
  5. Ingest payments (depends on loan accounts)
  6. Data quality checks (validates all tables)

Usage (Databricks notebook):
    %run ./run_pipeline
"""

from pyspark.sql import SparkSession


def run_ddl(spark: SparkSession):
    """Execute Delta Lake DDL scripts."""
    ddl_files = [
        "../ddl/create_schema.sql",
        "../ddl/create_borrowers.sql",
        "../ddl/create_loan_products.sql",
        "../ddl/create_loan_accounts.sql",
        "../ddl/create_payments.sql",
    ]
    for ddl_file in ddl_files:
        print(f"Executing DDL: {ddl_file}")
        with open(ddl_file) as f:
            statements = f.read().split(";")
            for stmt in statements:
                stmt = stmt.strip()
                if stmt:
                    spark.sql(stmt)
    print("DDL execution complete.")


def run(spark: SparkSession):
    """Run the full migration pipeline."""
    print("=" * 70)
    print("LOAN WAREHOUSE MIGRATION PIPELINE")
    print("=" * 70)

    # Step 1: DDL
    print("\n>>> Step 1: Create schema and tables")
    run_ddl(spark)

    # Step 2: Ingest borrowers
    print("\n>>> Step 2: Ingest borrowers")
    from databricks.ingestion.ingest_borrowers import run as ingest_borrowers
    borr_source, borr_good, borr_bad = ingest_borrowers(spark)

    # Step 3: Ingest loan products
    print("\n>>> Step 3: Ingest loan products")
    from databricks.ingestion.ingest_loan_products import run as ingest_products
    prod_source, prod_good, prod_dropped = ingest_products(spark)

    # Step 4: Ingest loan accounts
    print("\n>>> Step 4: Ingest loan accounts")
    from databricks.ingestion.ingest_loan_accounts import run as ingest_accounts
    acct_source, acct_good, acct_bad = ingest_accounts(spark)

    # Step 5: Ingest payments
    print("\n>>> Step 5: Ingest payments")
    from databricks.ingestion.ingest_payments import run as ingest_payments
    pmt_source, pmt_good, pmt_bad = ingest_payments(spark)

    # Step 6: Data quality checks
    print("\n>>> Step 6: Data quality checks")
    source_counts = {
        "CDW_BORR_MSTR": borr_source,
        "CDW_LN_PROD": prod_source,
        "CDW_LN_ACCT": acct_source,
        "CDW_PMT_HIST": pmt_source,
    }
    from databricks.quality.data_quality_checks import run as run_quality
    report = run_quality(spark, source_counts=source_counts)

    # Summary
    print("\n" + "=" * 70)
    print("PIPELINE SUMMARY")
    print("=" * 70)
    print(f"Borrowers:     {borr_source} source -> {borr_good} loaded, {borr_bad} quarantined")
    print(f"Products:      {prod_source} source -> {prod_good} loaded, {prod_dropped} dropped")
    print(f"Loan Accounts: {acct_source} source -> {acct_good} loaded, {acct_bad} quarantined")
    print(f"Payments:      {pmt_source} source -> {pmt_good} loaded, {pmt_bad} quarantined")
    print(f"Quality:       {report.pass_count}/{report.total} checks passed")
    print("=" * 70)


if __name__ == "__main__":
    spark = SparkSession.builder.getOrCreate()
    run(spark)
