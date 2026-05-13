# =============================================================================
# Data Quality Framework for the CDW to Delta Lake Migration
# =============================================================================
# Post-ingestion validation module that checks:
#   - Row count reconciliation (source vs. target)
#   - Null checks on required fields
#   - Referential integrity between loan and borrower tables
#   - Business rule validation (active loan balances, closed loan dates, etc.)
#   - Generates a DATA_QUALITY_REPORT.md summarizing pass/fail results
# =============================================================================
