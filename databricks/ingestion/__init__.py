"""
PySpark Ingestion Pipeline for Legacy CDW to Delta Lake Migration.
Contains individual ingestion scripts for each source table:
- ingest_borrowers.py: CDW_BORR_MSTR → loan_warehouse.borrowers
- ingest_loan_products.py: CDW_LN_PROD → loan_warehouse.loan_products
- ingest_loan_accounts.py: CDW_LN_ACCT → loan_warehouse.loan_accounts
- ingest_payments.py: CDW_PMT_HIST → loan_warehouse.payments
"""
