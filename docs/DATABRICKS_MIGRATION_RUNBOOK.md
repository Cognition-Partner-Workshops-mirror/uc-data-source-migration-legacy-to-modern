# Databricks Migration Runbook

## Overview

This runbook documents the end-to-end migration of the legacy CDW (Corporate Data Warehouse) loan management data into a modern Delta Lake schema on Databricks. It covers every transformation decision, column mapping, type conversion, partitioning rationale, and the recommended execution order.

---

## 1. Source System Summary

The legacy CDW system stores loan management data across four tables:

| Legacy Table | Description | Row Count (Seed) |
|---|---|---|
| `CDW_BORR_MSTR` | Borrower master records | 5 |
| `CDW_LN_PROD` | Loan product definitions | 5 |
| `CDW_LN_ACCT` | Loan accounts (denormalized with borrower data) | 5 |
| `CDW_PMT_HIST` | Payment transaction history | 10 |

### Legacy Schema Characteristics

- **All-VARCHAR columns**: Every column is stored as `VARCHAR`, including dates, amounts, and integers.
- **Cryptic column names**: Abbreviated naming convention (e.g., `BORR_FST_NM` for borrower first name, `LN_CURR_BAL` for loan current balance).
- **Denormalized structure**: `CDW_LN_ACCT` embeds borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) that duplicate `CDW_BORR_MSTR`.
- **No foreign keys**: No referential integrity constraints exist between tables.
- **Status code abbreviations**: Short codes like `ACT`, `CLO`, `DFT`, `FRB` instead of readable values.
- **String-encoded dates**: All dates stored as `MM/DD/YYYY` strings.
- **String-encoded amounts**: Monetary values stored with commas (e.g., `"285,000"`, `"271,432.56"`).

---

## 2. Target Schema (Delta Lake)

### 2.1 Schema: `loan_warehouse`

All target tables reside in the `loan_warehouse` schema (Databricks database).

### 2.2 Target Tables

| Target Table | Source Table | Description |
|---|---|---|
| `loan_warehouse.borrowers` | `CDW_BORR_MSTR` | Normalized borrower dimension |
| `loan_warehouse.loan_products` | `CDW_LN_PROD` | Loan product reference data |
| `loan_warehouse.loan_accounts` | `CDW_LN_ACCT` | Loan account facts (denormalized fields removed) |
| `loan_warehouse.payments` | `CDW_PMT_HIST` | Payment transaction history |

### 2.3 Partitioning Strategy

| Table | Partition Column(s) | Rationale |
|---|---|---|
| `borrowers` | `status` | Queries frequently filter by active/inactive status; low cardinality keeps partition count manageable |
| `loan_products` | *(none)* | Very small reference table (~tens of rows); partitioning would add overhead with no benefit |
| `loan_accounts` | `origination_year` | Loan vintage analysis is a common query pattern; year-based partitioning balances partition size and query pruning |
| `payments` | `payment_year`, `payment_month` | Time-range queries on payment history are the primary access pattern; year+month gives good pruning without excessive partitions |

### 2.4 Delta Lake Properties

All tables use:
- `delta.autoOptimize.optimizeWrite = true` — coalesces small files during writes
- `delta.autoOptimize.autoCompact = true` — triggers automatic compaction
- `delta.columnMapping.mode = name` — enables column rename/drop without rewriting data

---

## 3. Column Mapping Reference

### 3.1 CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `BORR_ID` | `external_id` | VARCHAR → STRING | Direct copy; used as business key |
| `BORR_FST_NM` | `first_name` | VARCHAR → STRING | Direct copy |
| `BORR_LST_NM` | `last_name` | VARCHAR → STRING | Direct copy |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR → STRING | Direct copy |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR → STRING | Direct copy (re-encryption recommended in production) |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR → DATE | Parse `MM/DD/YYYY` string to `DateType` |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR → STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR → STRING | Direct copy; nullable |
| `BORR_CTY_NM` | `city` | VARCHAR → STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR → STRING | Direct copy (2-char state code) |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR → STRING | Direct copy (kept as string to preserve leading zeros) |
| `BORR_PH_NBR` | `phone` | VARCHAR → STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR → STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR → INT | Parse numeric string to integer |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR → STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR → DECIMAL(12,2) | Remove commas, parse to decimal |
| `BORR_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` to timestamp (midnight) |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` to timestamp (midnight) |
| `BORR_STAT_CD` | `status` | VARCHAR → STRING | Expand: `ACT` → `ACTIVE`, `INA` → `INACTIVE` |
| `BORR_REC_TYP` | *(dropped)* | — | Record type indicator not needed in modern schema |

### 3.2 CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `PROD_CD` | `code` | VARCHAR → STRING | Direct copy; used as business key |
| `PROD_DESC_TXT` | `name` | VARCHAR → STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR → STRING | Direct copy (FXD, ARM, FHA, VA) |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | Parse numeric string to integer |
| `PROD_RT_TYP` | `rate_type` | VARCHAR → STRING | Direct copy (FIXED, VARIABLE) |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse to decimal |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse to decimal |
| `PROD_STAT_CD` | `is_active` | VARCHAR → BOOLEAN | `ACT` → `true`, `INA` → `false` |
| `PROD_EFF_DT` | `effective_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` to date |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` to date |

### 3.3 CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `LN_ACCT_NBR` | `account_number` | VARCHAR → STRING | Direct copy; used as business key |
| `BORR_ID` | `borrower_external_id` | VARCHAR → STRING | FK to `borrowers.external_id` |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK instead |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK instead |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK instead |
| `PROD_CD` | `product_code` | VARCHAR → STRING | FK to `loan_products.code` |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse to decimal |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) | Remove commas, parse to decimal |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | Parse string like `"5.250"` to decimal |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | Parse numeric string to integer |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) | Remove commas, parse to decimal |
| `LN_ORIG_DT` | `origination_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` to date |
| `LN_MAT_DT` | `maturity_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` to date |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` to date |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` to date |
| `LN_STAT_CD` | `status` | VARCHAR → STRING | Expand: `ACT` → `ACTIVE`, `CLO` → `CLOSED`, `DFT` → `DEFAULT`, `FRB` → `FORBEARANCE` |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | Parse numeric string to integer |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Remove commas, parse to decimal |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | Parse string like `"82.5"` to decimal |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR → STRING | Expand: `SFR` → `Single Family`, `CND` → `Condominium`, `MFR` → `Multi-Family`, `TWN` → `Townhouse` |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Remove commas, parse to decimal |
| `LN_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` to timestamp |
| `LN_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` to timestamp |
| *(derived)* | `origination_year` | — | `year(origination_date)`; used as partition column |

### 3.4 CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `PMT_SEQ_NBR` | `legacy_payment_seq` | VARCHAR → STRING | Preserved for audit traceability |
| `LN_ACCT_NBR` | `loan_account_number` | VARCHAR → STRING | FK to `loan_accounts.account_number` |
| `PMT_DT` | `payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` to date |
| `PMT_AMT` | `total_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse to decimal |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse to decimal |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse to decimal |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse to decimal |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR → DECIMAL(10,2) | Remove commas, parse to decimal |
| `PMT_TYP_CD` | `type` | VARCHAR → STRING | Expand: `REG` → `REGULAR`, `EXT` → `EXTRA`, `PRT` → `PARTIAL`, `PRE` → `PREPAYMENT` |
| `PMT_STAT_CD` | `status` | VARCHAR → STRING | Expand: `PST` → `POSTED`, `REV` → `REVERSED`, `NSF` → `NSF`, `PND` → `PENDING` |
| `PMT_RECV_DT` | `received_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` to date |
| `PMT_PROC_DT` | `processed_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` to date |
| `PMT_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` to timestamp |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` to timestamp |
| *(derived)* | `payment_year` | — | `year(payment_date)`; partition column |
| *(derived)* | `payment_month` | — | `month(payment_date)`; partition column |

---

## 4. Transformation Decisions

### 4.1 Date Handling

**Decision:** Use `to_date(col, "MM/dd/yyyy")` and `to_timestamp(col, "MM/dd/yyyy")`.

- Legacy dates are consistently formatted as `MM/DD/YYYY` strings.
- Timestamps are derived from date-only strings and default to midnight (`00:00:00`).
- Malformed or NULL date strings produce NULL in the target — they are logged but not dropped.

### 4.2 Amount / Numeric Parsing

**Decision:** Strip commas with `regexp_replace(col, ",", "")` then cast to `DecimalType`.

- Legacy amounts include commas as thousands separators (e.g., `"285,000"`, `"271,432.56"`).
- After comma removal, standard Spark decimal casting handles the conversion.
- Precision and scale are chosen per-column based on business domain requirements:
  - Loan amounts: `DECIMAL(12,2)` — supports up to $9,999,999,999.99
  - Payment amounts: `DECIMAL(10,2)` — supports up to $99,999,999.99
  - Interest rates: `DECIMAL(5,3)` — supports rates like `5.250%`
  - LTV percent: `DECIMAL(5,2)` — supports percentages like `82.50`

### 4.3 Status Code Expansion

**Decision:** Use PySpark map lookups to expand abbreviations to readable values.

| Domain | Code | Expanded Value |
|---|---|---|
| Borrower Status | `ACT` | `ACTIVE` |
| Borrower Status | `INA` | `INACTIVE` |
| Loan Status | `ACT` | `ACTIVE` |
| Loan Status | `CLO` | `CLOSED` |
| Loan Status | `DFT` | `DEFAULT` |
| Loan Status | `FRB` | `FORBEARANCE` |
| Payment Type | `REG` | `REGULAR` |
| Payment Type | `EXT` | `EXTRA` |
| Payment Type | `PRT` | `PARTIAL` |
| Payment Type | `PRE` | `PREPAYMENT` |
| Payment Status | `PST` | `POSTED` |
| Payment Status | `REV` | `REVERSED` |
| Payment Status | `NSF` | `NSF` |
| Payment Status | `PND` | `PENDING` |
| Product Status | `ACT` | `true` (boolean) |
| Product Status | `INA` | `false` (boolean) |
| Property Type | `SFR` | `Single Family` |
| Property Type | `CND` | `Condominium` |
| Property Type | `MFR` | `Multi-Family` |
| Property Type | `TWN` | `Townhouse` |

Unmapped codes are preserved as-is and logged as warnings.

### 4.4 Denormalization Removal

**Decision:** Drop `BORR_FST_NM`, `BORR_LST_NM`, and `BORR_SSN_LST4` from `CDW_LN_ACCT`.

- These fields duplicate data from `CDW_BORR_MSTR` and are unnecessary in a normalized schema.
- The `BORR_ID` field is retained as `borrower_external_id` to serve as the FK join key.
- The `PROD_CD` field is retained as `product_code` for FK joins to `loan_products`.

### 4.5 ID Strategy

**Decision:** Use Delta Lake `GENERATED ALWAYS AS IDENTITY` for surrogate keys, retain legacy IDs as business keys.

- Each table has an auto-generated `BIGINT` identity column as its primary key.
- Legacy IDs (e.g., `B-10001`, `LN-2019-00142`) are preserved in dedicated columns for traceability.
- FK relationships use business keys (e.g., `borrower_external_id`, `product_code`, `loan_account_number`) rather than surrogate IDs. This simplifies the migration by avoiding ID lookup joins during ingestion.

### 4.6 Migration Metadata

**Decision:** Add `_migration_source` and `_migrated_at` columns to all target tables.

- `_migration_source`: Name of the legacy source table (e.g., `CDW_BORR_MSTR`).
- `_migrated_at`: Timestamp of when the row was ingested.
- These columns support audit and lineage tracking.

### 4.7 Null / Malformed Value Handling

**Decision:** Never silently drop records. Use a quarantine pattern.

- Each ingestion script validates required fields after transformation.
- Rows with NULL in required columns are separated into a quarantine DataFrame.
- Quarantined row counts and details are logged at WARNING level.
- The `log_row_counts()` function reports source vs. target reconciliation for every table.

---

## 5. Execution Order

Run the migration steps in the following order on Databricks:

### Step 0: Create Schema

```sql
-- Run: databricks/ddl/00_create_schema.sql
CREATE SCHEMA IF NOT EXISTS loan_warehouse ...
```

### Step 1: Create Target Tables

Run DDL scripts in order:

```
databricks/ddl/01_borrowers.sql
databricks/ddl/02_loan_products.sql
databricks/ddl/03_loan_accounts.sql
databricks/ddl/04_payments.sql
```

### Step 2: Export Legacy Data

Export legacy tables to CSV or Parquet files in a landing zone:

```
/mnt/landing/cdw_export/
  CDW_BORR_MSTR/
    part-00000.csv
  CDW_LN_PROD/
    part-00000.csv
  CDW_LN_ACCT/
    part-00000.csv
  CDW_PMT_HIST/
    part-00000.csv
```

### Step 3: Run Ingestion Pipeline

```python
# In a Databricks notebook:
from databricks.ingestion.run_pipeline import run_pipeline

results = run_pipeline(
    source_dir="/mnt/landing/cdw_export/",
    source_format="csv",
    write_mode="overwrite"
)
```

Or via `spark-submit`:

```bash
spark-submit \
  --py-files databricks/ingestion/*.py \
  databricks/ingestion/run_pipeline.py \
  --source-dir /mnt/landing/cdw_export/ \
  --source-format csv \
  --write-mode overwrite
```

**Ingestion order (enforced by the pipeline orchestrator):**
1. `borrowers` — no dependencies
2. `loan_products` — no dependencies
3. `loan_accounts` — references borrowers and loan_products
4. `payments` — references loan_accounts

### Step 4: Run Data Quality Checks

```python
from databricks.quality.generate_report import run_and_report

source_counts = {
    "loan_warehouse.borrowers": 5,
    "loan_warehouse.loan_products": 5,
    "loan_warehouse.loan_accounts": 5,
    "loan_warehouse.payments": 10,
}

report = run_and_report(
    spark,
    source_counts=source_counts,
    output_path="/dbfs/reports/DATA_QUALITY_REPORT.md"
)

# Check results
print(f"Passed: {report.passed}, Failed: {report.failed}")
```

### Step 5: Review Quality Report

Review the generated `DATA_QUALITY_REPORT.md` for:
- Row count reconciliation (source vs. target)
- Null violations on required fields
- Referential integrity between tables
- Business rule violations
- Status code validation

### Step 6: Sign-Off

If all quality checks pass:
1. Move the pipeline to a scheduled Databricks job for incremental loads
2. Update downstream consumers to read from `loan_warehouse.*` tables
3. Decommission the legacy CDW read path

---

## 6. Data Quality Checks

The quality framework (`databricks/quality/`) runs the following checks:

| # | Category | Check | Description |
|---|---|---|---|
| 1 | Row Count | `row_count_reconciliation` | Source row count matches target row count |
| 2 | Null Check | `not_null_{column}` | Required columns have no NULL values |
| 3 | Referential Integrity | `fk_borrower_external_id` | All loan borrower IDs exist in borrowers table |
| 4 | Referential Integrity | `fk_product_code` | All loan product codes exist in loan_products table |
| 5 | Referential Integrity | `fk_loan_account_number` | All payment loan account numbers exist in loan_accounts |
| 6 | Business Rule | `active_loan_positive_balance` | Active loans must have current_balance > 0 |
| 7 | Business Rule | `origination_before_maturity` | Origination date must precede maturity date |
| 8 | Business Rule | `interest_rate_range` | Interest rates between 0% and 100% |
| 9 | Business Rule | `ltv_percent_range` | LTV between 0% and 200% |
| 10 | Business Rule | `delinquency_days_nonneg` | Delinquency days >= 0 |
| 11 | Business Rule | `payment_amount_positive` | Payment total_amount > 0 |
| 12 | Business Rule | `received_before_processed` | Payment received_date <= processed_date |
| 13 | Business Rule | `payment_components_sum` | Principal + interest + escrow + late_fee ≈ total_amount |
| 14 | Business Rule | `credit_score_range` | Borrower credit scores between 300 and 850 |
| 15 | Business Rule | `annual_income_nonneg` | Borrower annual income >= 0 |
| 16 | Status Validation | `valid_{col}_values` | All expanded status/type values are in the expected domain |

---

## 7. Rollback Procedure

Delta Lake supports time travel. If a migration run produces incorrect data:

```sql
-- View table history
DESCRIBE HISTORY loan_warehouse.loan_accounts;

-- Restore to a previous version
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF <version_number>;

-- Or restore to a point in time
RESTORE TABLE loan_warehouse.loan_accounts TO TIMESTAMP AS OF '2026-01-15T00:00:00';
```

To completely start over:

```sql
DROP TABLE IF EXISTS loan_warehouse.payments;
DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
DROP TABLE IF EXISTS loan_warehouse.loan_products;
DROP TABLE IF EXISTS loan_warehouse.borrowers;
DROP SCHEMA IF EXISTS loan_warehouse CASCADE;
```

Then re-run from Step 0.

---

## 8. File Inventory

| Path | Description |
|---|---|
| `databricks/ddl/00_create_schema.sql` | Schema creation DDL |
| `databricks/ddl/01_borrowers.sql` | Borrowers Delta Lake table DDL |
| `databricks/ddl/02_loan_products.sql` | Loan products Delta Lake table DDL |
| `databricks/ddl/03_loan_accounts.sql` | Loan accounts Delta Lake table DDL |
| `databricks/ddl/04_payments.sql` | Payments Delta Lake table DDL |
| `databricks/ingestion/__init__.py` | Package init |
| `databricks/ingestion/transforms.py` | Shared transformation utilities and UDFs |
| `databricks/ingestion/ingest_borrowers.py` | Borrower ingestion ETL |
| `databricks/ingestion/ingest_loan_products.py` | Loan product ingestion ETL |
| `databricks/ingestion/ingest_loan_accounts.py` | Loan account ingestion ETL |
| `databricks/ingestion/ingest_payments.py` | Payment ingestion ETL |
| `databricks/ingestion/run_pipeline.py` | Pipeline orchestrator |
| `databricks/quality/__init__.py` | Package init |
| `databricks/quality/data_quality_checks.py` | Data quality check framework |
| `databricks/quality/generate_report.py` | Report generator (produces DATA_QUALITY_REPORT.md) |
| `docs/DATABRICKS_MIGRATION_RUNBOOK.md` | This document |
