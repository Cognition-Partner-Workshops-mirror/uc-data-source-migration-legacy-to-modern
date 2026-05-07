"""
Data quality validation framework for the loan data warehouse.

Modules:
  - validators : individual check functions (row counts, nulls, referential integrity, business rules)
  - run_quality_checks : orchestrator that runs all checks and generates DATA_QUALITY_REPORT.md
"""
