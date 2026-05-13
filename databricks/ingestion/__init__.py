# =============================================================================
# PySpark Ingestion Package for Legacy CDW to Delta Lake Migration
# =============================================================================
# This package contains ingestion scripts for migrating loan management data
# from the legacy CDW (Corporate Data Warehouse) system to Delta Lake tables.
#
# Modules:
#   - transformations : Shared transformation functions (date parsing, amount
#                       parsing, status code expansion, null handling)
#   - ingest_borrowers : Reads CDW_BORR_MSTR and writes to loan_warehouse.borrowers
#   - ingest_loan_products : Reads CDW_LN_PROD and writes to loan_warehouse.loan_products
#   - ingest_loan_accounts : Reads CDW_LN_ACCT and writes to loan_warehouse.loan_accounts
#   - ingest_payments : Reads CDW_PMT_HIST and writes to loan_warehouse.payments
#   - run_all : Orchestrator that executes the full pipeline in dependency order
# =============================================================================
