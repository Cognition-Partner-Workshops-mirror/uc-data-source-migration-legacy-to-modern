"""
Data Quality Framework for CDW Legacy-to-Modern Migration.

Provides post-ingestion validation checks including:
- Row count reconciliation (source vs. target)
- Null checks on required fields
- Referential integrity between loan and borrower tables
- Business rule validation
- Generates DATA_QUALITY_REPORT.md with pass/fail results
"""
