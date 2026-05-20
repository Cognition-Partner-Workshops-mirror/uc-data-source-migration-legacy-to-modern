# Data Quality Report

**Generated:** *(populated automatically by data_quality_checks.py after each run)*
**Pipeline:** Legacy CDW → Delta Lake Migration

## Summary

| Metric | Count |
|--------|-------|
| Total Checks | — |
| Passed | — |
| Failed | — |
| Not Run | — |
| **Pass Rate** | **—** |

**Overall Status:** *(PASS or FAIL — populated after execution)*

> **Note:** This is a template. Run `databricks/quality/data_quality_checks.py` after
> ingestion to generate a populated report. The script writes the results to
> `/dbfs/mnt/reports/DATA_QUALITY_REPORT.md` on Databricks, or prints to stdout
> if the path is not writable.

## Row Count (source vs. target)

| Check | Status | Details |
|-------|--------|---------|
| Row count reconciliation for borrowers | — | — |
| Row count reconciliation for loan_products | — | — |
| Row count reconciliation for loan_accounts | — | — |
| Row count reconciliation for payments | — | — |

## Null Check (required fields)

| Check | Status | Details |
|-------|--------|---------|
| No nulls in borrowers.external_id | — | — |
| No nulls in borrowers.first_name | — | — |
| No nulls in borrowers.last_name | — | — |
| No nulls in loan_products.code | — | — |
| No nulls in loan_products.name | — | — |
| No nulls in loan_accounts.account_number | — | — |
| No nulls in loan_accounts.borrower_external_id | — | — |
| No nulls in loan_accounts.original_amount | — | — |
| No nulls in payments.loan_account_number | — | — |
| No nulls in payments.payment_date | — | — |
| No nulls in payments.total_amount | — | — |
| *(additional required field checks)* | — | — |

## Referential Integrity

| Check | Status | Details |
|-------|--------|---------|
| Every loan account references a valid borrower | — | — |
| Every loan account references a valid product | — | — |
| Every payment references a valid loan account | — | — |

## Business Rule

| Check | Status | Details |
|-------|--------|---------|
| Active loans must have current_balance > 0 | — | — |
| Closed loans must have a maturity_date | — | — |
| principal + interest + escrow ≈ total_amount (±$0.02 tolerance) | — | — |
| POSTED payments must not have a future payment_date | — | — |
| Borrower credit scores must be between 300 and 850 | — | — |
| Loan interest rates must be between 0% and 30% | — | — |
