# Databricks Migration Runbook

## Overview

This runbook documents the complete migration pipeline from the legacy CDW (Corporate Data Warehouse) schema to a modern, properly typed Delta Lake schema on Databricks. It covers every transformation decision, column mapping, type conversion, partitioning rationale, and the recommended execution order.

---

## 1. Source System: Legacy CDW Schema

The legacy CDW uses a "VARCHAR-for-everything" approach with cryptic abbreviated column names, denormalized structures, and no foreign key constraints.

### Legacy Tables

| Table | Description | Rows (Seed) |
|-------|-------------|-------------|
| `CDW_BORR_MSTR` | Borrower master — all borrower personal/financial info | 5 |
| `CDW_LN_PROD` | Loan product reference data | 5 |
| `CDW_LN_ACCT` | Loan accounts — denormalized with borrower fields embedded | 5 |
| `CDW_PMT_HIST` | Payment history for all loan accounts | 10 |

### Legacy Schema Characteristics

1. **All-VARCHAR columns**: Dates, amounts, integers, and booleans stored as strings
2. **Cryptic column names**: Abbreviated (e.g., `BORR_FST_NM`, `LN_CURR_BAL`, `PMT_ESCROW_AMT`)
3. **Denormalization**: `CDW_LN_ACCT` duplicates borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`)
4. **No FK constraints**: No referential integrity enforced at the database level
5. **Status code abbreviations**: `ACT`, `CLO`, `DFT`, `FRB`, `PST`, `REV`, `NSF`, `PND`
6. **Date format**: `MM/DD/YYYY` stored as strings
7. **Amount format**: Comma-separated strings (e.g., `"285,000"`, `"1,487.02"`)

---

## 2. Target System: Delta Lake Schema

The modern schema on Databricks uses Delta Lake with proper Spark SQL types, meaningful names, normalization, and partitioning.

### Target Tables

| Table | Description | Partition Key |
|-------|-------------|---------------|
| `loan_management.borrowers` | Normalized borrower dimension | None (small dimension) |
| `loan_management.loan_products` | Loan product reference | None (small reference) |
| `loan_management.loan_accounts` | Loan account fact table | `status` |
| `loan_management.payments` | Payment transaction facts | `payment_year` |

### Partitioning Rationale

- **`loan_accounts` partitioned by `status`**: Most queries filter by loan status (active vs. closed vs. default). The low cardinality (4 values: ACTIVE, CLOSED, DEFAULT, FORBEARANCE) makes this efficient for partition pruning without creating too many small files.
- **`payments` partitioned by `payment_year`**: Payment queries are almost always time-bounded (e.g., "payments in 2025"). Year-level partitioning balances partition count against query selectivity.
- **`borrowers` and `loan_products`**: Not partitioned because they are small dimension/reference tables where full scans are acceptable.

---

## 3. Column Mapping Reference

### 3.1 CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `BORR_ID` | `external_id` | VARCHAR → STRING | Direct copy |
| `BORR_FST_NM` | `first_name` | VARCHAR → STRING | Direct copy |
| `BORR_LST_NM` | `last_name` | VARCHAR → STRING | Direct copy |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR → STRING | Direct copy |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR → STRING | Direct copy (re-encrypt recommended) |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR → DATE | Parse `MM/DD/YYYY` → DateType |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR → STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR → STRING | Direct copy |
| `BORR_CTY_NM` | `city` | VARCHAR → STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR → STRING | Direct copy |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR → STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR → STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR → STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR → INT | Cast string to integer |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR → STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR → DECIMAL(12,2) | Strip commas, cast to decimal |
| `BORR_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` → TimestampType |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` → TimestampType |
| `BORR_STAT_CD` | `status` | VARCHAR → STRING | Expand: ACT→ACTIVE, INA→INACTIVE |
| `BORR_REC_TYP` | *(dropped)* | — | Not needed in modern schema |

### 3.2 CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PROD_CD` | `code` | VARCHAR → STRING | Direct copy |
| `PROD_DESC_TXT` | `name` | VARCHAR → STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR → STRING | Direct copy (FXD, ARM, FHA, VA) |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | Cast string to integer |
| `PROD_RT_TYP` | `rate_type` | VARCHAR → STRING | Direct copy (FIXED, VARIABLE) |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) | Strip commas, cast to decimal |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) | Strip commas, cast to decimal |
| `PROD_STAT_CD` | `is_active` | VARCHAR → BOOLEAN | ACT→true, INA→false |
| `PROD_EFF_DT` | `effective_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` → DateType |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` → DateType |

### 3.3 CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `LN_ACCT_NBR` | `account_number` | VARCHAR → STRING | Direct copy |
| `BORR_ID` | `borrower_external_id` | VARCHAR → STRING | FK to borrowers.external_id |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_code` | VARCHAR → STRING | FK to loan_products.code |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) | Strip commas, cast |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) | Strip commas, cast |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | Cast string to decimal |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | Cast string to integer |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) | Strip commas, cast |
| `LN_ORIG_DT` | `origination_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_MAT_DT` | `maturity_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_STAT_CD` | `status` | VARCHAR → STRING | ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | Cast string to integer |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Strip commas, cast |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | Cast string to decimal |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR → STRING | SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Strip commas, cast |
| `LN_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `LN_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |

### 3.4 CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PMT_SEQ_NBR` | `legacy_payment_id` | VARCHAR → STRING | Preserved for reconciliation |
| `LN_ACCT_NBR` | `loan_account_number` | VARCHAR → STRING | FK to loan_accounts.account_number |
| `PMT_DT` | `payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_AMT` | `total_amount` | VARCHAR → DECIMAL(10,2) | Strip commas, cast |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR → DECIMAL(10,2) | Strip commas, cast |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR → DECIMAL(10,2) | Strip commas, cast |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR → DECIMAL(10,2) | Strip commas, cast |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR → DECIMAL(10,2) | Strip commas, cast |
| `PMT_TYP_CD` | `type` | VARCHAR → STRING | REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| `PMT_STAT_CD` | `status` | VARCHAR → STRING | PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| `PMT_RECV_DT` | `received_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_PROC_DT` | `processed_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| *(derived)* | `payment_year` | — | `year(payment_date)` for partitioning |

---

## 4. Type Conversion Decisions

### 4.1 Date/Time Handling

| Decision | Rationale |
|----------|-----------|
| Use Spark `to_date(col, "MM/dd/yyyy")` | The legacy format is consistently `MM/DD/YYYY` |
| Dates → `DateType` | For columns with date-only semantics (payment_date, origination_date) |
| Dates → `TimestampType` | For audit columns (created_at, updated_at) to support future time-of-day granularity |
| Unparseable values → `null` | Preserved as null with error flag in `_parse_errors` column |

### 4.2 Amount Handling

| Decision | Rationale |
|----------|-----------|
| Strip commas via `regexp_replace(col, ",", "")` | Legacy stores amounts like `"285,000"` and `"1,487.02"` |
| Cast to `DecimalType(12,2)` for large amounts | Supports up to $9,999,999,999.99 — sufficient for mortgage amounts |
| Cast to `DecimalType(10,2)` for payment amounts | Supports up to $99,999,999.99 — sufficient for individual payments |
| Cast to `DecimalType(5,3)` for interest rates | Supports up to 99.999% — sufficient for mortgage rates |
| Cast to `DecimalType(5,2)` for LTV percent | Supports up to 999.99% — sufficient for LTV ratios |

### 4.3 Status Code Expansion

All cryptic legacy status codes are expanded to human-readable values. Unknown codes are preserved as-is and flagged for manual review.

| Legacy Code | Expanded Value | Context |
|-------------|----------------|---------|
| `ACT` | `ACTIVE` | Borrower status, loan status, product status |
| `INA` | `INACTIVE` | Borrower status, product status |
| `CLO` | `CLOSED` | Loan status |
| `DFT` | `DEFAULT` | Loan status |
| `FRB` | `FORBEARANCE` | Loan status |
| `REG` | `REGULAR` | Payment type |
| `EXT` | `EXTRA` | Payment type |
| `PRT` | `PARTIAL` | Payment type |
| `PRE` | `PREPAYMENT` | Payment type |
| `PST` | `POSTED` | Payment status |
| `REV` | `REVERSED` | Payment status |
| `NSF` | `NSF` | Payment status (kept as-is — widely understood) |
| `PND` | `PENDING` | Payment status |
| `SFR` | `Single Family` | Property type |
| `CND` | `Condominium` | Property type |
| `MFR` | `Multi-Family` | Property type |
| `TWN` | `Townhouse` | Property type |

### 4.4 Normalization Decisions

| Decision | Rationale |
|----------|-----------|
| Drop `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` from loan_accounts | These are denormalized copies from the borrower master — use FK instead |
| Keep `borrower_external_id` as STRING FK | Allows natural-key joins to borrowers without synthetic ID lookup |
| Keep `product_code` as STRING FK | Allows natural-key joins to loan_products without synthetic ID lookup |
| Keep `loan_account_number` as STRING FK in payments | Allows natural-key joins to loan_accounts |
| Preserve `legacy_payment_id` in payments | Required for reconciliation between source and target systems |

---

## 5. Pipeline Architecture

### 5.1 Directory Structure

```
databricks/
├── ddl/
│   ├── create_borrowers.sql          # Delta Lake DDL for borrowers
│   ├── create_loan_products.sql      # Delta Lake DDL for loan_products
│   ├── create_loan_accounts.sql      # Delta Lake DDL for loan_accounts
│   └── create_payments.sql           # Delta Lake DDL for payments
├── ingestion/
│   ├── common_transforms.py          # Shared UDFs and transformation utilities
│   ├── ingest_borrowers.py           # Borrower ingestion pipeline
│   ├── ingest_loan_products.py       # Loan product ingestion pipeline
│   ├── ingest_loan_accounts.py       # Loan account ingestion pipeline
│   ├── ingest_payments.py            # Payment ingestion pipeline
│   └── run_all.py                    # Orchestrator — runs all steps in order
└── quality/
    └── data_quality_checks.py        # Post-ingestion validation framework
```

### 5.2 Shared Utilities (`common_transforms.py`)

All transformation functions are centralized in `common_transforms.py` to ensure consistency:

- **`parse_date_col()`**: `MM/DD/YYYY` string → `DateType`
- **`parse_timestamp_col()`**: `MM/DD/YYYY` string → `TimestampType`
- **`parse_amount_col()`**: Comma-formatted string → `DecimalType`
- **`parse_int_col()`**: String → `IntegerType`
- **`expand_status_col()`**: Abbreviation → full value using lookup map
- **`expand_status_to_bool()`**: Abbreviation → `BooleanType`
- **`add_parse_error_flags()`**: Adds `_parse_errors` array column for monitoring
- **`log_transformation_summary()`**: Prints row counts and error summaries

### 5.3 Error Handling Strategy

The pipeline does **not silently drop records**. Instead:

1. **Parse failures** → null value in the target column
2. **Error tracking** → `_parse_errors` array column lists which fields had issues
3. **Summary logging** → Each ingestion step prints total rows vs. rows with errors
4. **Unknown status codes** → Preserved as-is (not expanded) and logged
5. **Orchestrator continues** → If one table fails, remaining tables still execute
6. **Exit code** → Non-zero if any step failed

---

## 6. Recommended Execution Order

### 6.1 Pre-Migration Setup

```
Step 0: Create the target database/schema
  → Run: CREATE DATABASE IF NOT EXISTS loan_management;

Step 1: Stage legacy data as CSV/Parquet files
  → Export CDW tables to /mnt/legacy-data/ as CSV with headers
  → Alternatively, export as Parquet for better performance
```

### 6.2 DDL Execution (Create Target Tables)

Execute in this order (no dependencies between tables):

```
Step 2a: databricks/ddl/create_borrowers.sql
Step 2b: databricks/ddl/create_loan_products.sql
Step 2c: databricks/ddl/create_loan_accounts.sql
Step 2d: databricks/ddl/create_payments.sql
```

These can be run in parallel since there are no cross-table dependencies in the DDL (Delta Lake does not enforce FK constraints at the storage layer).

### 6.3 Ingestion Execution (Transform & Load)

Execute in strict dependency order:

```
Step 3a: databricks/ingestion/ingest_borrowers.py
  → No dependencies. Creates borrower dimension first.

Step 3b: databricks/ingestion/ingest_loan_products.py
  → No dependencies. Creates product reference data.
  → Can run in parallel with Step 3a.

Step 3c: databricks/ingestion/ingest_loan_accounts.py
  → Depends on: borrowers (for borrower_external_id), loan_products (for product_code)
  → Must run AFTER Steps 3a and 3b.

Step 3d: databricks/ingestion/ingest_payments.py
  → Depends on: loan_accounts (for loan_account_number)
  → Must run AFTER Step 3c.
```

**Or use the orchestrator**: `databricks/ingestion/run_all.py` handles the ordering automatically.

### 6.4 Post-Migration Validation

```
Step 4: databricks/quality/data_quality_checks.py
  → Runs all validation checks: row counts, nulls, referential integrity, business rules
  → Generates DATA_QUALITY_REPORT.md
```

### 6.5 Post-Migration Cleanup

```
Step 5: Review DATA_QUALITY_REPORT.md
  → Investigate any FAIL results
  → Re-run specific ingestion steps if needed

Step 6: Optimize Delta tables
  → OPTIMIZE loan_management.loan_accounts ZORDER BY (borrower_external_id);
  → OPTIMIZE loan_management.payments ZORDER BY (loan_account_number, payment_date);

Step 7: Set up table maintenance
  → Schedule VACUUM and OPTIMIZE jobs in Databricks workflows
```

---

## 7. Configuration Reference

### Source Paths (Update for Your Environment)

| Table | Default Path | Format |
|-------|-------------|--------|
| CDW_BORR_MSTR | `/mnt/legacy-data/cdw_borr_mstr/` | CSV |
| CDW_LN_PROD | `/mnt/legacy-data/cdw_ln_prod/` | CSV |
| CDW_LN_ACCT | `/mnt/legacy-data/cdw_ln_acct/` | CSV |
| CDW_PMT_HIST | `/mnt/legacy-data/cdw_pmt_hist/` | CSV |

### Target Tables

| Table | Full Name |
|-------|-----------|
| borrowers | `loan_management.borrowers` |
| loan_products | `loan_management.loan_products` |
| loan_accounts | `loan_management.loan_accounts` |
| payments | `loan_management.payments` |

### Delta Lake Table Properties

All tables use:
- `delta.autoOptimize.optimizeWrite = true` — automatic file size optimization on write
- `delta.autoOptimize.autoCompact = true` — automatic small file compaction

---

## 8. Data Quality Checks

The quality framework (`databricks/quality/data_quality_checks.py`) validates:

### 8.1 Row Count Reconciliation
- Source row count vs. target row count for each table
- Expected: exact match (no dropped records)

### 8.2 Null Checks
- Required fields must have no nulls:
  - `borrowers`: external_id, first_name, last_name
  - `loan_products`: code, name, type, term_months, rate_type
  - `loan_accounts`: account_number, borrower_external_id, product_code, original_amount, current_balance, interest_rate, term_months, monthly_payment, origination_date, maturity_date
  - `payments`: loan_account_number, payment_date, total_amount, type, status

### 8.3 Referential Integrity
- `loan_accounts.borrower_external_id` → `borrowers.external_id`
- `loan_accounts.product_code` → `loan_products.code`
- `payments.loan_account_number` → `loan_accounts.account_number`

### 8.4 Business Rules
- Active loans must have `current_balance > 0`
- Closed loans must have a `maturity_date`
- Payment components must sum correctly: `principal + interest + escrow ≈ total (±$0.02)`
- No POSTED payments with future `payment_date`
- Credit scores must be in range 300–850
- Interest rates must be in range 0–30%

---

## 9. Troubleshooting

### Common Issues

| Issue | Cause | Resolution |
|-------|-------|------------|
| Date parsing returns null | Non-standard date format in source | Check `_parse_errors` column; update parse format if needed |
| Amount parsing returns null | Unexpected characters (e.g., `$`, spaces) | Add additional `regexp_replace` rules in `parse_amount_col()` |
| Row count mismatch | Duplicate rows in source or dedup in target | Check source for duplicates; add dedup step if needed |
| FK violation (orphan records) | Missing parent records | Ensure dimension tables are loaded before fact tables |
| Status code not expanded | Unknown/new status code in source | Add the new code to the appropriate map in `common_transforms.py` |

### Monitoring Queries

```sql
-- Check for parse errors in any table
SELECT * FROM loan_management.loan_accounts
WHERE size(_parse_errors) > 0;

-- Verify status code distribution
SELECT status, count(*) FROM loan_management.loan_accounts GROUP BY status;

-- Check payment component totals
SELECT legacy_payment_id, total_amount,
       principal_amount + interest_amount + escrow_amount AS component_sum,
       total_amount - (principal_amount + interest_amount + escrow_amount) AS difference
FROM loan_management.payments
WHERE ABS(total_amount - (principal_amount + interest_amount + escrow_amount)) > 0.02;
```
