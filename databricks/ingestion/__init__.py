"""
PySpark ingestion pipeline for legacy CDW to modern Delta Lake migration.

Modules:
    utils       - Shared parsing and transformation utilities
    ingest_borrowers    - CDW_BORR_MSTR -> borrowers
    ingest_loan_products - CDW_LN_PROD -> loan_products
    ingest_loan_accounts - CDW_LN_ACCT -> loan_accounts
    ingest_payments     - CDW_PMT_HIST -> payments
    run_pipeline        - Orchestrator to run full migration
"""
