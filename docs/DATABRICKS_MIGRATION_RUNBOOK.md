# Databricks Migration Runbook

## CDW Legacy → Delta Lake Migration Pipeline

**Version:** 1.0
**Last Updated:** 2026-05-11
**Source System:** Legacy Corporate Data Warehouse (CDW) — H2/MySQL with all-VARCHAR columns
**Target System:** Databricks Lakehouse — Delta Lake with proper types

---

## Table of Contents

1. [Overview](#overview)
2. [Legacy Schema Summary](#legacy-schema-summary)
3. [Column Mapping Reference](#column-mapping-reference)
4. [Type Conversion Decisions](#type-conversion-decisions)
5. [Status Code Expansions](#status-code-expansions)
6. [Partitioning Strategy](#partitioning-strategy)
7. [Execution Order](#execution-order)
8. [Pre-Migration Checklist](#pre-migration-checklist)
9. [Running the Pipeline](#running-the-pipeline)
10. [Post-Migration Validation](#post-migration-validation)
11. [Troubleshooting](#troubleshooting)
12. [Rollback Procedure](#rollback-procedure)

---

## Overview

This runbook documents the migration of four legacy CDW tables into a normalized Delta Lake schema on Databricks. The legacy schema uses all-VARCHAR columns with cryptic abbreviated names, denormalized structures, string-encoded dates/amounts, and no foreign key constraints.

### Source Tables

| Legacy Table | Description | Row Count (seed) |
|-------------|-------------|------------------|
| `CDW_BORR_MSTR` | Borrower master | 5 |
| `CDW_LN_PROD` | Loan product reference | 5 |
| `CDW_LN_ACCT` | Loan accounts (denormalized) | 5 |
| `CDW_PMT_HIST` | Payment history | 10 |

### Target Tables

| Delta Table | Description | Partition Column |
|------------|-------------|------------------|
| `loan_warehouse.borrowers` | Borrower dimension | `status` |
| `loan_warehouse.loan_products` | Product dimension | *(none — small table)* |
| `loan_warehouse.loan_accounts` | Loan account fact | `origination_year` |
| `loan_warehouse.payments` | Payment fact | `payment_year` |

---

## Legacy Schema Summary

The legacy CDW schema has the following characteristics that necessitate transformation:

1. **All-VARCHAR typing:** Every column is VARCHAR regardless of actual data type. Dates stored as `MM/DD/YYYY` strings, amounts as comma-formatted strings (`"285,000"`), integers as strings.

2. **Cryptic column names:** Abbreviated names like `BORR_FST_NM` (borrower first name), `LN_CURR_BAL` (loan current balance), `PMT_ESCROW_AMT` (payment escrow amount).

3. **Denormalized structures:** `CDW_LN_ACCT` duplicates borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) that already exist in `CDW_BORR_MSTR`.

4. **No foreign keys:** Tables reference each other via string IDs (`BORR_ID`, `LN_ACCT_NBR`) but have no FK constraints.

5. **Status code abbreviations:** `ACT`, `CLO`, `DFT`, `FRB`, `REG`, `PST`, etc. — not self-documenting.

---

## Column Mapping Reference

### CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|--------------|---------------|-------------|----------------|
| `BORR_ID` | `external_id` | VARCHAR → STRING | Direct copy |
| `BORR_FST_NM` | `first_name` | VARCHAR → STRING | Direct copy |
| `BORR_LST_NM` | `last_name` | VARCHAR → STRING | Direct copy |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR → STRING | Direct copy |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR → STRING | Direct copy (re-encrypt recommended) |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR → STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR → STRING | Direct copy |
| `BORR_CTY_NM` | `city` | VARCHAR → STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR → STRING | Direct copy |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR → STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR → STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR → STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR → INT | Cast string to integer |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR → STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR → DECIMAL(12,2) | Remove commas, cast |
| `BORR_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` to midnight timestamp |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` to midnight timestamp |
| `BORR_STAT_CD` | `status` | VARCHAR → STRING | Expand: ACT→Active, INA→Inactive |
| `BORR_REC_TYP` | *(dropped)* | — | Not needed in modern schema |

### CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|--------------|---------------|-------------|----------------|
| `PROD_CD` | `code` | VARCHAR → STRING | Direct copy |
| `PROD_DESC_TXT` | `name` | VARCHAR → STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR → STRING | Direct copy |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | Cast string to integer |
| `PROD_RT_TYP` | `rate_type` | VARCHAR → STRING | Direct copy |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, cast |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, cast |
| `PROD_STAT_CD` | `is_active` | VARCHAR → BOOLEAN | ACT→true, INA→false |
| `PROD_EFF_DT` | `effective_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |

### CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|--------------|---------------|-------------|----------------|
| `LN_ACCT_NBR` | `account_number` | VARCHAR → STRING | Direct copy |
| `BORR_ID` | `borrower_id` | VARCHAR → BIGINT | FK lookup via `borrowers.external_id` |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_id` | VARCHAR → BIGINT | FK lookup via `loan_products.code` |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, cast |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) | Remove commas, cast |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | Cast string to decimal |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | Cast string to integer |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| `LN_ORIG_DT` | `origination_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_MAT_DT` | `maturity_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_STAT_CD` | `status` | VARCHAR → STRING | Expand: ACT→Active, CLO→Closed, DFT→Default, FRB→Forbearance |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | Cast string to integer |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | Cast string to decimal |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR → STRING | Expand: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Remove commas, cast |
| `LN_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `LN_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| *(derived)* | `origination_year` | — | `year(origination_date)` — partition column |

### CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Change | Transformation |
|--------------|---------------|-------------|----------------|
| `PMT_SEQ_NBR` | `legacy_sequence_nbr` | VARCHAR → STRING | Preserved for audit trail |
| `LN_ACCT_NBR` | `loan_account_id` | VARCHAR → BIGINT | FK lookup via `loan_accounts.account_number` |
| `PMT_DT` | `payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_AMT` | `total_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| `PMT_TYP_CD` | `type` | VARCHAR → STRING | Expand: REG→Regular, EXT→Extra, PRT→Partial, PRE→Prepayment |
| `PMT_STAT_CD` | `status` | VARCHAR → STRING | Expand: PST→Posted, REV→Reversed, NSF→NSF, PND→Pending |
| `PMT_RECV_DT` | `received_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_PROC_DT` | `processed_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| *(derived)* | `payment_year` | — | `year(payment_date)` — partition column |

---

## Type Conversion Decisions

### Date Handling
- **Format:** Legacy uses `MM/DD/YYYY` strings consistently across all tables.
- **Target:** `DATE` for business dates (birth, origination, payment), `TIMESTAMP` for audit fields (created_at, updated_at).
- **Rationale:** Audit timestamps use `TIMESTAMP` to allow future precision; `DATE` suffices for business dates.
- **Edge cases:** Unparseable dates become `NULL` and the row is flagged for quarantine review.

### Amount Handling
- **Format:** Legacy stores amounts as comma-formatted strings (e.g., `"285,000"`, `"1,487.02"`).
- **Transformation:** Strip commas via `regexp_replace`, then cast to `DECIMAL`.
- **Precision:** `DECIMAL(12,2)` for large amounts (loan balances, appraisals), `DECIMAL(10,2)` for payment-sized amounts, `DECIMAL(5,3)` for rates, `DECIMAL(5,2)` for percentages.
- **Rationale:** Precision choices match the modern schema in `data/modern-schema/modern_tables.sql`.

### Integer Handling
- **Fields:** Credit score, term months, delinquency days.
- **Transformation:** Direct cast from VARCHAR to `INT`.
- **Edge cases:** Non-numeric values become `NULL`.

### Boolean Handling
- **Field:** `loan_products.is_active` (from `PROD_STAT_CD`).
- **Mapping:** `ACT → true`, `INA → false`. Unknown codes → `NULL`.

---

## Status Code Expansions

All status code expansions are sourced from `data/mappings/column_mappings.md`.

### Borrower Status (`BORR_STAT_CD`)
| Code | Expanded Value |
|------|---------------|
| `ACT` | Active |
| `INA` | Inactive |

### Loan Status (`LN_STAT_CD`)
| Code | Expanded Value |
|------|---------------|
| `ACT` | Active |
| `CLO` | Closed |
| `DFT` | Default |
| `FRB` | Forbearance |

### Property Type (`PROP_TYP_CD`)
| Code | Expanded Value |
|------|---------------|
| `SFR` | Single Family |
| `CND` | Condominium |
| `MFR` | Multi-Family |
| `TWN` | Townhouse |

### Payment Type (`PMT_TYP_CD`)
| Code | Expanded Value |
|------|---------------|
| `REG` | Regular |
| `EXT` | Extra |
| `PRT` | Partial |
| `PRE` | Prepayment |

### Payment Status (`PMT_STAT_CD`)
| Code | Expanded Value |
|------|---------------|
| `PST` | Posted |
| `REV` | Reversed |
| `NSF` | NSF |
| `PND` | Pending |

### Product Status (`PROD_STAT_CD`)
| Code | Boolean Value |
|------|--------------|
| `ACT` | true |
| `INA` | false |

**Unknown codes** are not silently mapped. If a code is not in the mapping, it is preserved with a `_UNKNOWN` suffix (e.g., `XYZ_UNKNOWN`) to ensure it surfaces during quality checks.

---

## Partitioning Strategy

| Table | Partition Column | Rationale |
|-------|-----------------|-----------|
| `borrowers` | `status` | Most queries filter by active/inactive. Low cardinality (2–3 values) keeps partition count manageable. |
| `loan_products` | *(none)* | Small reference table (< 100 rows typically). Partitioning would create excessive small files. |
| `loan_accounts` | `origination_year` | Natural vintage-based partitioning. Loan portfolio queries frequently filter by origination year/range. Cardinality is bounded (decades, not thousands). |
| `payments` | `payment_year` | Time-series fact data. Year-level partitioning enables efficient pruning for monthly/quarterly reporting. |

### Delta Lake Optimizations
All tables use:
- `delta.autoOptimize.optimizeWrite = true` — auto-coalesces small files during write
- `delta.autoOptimize.autoCompact = true` — auto-compacts small files after write
- `delta.columnMapping.mode = name` — allows column renames/drops without rewriting data

---

## Execution Order

The pipeline must execute in dependency order (dimension tables before fact tables):

```
Step 1: CREATE DATABASE loan_warehouse (if not exists)

Step 2: Run DDL scripts in order:
  ├── 01_borrowers.sql        (no dependencies)
  ├── 02_loan_products.sql    (no dependencies)
  ├── 03_loan_accounts.sql    (references borrowers, loan_products)
  └── 04_payments.sql         (references loan_accounts)

Step 3: Run ingestion scripts in order:
  ├── ingest_borrowers.py     (no dependencies)
  ├── ingest_loan_products.py (no dependencies)
  ├── ingest_loan_accounts.py (depends on borrowers + loan_products)
  └── ingest_payments.py      (depends on loan_accounts)

Step 4: Run quality checks:
  └── run_quality_checks.py   (reads all 4 target tables)
```

**Note:** Steps 2a/2b (borrowers/loan_products DDL) and 3a/3b (borrowers/loan_products ingestion) can run in parallel since they have no interdependencies.

---

## Pre-Migration Checklist

- [ ] **Export legacy data:** Export `CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST` to CSV or Parquet files.
- [ ] **Upload to DBFS/Volume:** Place exports at the paths configured in `config.py` (`SOURCE_PATHS`).
- [ ] **Verify source file headers:** CSV files must have column headers matching the legacy schema definitions.
- [ ] **Create Databricks cluster:** Ensure cluster has PySpark and Delta Lake libraries.
- [ ] **Update config.py paths:** Set `SOURCE_PATHS` to match your actual DBFS mount points or Unity Catalog volumes.
- [ ] **Review status code mappings:** Confirm the expansion values in `config.py` match your business requirements.
- [ ] **Take a snapshot:** If migrating a production dataset, back up existing Delta tables first.

---

## Running the Pipeline

### Option A: Full Pipeline (Recommended)

Run the orchestrator script which handles dependency ordering automatically:

```python
# In a Databricks notebook:
%run ./databricks/ingestion/run_ingestion

# Or via databricks CLI:
databricks jobs create --json '{
  "name": "CDW_Migration_Pipeline",
  "tasks": [{
    "task_key": "full_pipeline",
    "spark_python_task": {
      "python_file": "dbfs:/path/to/databricks/ingestion/run_ingestion.py"
    }
  }]
}'
```

### Option B: Step-by-Step

```sql
-- Step 1: Create database
CREATE DATABASE IF NOT EXISTS loan_warehouse;

-- Step 2: Run DDL (in a SQL notebook or via Databricks SQL)
-- Execute each file in databricks/ddl/ in numerical order
```

```python
# Step 3: Run ingestion scripts individually
from ingest_borrowers import ingest_borrowers
from ingest_loan_products import ingest_loan_products
from ingest_loan_accounts import ingest_loan_accounts
from ingest_payments import ingest_payments

borrower_result = ingest_borrowers(spark)
product_result = ingest_loan_products(spark)
loan_result = ingest_loan_accounts(spark)       # Must run after borrowers + products
payment_result = ingest_payments(spark)          # Must run after loan_accounts
```

```python
# Step 4: Run quality checks
from validation import run_all_checks

source_counts = {
    "borrowers": borrower_result,
    "loan_products": product_result,
    "loan_accounts": loan_result,
    "payments": payment_result,
}

report = run_all_checks(spark, source_counts=source_counts,
                        output_path="/dbfs/reports/DATA_QUALITY_REPORT.md")
```

---

## Post-Migration Validation

After the pipeline completes, review the following:

1. **DATA_QUALITY_REPORT.md** — Check for any FAIL results across all four categories.
2. **Row count reconciliation** — Verify `source = target + quarantine` for each table.
3. **Quarantine table** — Review `loan_warehouse._quarantine` for any flagged records. Investigate and manually remediate if needed.
4. **Sample spot checks** — Query a few records and compare against legacy source:

```sql
-- Verify borrower transformation
SELECT external_id, first_name, last_name, date_of_birth, annual_income, status
FROM loan_warehouse.borrowers
WHERE external_id = 'B-10001';
-- Expected: James Mitchell, 1978-03-15, 92500.00, Active

-- Verify loan account FK resolution and status expansion
SELECT account_number, borrower_id, product_id, status, origination_year
FROM loan_warehouse.loan_accounts
WHERE account_number = 'LN-2019-00142';
-- Expected: status=Active, origination_year=2019, valid borrower_id and product_id

-- Verify payment amount parsing and type expansion
SELECT legacy_sequence_nbr, total_amount, type, status, payment_year
FROM loan_warehouse.payments
WHERE legacy_sequence_nbr = 'PMT-2025120001';
-- Expected: 1487.02, Regular, Posted, 2025
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Resolution |
|-------|-------|------------|
| `NULL` dates after transformation | Date string not in `MM/DD/YYYY` format | Check source data for inconsistent date formats. Update `LEGACY_DATE_FORMAT` in config if needed. |
| `NULL` amounts after transformation | Amount string has unexpected characters | Check for currency symbols ($), spaces, or non-standard separators in source data. |
| Orphan FK references | Loan references borrower not in dimension table | Run borrowers ingestion first. Check quarantine table for rejected borrowers. |
| `_UNKNOWN` suffix in status fields | Legacy code not in mapping dictionary | Add the new code to the appropriate map in `config.py`. |
| Small file problem | Many small partitions | Run `OPTIMIZE loan_warehouse.<table>` to compact files. Auto-optimize is enabled but may not compact immediately. |

### Quarantine Investigation

```sql
-- View quarantine records by source table
SELECT _etl_source, _quarantine_reason, count(*) as cnt
FROM loan_warehouse._quarantine
GROUP BY _etl_source, _quarantine_reason;
```

---

## Rollback Procedure

Delta Lake supports time travel, making rollback straightforward:

```sql
-- Check table history
DESCRIBE HISTORY loan_warehouse.borrowers;

-- Restore to a previous version
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF <version_number>;

-- Or restore to a timestamp
RESTORE TABLE loan_warehouse.borrowers TO TIMESTAMP AS OF '2026-05-10T00:00:00';
```

To completely remove the migrated data:

```sql
DROP TABLE IF EXISTS loan_warehouse.payments;
DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
DROP TABLE IF EXISTS loan_warehouse.loan_products;
DROP TABLE IF EXISTS loan_warehouse.borrowers;
DROP TABLE IF EXISTS loan_warehouse._quarantine;
-- Drop in reverse dependency order
```

---

## Appendix: ETL Metadata Columns

Every target table includes two ETL lineage columns:

| Column | Type | Description |
|--------|------|-------------|
| `_etl_loaded_at` | TIMESTAMP | When the record was loaded into Delta Lake |
| `_etl_source` | STRING | Legacy source table name (e.g., `CDW_BORR_MSTR`) |

These columns support lineage tracking and debugging. They are not part of the business schema.
