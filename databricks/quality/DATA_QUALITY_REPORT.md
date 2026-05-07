# Data Quality Report

**Generated:** *(populated at runtime)*
**Duration:** *(populated at runtime)*
**Total Checks:** *(populated at runtime)*
**Passed:** *(populated at runtime)*
**Failed:** *(populated at runtime)*

**Overall Status:** *(populated at runtime)*

---

> This file is a **template**. Run `data_quality_checks.py` after ingestion
> to generate the actual report with real pass/fail results.

## Row Count

| Check | Status | Severity | Detail |
|-------|--------|----------|--------|
| borrowers_count_match | *(run)* | ERROR | source=5, target=5 (expected) |
| loan_products_count_match | *(run)* | ERROR | source=5, target=5 (expected) |
| loan_accounts_count_match | *(run)* | ERROR | source=5, target=5 (expected) |
| payments_count_match | *(run)* | ERROR | source=10, target=10 (expected) |

## Null Check

| Check | Status | Severity | Detail |
|-------|--------|----------|--------|
| borrowers.external_id | *(run)* | ERROR | null_count=0 (expected) |
| borrowers.first_name | *(run)* | ERROR | null_count=0 (expected) |
| borrowers.last_name | *(run)* | ERROR | null_count=0 (expected) |
| borrowers.status | *(run)* | ERROR | null_count=0 (expected) |
| loan_accounts.borrower_id | *(run)* | ERROR | null_count=0 (expected) |
| loan_accounts.product_id | *(run)* | ERROR | null_count=0 (expected) |
| payments.loan_account_id | *(run)* | ERROR | null_count=0 (expected) |

## Referential Integrity

| Check | Status | Severity | Detail |
|-------|--------|----------|--------|
| loan_accounts.borrower_id -> borrowers | *(run)* | ERROR | orphan_count=0 (expected) |
| loan_accounts.product_id -> loan_products | *(run)* | ERROR | orphan_count=0 (expected) |
| payments.loan_account_id -> loan_accounts | *(run)* | ERROR | orphan_count=0 (expected) |

## Business Rule

| Check | Status | Severity | Detail |
|-------|--------|----------|--------|
| active_loans_positive_balance | *(run)* | ERROR | Active loans with balance <= 0: 0 (expected) |
| interest_rate_range | *(run)* | ERROR | Rates outside 0-100: 0 (expected) |
| maturity_after_origination | *(run)* | ERROR | Maturity <= origination: 0 (expected) |
| ltv_percent_range | *(run)* | WARNING | LTV outside 0-200: 0 (expected) |
| delinquency_days_non_negative | *(run)* | ERROR | Negative days: 0 (expected) |
| loan_status_valid | *(run)* | ERROR | Unknown status: 0 (expected) |
| payment_component_sum | *(run)* | WARNING | Mismatched totals: 0 (expected) |
| payment_status_valid | *(run)* | ERROR | Unknown status: 0 (expected) |
