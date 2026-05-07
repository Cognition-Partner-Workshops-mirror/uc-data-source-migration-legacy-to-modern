"""
PySpark ingestion pipeline for migrating legacy CDW loan data to Delta Lake.

Modules:
    transformations: Common UDFs and transformation functions
    ingest_borrowers: Borrower dimension ingestion
    ingest_loan_products: Loan product reference ingestion
    ingest_loan_accounts: Loan account fact ingestion
    ingest_payments: Payment history fact ingestion
    run_pipeline: Orchestrator for full migration run
"""
