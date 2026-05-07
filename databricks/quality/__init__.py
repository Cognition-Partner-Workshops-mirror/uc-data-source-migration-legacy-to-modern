"""
Data Quality Framework for the CDW to Delta Lake migration.

Provides post-ingestion validation checks:
- Row count reconciliation (source vs. target)
- Null checks on required fields
- Referential integrity between loan and borrower tables
- Business rule validation
- Consolidated reporting
"""
