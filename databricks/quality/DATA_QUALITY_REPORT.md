# Data Quality Report

**Generated:** *(Run `databricks/quality/runner.py` to generate live results)*

## Summary

| Metric | Value |
|--------|-------|
| Total Checks | 28 |
| Passed | TBD |
| Failed | TBD |
| Pass Rate | TBD |

**Overall Status:** Run pipeline to determine

## Row Count Reconciliation (4 checks)

| Status | Check | Details |
|--------|-------|---------|
| — | Row count: loan_warehouse.borrowers | Source vs target + quarantined |
| — | Row count: loan_warehouse.loan_products | Source vs target + quarantined |
| — | Row count: loan_warehouse.loan_accounts | Source vs target + quarantined |
| — | Row count: loan_warehouse.payments | Source vs target + quarantined |

## Null Checks on Required Fields (15 checks)

Validates that the following required fields contain no NULL values:

- **borrowers:** external_id, first_name, last_name, status
- **loan_products:** code, name, type, term_months, rate_type, is_active
- **loan_accounts:** account_number, borrower_id, product_id, original_amount, current_balance, interest_rate, term_months, monthly_payment, origination_date, maturity_date, status
- **payments:** loan_account_id, payment_date, total_amount, type, status

## Referential Integrity (3 checks)

| Status | Check | Details |
|--------|-------|---------|
| — | FK: loan_accounts.borrower_id -> borrowers.id | Orphan check |
| — | FK: loan_accounts.product_id -> loan_products.id | Orphan check |
| — | FK: payments.loan_account_id -> loan_accounts.id | Orphan check |

## Business Rule Validations (6 checks)

| Status | Check | Details |
|--------|-------|---------|
| — | Active loans have positive balance | current_balance > 0 for ACTIVE loans |
| — | Closed loans have maturity date | maturity_date NOT NULL for CLOSED loans |
| — | Interest rate in valid range (0-30%) | Reasonable rate bounds |
| — | Payment amounts are positive | total_amount > 0 |
| — | Origination date before maturity date | Temporal consistency |
| — | Delinquency days non-negative | delinquency_days >= 0 |

## Quarantine Summary

Records that failed critical parsing are stored in quarantine tables:
- `loan_warehouse._quarantine_borrowers`
- `loan_warehouse._quarantine_loan_products`
- `loan_warehouse._quarantine_loan_accounts`
- `loan_warehouse._quarantine_payments`

Review quarantined records and resolve data issues before marking migration as complete.

---
*This is a template report. Run the quality runner to populate with actual results.*
