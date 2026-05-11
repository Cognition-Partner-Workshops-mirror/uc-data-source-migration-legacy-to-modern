# Data Quality Report — CDW → Delta Lake Migration

> **Note:** This is a template. The actual report is generated at runtime by
> `data_quality_checks.py` and written to DBFS after each migration run.

**Run Timestamp:** *(populated at runtime)*
**Total Checks:** *(populated at runtime)*
**Passed:** *(populated at runtime)*
**Failed:** *(populated at runtime)*
**Overall Status:** *(populated at runtime)*

## Check Categories

### 1. Row Count Reconciliation
Compares the number of rows in each legacy source file against the target
Delta table. A mismatch indicates dropped or duplicated records.

| Source Table | Target Table | Expected |
|--------------|--------------|----------|
| CDW_BORR_MSTR | loan_warehouse.borrowers | Exact match |
| CDW_LN_PROD | loan_warehouse.loan_products | Exact match |
| CDW_LN_ACCT | loan_warehouse.loan_accounts | Exact match |
| CDW_PMT_HIST | loan_warehouse.payments | Exact match |

### 2. Null Checks on Required Fields
Validates that NOT NULL constraints defined in the Delta DDL are satisfied.

### 3. Referential Integrity
Verifies foreign key relationships:
- `loan_accounts.borrower_id` → `borrowers.id`
- `loan_accounts.product_id` → `loan_products.id`
- `payments.loan_account_id` → `loan_accounts.id`

### 4. Business Rule Validation
| Rule ID | Description |
|---------|-------------|
| BR-1 | Active loans must have current_balance > 0 |
| BR-2 | Closed loans must have a maturity_date |
| BR-3 | Payment components sum ≈ total (± $0.01 tolerance) |
| BR-4 | Delinquency days >= 0 |
| BR-5 | Interest rate in [0, 100] |
| BR-6 | Credit score in [300, 850] (where not null) |
