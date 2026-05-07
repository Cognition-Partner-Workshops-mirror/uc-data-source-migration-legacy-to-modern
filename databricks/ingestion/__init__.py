"""
PySpark ingestion scripts for the legacy-to-modern loan data migration.

Modules:
  - transformations : reusable UDFs and column-level transform helpers
  - ingest_borrowers : CDW_BORR_MSTR  -> borrowers
  - ingest_loan_products : CDW_LN_PROD -> loan_products
  - ingest_loan_accounts : CDW_LN_ACCT -> loan_accounts (+ borrower split)
  - ingest_payments : CDW_PMT_HIST    -> payments
  - run_ingestion : orchestrator that runs all four in dependency order
"""
