# Databricks Migration Runbook

## Legacy CDW → Modern Delta Lake Migration

This runbook documents the complete migration pipeline from the legacy Corporate Data Warehouse (CDW) schema to the modern Delta Lake schema on Databricks.

---

## Table of Contents

1. [Overview](#overview)
2. [Legacy Schema Summary](#legacy-schema-summary)
3. [Column Mapping Reference](#column-mapping-reference)
4. [Type Conversion Decisions](#type-conversion-decisions)
5. [Status Code Expansion](#status-code-expansion)
6. [Partitioning Strategy](#partitioning-strategy)
7. [Execution Order](#execution-order)
8. [Pre-Migration Checklist](#pre-migration-checklist)
9. [Running the Pipeline](#running-the-pipeline)
10. [Post-Migration Validation](#post-migration-validation)
11. [Troubleshooting](#troubleshooting)

---

## Overview

The legacy CDW loan management system stores all data as VARCHAR columns with cryptic abbreviated names, string-encoded dates (`MM/DD/YYYY`), comma-formatted amounts (`"285,000"`), and abbreviated status codes (`ACT`, `CLO`, `DFT`, `FRB`). The modern schema normalizes this into four Delta Lake tables with proper types, meaningful names, and FK relationships.

### Architecture

```
Legacy CDW (CSV/Parquet export)     Modern Delta Lake (loan_warehouse)
─────────────────────────────       ─────────────────────────────────
CDW_BORR_MSTR  ──────────────────► borrowers
CDW_LN_PROD    ──────────────────► loan_products
CDW_LN_ACCT    ──┬───────────────► loan_accounts
                 └─(drop denorm      (FK → borrowers, loan_products)
                    borrower fields)
CDW_PMT_HIST   ──────────────────► payments
                                     (FK → loan_accounts)
```

### Key Transformations

| Transformation | Example |
|---------------|---------|
| Date parsing | `"03/15/1978"` → `1978-03-15` (DATE) |
| Amount parsing | `"285,000"` → `285000.00` (DECIMAL) |
| Status expansion | `ACT` → `Active` |
| Denormalization removal | Borrower fields dropped from loan_accounts |
| FK resolution | `BORR_ID` string → `borrower_id` BIGINT |
| Property type expansion | `SFR` → `Single Family` |

---

## Legacy Schema Summary

### CDW_BORR_MSTR (Borrower Master)
- **20 columns**, all VARCHAR
- Contains borrower PII, address, financial data
- Status codes: `ACT` (Active), `INA` (Inactive)
- Record type field (`BORR_REC_TYP`) dropped in migration

### CDW_LN_PROD (Loan Products)
- **10 columns**, all VARCHAR
- Reference table for product catalog
- Product types: `FXD`, `ARM`, `FHA`, `VA`
- Rate types: `FIXED`, `VARIABLE`

### CDW_LN_ACCT (Loan Accounts)
- **30 columns**, all VARCHAR
- **Denormalized**: includes `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` (redundant with CDW_BORR_MSTR)
- Loan status codes: `ACT`, `CLO`, `DFT`, `FRB`
- Property type codes: `SFR`, `CND`, `MFR`, `TWN`

### CDW_PMT_HIST (Payment History)
- **14 columns**, all VARCHAR
- Payment type codes: `REG`, `EXT`, `PRT`, `PRE`
- Payment status codes: `PST`, `REV`, `NSF`, `PND`

---

## Column Mapping Reference

### CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `BORR_ID` | `external_id` | VARCHAR → STRING | Direct copy |
| `BORR_FST_NM` | `first_name` | VARCHAR → STRING | Direct copy |
| `BORR_LST_NM` | `last_name` | VARCHAR → STRING | Direct copy |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR → STRING | Direct copy |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR → STRING | Direct copy |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR → STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR → STRING | Direct copy |
| `BORR_CTY_NM` | `city` | VARCHAR → STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR → STRING | Direct copy |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR → STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR → STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR → STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR → INT | Parse string |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR → STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR → DECIMAL(12,2) | Remove commas |
| `BORR_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |
| `BORR_STAT_CD` | `status` | VARCHAR → STRING | Expand code |
| `BORR_REC_TYP` | *(dropped)* | — | Not needed |

### CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PROD_CD` | `code` | VARCHAR → STRING | Direct copy |
| `PROD_DESC_TXT` | `name` | VARCHAR → STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR → STRING | Direct copy |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | Parse string |
| `PROD_RT_TYP` | `rate_type` | VARCHAR → STRING | Direct copy |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) | Remove commas |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) | Remove commas |
| `PROD_STAT_CD` | `is_active` | VARCHAR → BOOLEAN | ACT→true, INA→false |
| `PROD_EFF_DT` | `effective_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR → DATE | Parse MM/DD/YYYY |

### CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `LN_ACCT_NBR` | `account_number` | VARCHAR → STRING | Direct copy |
| `BORR_ID` | `borrower_id` | VARCHAR → BIGINT | FK lookup |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use FK |
| `PROD_CD` | `product_id` | VARCHAR → BIGINT | FK lookup |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) | Remove commas |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) | Remove commas |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | Parse string |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | Parse string |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) | Remove commas |
| `LN_ORIG_DT` | `origination_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `LN_MAT_DT` | `maturity_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `LN_STAT_CD` | `status` | VARCHAR → STRING | Expand code |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | Parse string |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Remove commas |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | Parse string |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR → STRING | Expand code |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Remove commas |
| `LN_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |
| `LN_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |
| *(derived)* | `origination_year` | — | `year(origination_date)` (partition col) |

### CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PMT_SEQ_NBR` | `legacy_sequence_id` | VARCHAR → STRING | Preserved for audit |
| `LN_ACCT_NBR` | `loan_account_id` | VARCHAR → BIGINT | FK lookup |
| `PMT_DT` | `payment_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `PMT_AMT` | `total_amount` | VARCHAR → DECIMAL(10,2) | Remove commas |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR → DECIMAL(10,2) | Remove commas |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR → DECIMAL(10,2) | Remove commas |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR → DECIMAL(10,2) | Remove commas |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR → DECIMAL(10,2) | Remove commas |
| `PMT_TYP_CD` | `type` | VARCHAR → STRING | Expand code |
| `PMT_STAT_CD` | `status` | VARCHAR → STRING | Expand code |
| `PMT_RECV_DT` | `received_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `PMT_PROC_DT` | `processed_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `PMT_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |
| *(derived)* | `payment_year` | — | `year(payment_date)` (partition col) |

---

## Type Conversion Decisions

### Dates (VARCHAR → DATE / TIMESTAMP)

- **Format**: All legacy dates are stored as `MM/DD/YYYY` strings
- **Parsing**: `to_date(col, 'MM/dd/yyyy')` for DATE, `to_timestamp(col, 'MM/dd/yyyy')` for TIMESTAMP
- **NULL handling**: Unparseable strings become NULL (logged, not dropped)
- **Decision**: `created_at` / `updated_at` use TIMESTAMP (midnight); all others use DATE
- **Rationale**: Audit timestamps should support time-of-day precision in the future, even though legacy only stores date

### Amounts (VARCHAR → DECIMAL)

- **Format**: Legacy amounts contain commas (e.g., `"285,000"`, `"1,487.02"`)
- **Parsing**: `regexp_replace(col, ',', '').cast(DecimalType(p,s))`
- **Precision choices**:
  - Loan amounts: `DECIMAL(12,2)` — supports up to $9,999,999,999.99
  - Payment amounts: `DECIMAL(10,2)` — supports up to $99,999,999.99
  - Interest rates: `DECIMAL(5,3)` — supports rates like 4.750%
  - LTV percent: `DECIMAL(5,2)` — supports up to 999.99%
- **Rationale**: Precision chosen based on reasonable upper bounds for US mortgage data

### Integers (VARCHAR → INT)

- **Fields**: `credit_score`, `term_months`, `delinquency_days`
- **Parsing**: Simple `.cast(IntegerType())`
- **NULL handling**: Non-numeric strings become NULL

### Booleans (VARCHAR → BOOLEAN)

- **Field**: `PROD_STAT_CD` → `is_active`
- **Mapping**: `ACT` → `true`, `INA` → `false`
- **NULL handling**: Unmapped codes become NULL (logged)

---

## Status Code Expansion

### Loan Status (`LN_STAT_CD`)

| Code | Expanded Value |
|------|---------------|
| `ACT` | `Active` |
| `CLO` | `Closed` |
| `DFT` | `Default` |
| `FRB` | `Forbearance` |

### Borrower Status (`BORR_STAT_CD`)

| Code | Expanded Value |
|------|---------------|
| `ACT` | `Active` |
| `INA` | `Inactive` |

### Payment Type (`PMT_TYP_CD`)

| Code | Expanded Value |
|------|---------------|
| `REG` | `Regular` |
| `EXT` | `Extra` |
| `PRT` | `Partial` |
| `PRE` | `Prepayment` |

### Payment Status (`PMT_STAT_CD`)

| Code | Expanded Value |
|------|---------------|
| `PST` | `Posted` |
| `REV` | `Reversed` |
| `NSF` | `NSF` |
| `PND` | `Pending` |

### Property Type (`PROP_TYP_CD`)

| Code | Expanded Value |
|------|---------------|
| `SFR` | `Single Family` |
| `CND` | `Condominium` |
| `MFR` | `Multi-Family` |
| `TWN` | `Townhouse` |

### Product Status (`PROD_STAT_CD`)

| Code | Expanded Value |
|------|---------------|
| `ACT` | `true` (boolean) |
| `INA` | `false` (boolean) |

---

## Partitioning Strategy

| Table | Partition Columns | Rationale |
|-------|-------------------|-----------|
| `borrowers` | `state` | Geographic queries are common in loan ops (state-level reporting, regulatory compliance) |
| `loan_products` | *(none)* | Small reference table (~10-100 rows); partitioning adds overhead |
| `loan_accounts` | `status`, `origination_year` | Most queries filter by loan status (active vs closed); origination year supports time-range analytics |
| `payments` | `payment_year`, `status` | Payment queries are typically time-bounded; status filtering for reconciliation |

### Z-ORDER Recommendations (post-load optimization)

```sql
OPTIMIZE loan_warehouse.borrowers ZORDER BY (external_id, email);
OPTIMIZE loan_warehouse.loan_accounts ZORDER BY (account_number, borrower_id);
OPTIMIZE loan_warehouse.payments ZORDER BY (loan_account_id, payment_date);
```

### Delta Lake Table Properties

All tables use:
- `delta.autoOptimize.optimizeWrite = true` — auto-coalesce small files on write
- `delta.autoOptimize.autoCompact = true` — auto-compact small files

---

## Execution Order

The pipeline must run in this order due to FK dependencies:

```
Step 1: borrowers      (no dependencies)
Step 2: loan_products  (no dependencies)
   ↓ (Steps 1 & 2 can run in parallel)
Step 3: loan_accounts  (depends on borrowers + loan_products for FK resolution)
   ↓
Step 4: payments       (depends on loan_accounts for FK resolution)
   ↓
Step 5: data quality   (depends on all tables being loaded)
```

### DDL Execution Order

```bash
# Run in Databricks SQL or notebook:
databricks/ddl/00_create_database.sql
databricks/ddl/01_borrowers.sql
databricks/ddl/02_loan_products.sql
databricks/ddl/03_loan_accounts.sql
databricks/ddl/04_payments.sql
```

### Ingestion Execution Order

```bash
# Option A: Run individual scripts
spark-submit databricks/ingestion/ingest_borrowers.py --source-path /mnt/legacy/cdw_borr_mstr --source-format csv
spark-submit databricks/ingestion/ingest_loan_products.py --source-path /mnt/legacy/cdw_ln_prod --source-format csv
spark-submit databricks/ingestion/ingest_loan_accounts.py --source-path /mnt/legacy/cdw_ln_acct --source-format csv
spark-submit databricks/ingestion/ingest_payments.py --source-path /mnt/legacy/cdw_pmt_hist --source-format csv

# Option B: Run the orchestrator
spark-submit databricks/ingestion/run_pipeline.py --source-dir /mnt/legacy --source-format csv
```

### Quality Checks

```bash
spark-submit databricks/quality/data_quality_checks.py \
    --source-dir /mnt/legacy \
    --source-format csv \
    --target-db loan_warehouse \
    --report-path /mnt/migration/DATA_QUALITY_REPORT.md
```

---

## Pre-Migration Checklist

- [ ] Legacy data exported to CSV/Parquet in the source directory
- [ ] Source files have headers matching legacy column names
- [ ] Databricks workspace and cluster available
- [ ] Delta Lake database created (`00_create_database.sql`)
- [ ] All four target tables created (DDL scripts 01-04)
- [ ] Source data mount point accessible from cluster (`/mnt/legacy/`)
- [ ] Error output path writable (`/mnt/migration/errors/`)
- [ ] PySpark scripts uploaded to workspace or DBFS

---

## Running the Pipeline

### Step 1: Prepare the Environment

```python
# In a Databricks notebook:
# Verify source data is accessible
dbutils.fs.ls("/mnt/legacy/cdw_borr_mstr")
dbutils.fs.ls("/mnt/legacy/cdw_ln_prod")
dbutils.fs.ls("/mnt/legacy/cdw_ln_acct")
dbutils.fs.ls("/mnt/legacy/cdw_pmt_hist")
```

### Step 2: Create the Database and Tables

Run each DDL script in order via a Databricks SQL notebook or the SQL editor.

### Step 3: Run the Ingestion Pipeline

```python
# Full pipeline (recommended):
%run databricks/ingestion/run_pipeline.py \
    --source-dir /mnt/legacy \
    --source-format csv \
    --target-db loan_warehouse \
    --error-dir /mnt/migration/errors
```

### Step 4: Run Quality Checks

```python
%run databricks/quality/data_quality_checks.py \
    --source-dir /mnt/legacy \
    --source-format csv \
    --target-db loan_warehouse \
    --report-path /mnt/migration/DATA_QUALITY_REPORT.md
```

### Step 5: Review the Quality Report

```python
report = dbutils.fs.head("/mnt/migration/DATA_QUALITY_REPORT.md")
displayHTML(f"<pre>{report}</pre>")
```

---

## Post-Migration Validation

### Quick Validation Queries

```sql
-- Row counts
SELECT 'borrowers' AS tbl, COUNT(*) AS cnt FROM loan_warehouse.borrowers
UNION ALL
SELECT 'loan_products', COUNT(*) FROM loan_warehouse.loan_products
UNION ALL
SELECT 'loan_accounts', COUNT(*) FROM loan_warehouse.loan_accounts
UNION ALL
SELECT 'payments', COUNT(*) FROM loan_warehouse.payments;

-- Verify status expansion
SELECT DISTINCT status FROM loan_warehouse.loan_accounts;
-- Expected: Active, Closed, Default, Forbearance

-- Verify FK integrity
SELECT la.account_number, b.first_name, b.last_name, lp.name AS product
FROM loan_warehouse.loan_accounts la
JOIN loan_warehouse.borrowers b ON la.borrower_id = b.borrower_id
JOIN loan_warehouse.loan_products lp ON la.product_id = lp.product_id;

-- Verify date parsing
SELECT account_number, origination_date, maturity_date
FROM loan_warehouse.loan_accounts
WHERE origination_date IS NOT NULL;

-- Verify amount parsing
SELECT account_number, original_amount, current_balance, monthly_payment
FROM loan_warehouse.loan_accounts;

-- Check for migration errors
SELECT * FROM delta.`/mnt/migration/errors/borrowers`;
SELECT * FROM delta.`/mnt/migration/errors/loan_accounts`;
SELECT * FROM delta.`/mnt/migration/errors/payments`;
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Resolution |
|-------|-------|------------|
| NULL dates after migration | Date string not in `MM/DD/YYYY` format | Check source data; review error records |
| NULL amounts | Amount string has unexpected format | Check for currency symbols, spaces |
| NULL borrower_id in loan_accounts | `BORR_ID` not found in borrowers table | Ensure borrowers loaded first; check error records |
| NULL product_id in loan_accounts | `PROD_CD` not found in loan_products table | Ensure loan_products loaded first |
| NULL loan_account_id in payments | `LN_ACCT_NBR` not found in loan_accounts | Ensure loan_accounts loaded first |
| Row count mismatch | Records failed validation | Check error path for rejected records with `_error_reason` |

### Audit Columns

Every migrated record includes:
- `_migration_source`: Name of the legacy source table
- `_migrated_at`: Timestamp of when the record was migrated

These columns support traceability and can be used to identify records from specific migration runs.

---

## Migration Metadata

| Property | Value |
|----------|-------|
| Source system | Legacy CDW (Corporate Data Warehouse) |
| Source format | All VARCHAR columns |
| Target platform | Databricks / Delta Lake |
| Target database | `loan_warehouse` |
| Tables migrated | 4 (borrowers, loan_products, loan_accounts, payments) |
| Key transformations | Date parsing, amount parsing, status expansion, FK resolution, denormalization removal |
| Error handling | Rejected records written to error path with `_error_reason` |
| Idempotency | Pipeline uses append mode; re-runs require table truncation or MERGE logic |
