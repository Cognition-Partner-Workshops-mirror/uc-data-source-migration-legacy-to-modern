# Databricks Migration Runbook

## Overview

This runbook documents the end-to-end migration of the loan management application's legacy CDW (Corporate Data Warehouse) tables to a modern Delta Lake schema on Databricks. It covers every transformation decision, column mapping, type conversion, partitioning rationale, and the recommended execution order.

---

## 1. Source System Analysis

### Legacy Schema Characteristics

The legacy CDW schema (`src/main/resources/schema-legacy.sql`) has the following issues:

| Issue | Description |
|-------|-------------|
| **All-VARCHAR typing** | Every column — dates, amounts, integers — is stored as `VARCHAR`. |
| **Cryptic column names** | Abbreviated names like `BORR_FST_NM`, `LN_CURR_BAL`, `PMT_ESCROW_AMT`. |
| **Denormalized structure** | `CDW_LN_ACCT` duplicates borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`). |
| **No foreign keys** | No referential integrity constraints between tables. |
| **Status abbreviations** | Codes like `ACT`, `CLO`, `DFT`, `FRB` instead of readable labels. |
| **String-encoded dates** | Dates stored as `MM/DD/YYYY` strings. |
| **String-encoded amounts** | Amounts stored with commas: `"285,000"`, `"271,432.56"`. |

### Legacy Tables

| Legacy Table | Row Count | Description |
|-------------|-----------|-------------|
| `CDW_BORR_MSTR` | 5 | Borrower master records |
| `CDW_LN_PROD` | 5 | Loan product definitions |
| `CDW_LN_ACCT` | 5 | Loan accounts (denormalized with borrower data) |
| `CDW_PMT_HIST` | 10 | Payment history |

---

## 2. Target Schema Design

### Design Principles

1. **Proper data types** — `DATE`, `DECIMAL`, `INT`, `BOOLEAN`, `TIMESTAMP` replace `VARCHAR`.
2. **Meaningful names** — `BORR_FST_NM` → `first_name`, `LN_CURR_BAL` → `current_balance`.
3. **Normalized structure** — Borrower data lives only in `borrowers`; `loan_accounts` references it via FK.
4. **Referential integrity** — Foreign keys between `loan_accounts` → `borrowers`, `loan_accounts` → `loan_products`, `payments` → `loan_accounts`.
5. **Audit columns** — `_migration_ts` and `_source_system` on every table for lineage tracking.

### Target Tables

| Target Table | Delta Location | Partition Column | Rationale |
|-------------|---------------|-----------------|-----------|
| `loan_warehouse.borrowers` | `loan_warehouse.borrowers` | `state` | Regional query patterns; low-cardinality (~50 values). |
| `loan_warehouse.loan_products` | `loan_warehouse.loan_products` | *(none)* | Small reference table (~10s of rows); partitioning adds overhead. |
| `loan_warehouse.loan_accounts` | `loan_warehouse.loan_accounts` | `status` | Most queries filter by Active/Closed/Default; 4-value partition. |
| `loan_warehouse.payments` | `loan_warehouse.payments` | `payment_year` | Time-range queries on payment history; year-level granularity balances partition count vs. file size. |

### Partitioning Rationale

- **`borrowers` by `state`**: Supports common filtering by geography (e.g., state-level regulatory reporting). ~50 partitions is within Databricks best practices.
- **`loan_accounts` by `status`**: Active/Closed/Default/Forbearance gives 4 partitions. Queries almost always filter by status (e.g., "show all active loans").
- **`payments` by `payment_year`**: Payment history grows over time. Year partitioning enables efficient time-range scans and Z-ORDER within partitions by `loan_account_id`.
- **`loan_products`**: Not partitioned — small reference table that benefits from a single Delta file for broadcast joins.

---

## 3. Column Mappings

### 3.1 CDW_BORR_MSTR → borrowers

| Legacy Column | Legacy Type | Target Column | Target Type | Transformation |
|---------------|-------------|---------------|-------------|----------------|
| `BORR_ID` | VARCHAR(20) | `external_id` | STRING | Direct copy |
| `BORR_FST_NM` | VARCHAR(50) | `first_name` | STRING | Direct copy |
| `BORR_LST_NM` | VARCHAR(50) | `last_name` | STRING | Direct copy |
| `BORR_MID_INIT` | VARCHAR(1) | `middle_initial` | STRING | Direct copy |
| `BORR_SSN_ENCR` | VARCHAR(100) | `ssn_hash` | STRING | Direct copy (re-encryption recommended) |
| `BORR_DOB_DT` | VARCHAR(10) | `date_of_birth` | DATE | Parse `MM/DD/YYYY` → `DateType` |
| `BORR_ADDR_LN1` | VARCHAR(100) | `address_line1` | STRING | Direct copy |
| `BORR_ADDR_LN2` | VARCHAR(100) | `address_line2` | STRING | Direct copy |
| `BORR_CTY_NM` | VARCHAR(50) | `city` | STRING | Direct copy |
| `BORR_ST_CD` | VARCHAR(2) | `state` | STRING | Direct copy |
| `BORR_ZIP_CD` | VARCHAR(10) | `zip_code` | STRING | Direct copy |
| `BORR_PH_NBR` | VARCHAR(15) | `phone` | STRING | Direct copy |
| `BORR_EMAIL_ADDR` | VARCHAR(100) | `email` | STRING | Direct copy |
| `BORR_CRDT_SCR` | VARCHAR(5) | `credit_score` | INT | Parse string → integer |
| `BORR_EMP_STAT` | VARCHAR(20) | `employment_status` | STRING | Direct copy |
| `BORR_ANN_INCM` | VARCHAR(15) | `annual_income` | DECIMAL(12,2) | Remove commas, parse → decimal |
| `BORR_CRET_DT` | VARCHAR(10) | `created_at` | TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |
| `BORR_UPDT_DT` | VARCHAR(10) | `updated_at` | TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |
| `BORR_STAT_CD` | VARCHAR(5) | `status` | STRING | Expand: `ACT`→`Active`, `INA`→`Inactive` |
| `BORR_REC_TYP` | VARCHAR(10) | *(dropped)* | — | Not needed in modern schema |

### 3.2 CDW_LN_PROD → loan_products

| Legacy Column | Legacy Type | Target Column | Target Type | Transformation |
|---------------|-------------|---------------|-------------|----------------|
| `PROD_CD` | VARCHAR(10) | `code` | STRING | Direct copy |
| `PROD_DESC_TXT` | VARCHAR(200) | `name` | STRING | Direct copy |
| `PROD_TYP_CD` | VARCHAR(5) | `type` | STRING | Direct copy |
| `PROD_TERM_MOS` | VARCHAR(5) | `term_months` | INT | Parse string → integer |
| `PROD_RT_TYP` | VARCHAR(10) | `rate_type` | STRING | Direct copy |
| `PROD_MIN_AMT` | VARCHAR(15) | `min_amount` | DECIMAL(12,2) | Remove commas, parse → decimal |
| `PROD_MAX_AMT` | VARCHAR(15) | `max_amount` | DECIMAL(12,2) | Remove commas, parse → decimal |
| `PROD_STAT_CD` | VARCHAR(5) | `is_active` | BOOLEAN | `ACT`→`true`, `INA`→`false` |
| `PROD_EFF_DT` | VARCHAR(10) | `effective_date` | DATE | Parse `MM/DD/YYYY` → date |
| `PROD_EXP_DT` | VARCHAR(10) | `expiration_date` | DATE | Parse `MM/DD/YYYY` → date |

### 3.3 CDW_LN_ACCT → loan_accounts

| Legacy Column | Legacy Type | Target Column | Target Type | Transformation |
|---------------|-------------|---------------|-------------|----------------|
| `LN_ACCT_NBR` | VARCHAR(20) | `account_number` | STRING | Direct copy |
| `BORR_ID` | VARCHAR(20) | `borrower_id` | BIGINT | FK lookup: `borrowers.borrower_id` where `external_id` = `BORR_ID` |
| `BORR_FST_NM` | VARCHAR(50) | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | VARCHAR(50) | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | VARCHAR(10) | `product_id` | BIGINT | FK lookup: `loan_products.product_id` where `code` = `PROD_CD` |
| `LN_ORIG_AMT` | VARCHAR(15) | `original_amount` | DECIMAL(12,2) | Remove commas, parse → decimal |
| `LN_CURR_BAL` | VARCHAR(15) | `current_balance` | DECIMAL(12,2) | Remove commas, parse → decimal |
| `LN_INT_RT` | VARCHAR(8) | `interest_rate` | DECIMAL(5,3) | Parse string → decimal |
| `LN_TERM_MOS` | VARCHAR(5) | `term_months` | INT | Parse string → integer |
| `LN_PMT_AMT` | VARCHAR(15) | `monthly_payment` | DECIMAL(10,2) | Remove commas, parse → decimal |
| `LN_ORIG_DT` | VARCHAR(10) | `origination_date` | DATE | Parse `MM/DD/YYYY` → date |
| `LN_MAT_DT` | VARCHAR(10) | `maturity_date` | DATE | Parse `MM/DD/YYYY` → date |
| `LN_1ST_PMT_DT` | VARCHAR(10) | `first_payment_date` | DATE | Parse `MM/DD/YYYY` → date |
| `LN_NXT_PMT_DT` | VARCHAR(10) | `next_payment_date` | DATE | Parse `MM/DD/YYYY` → date |
| `LN_STAT_CD` | VARCHAR(5) | `status` | STRING | Expand: `ACT`→`Active`, `CLO`→`Closed`, `DFT`→`Default`, `FRB`→`Forbearance` |
| `LN_DLQ_DAYS` | VARCHAR(5) | `delinquency_days` | INT | Parse string → integer |
| `LN_ESCROW_BAL` | VARCHAR(15) | `escrow_balance` | DECIMAL(10,2) | Remove commas, parse → decimal |
| `LN_LTV_PCT` | VARCHAR(8) | `ltv_percent` | DECIMAL(5,2) | Parse string → decimal |
| `PROP_ADDR_LN1` | VARCHAR(100) | `property_address` | STRING | Direct copy |
| `PROP_CTY_NM` | VARCHAR(50) | `property_city` | STRING | Direct copy |
| `PROP_ST_CD` | VARCHAR(2) | `property_state` | STRING | Direct copy |
| `PROP_ZIP_CD` | VARCHAR(10) | `property_zip` | STRING | Direct copy |
| `PROP_TYP_CD` | VARCHAR(10) | `property_type` | STRING | Expand: `SFR`→`Single Family`, `CND`→`Condominium`, `MFR`→`Multi-Family`, `TWN`→`Townhouse` |
| `PROP_APRS_VAL` | VARCHAR(15) | `appraised_value` | DECIMAL(12,2) | Remove commas, parse → decimal |
| `LN_CRET_DT` | VARCHAR(10) | `created_at` | TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |
| `LN_UPDT_DT` | VARCHAR(10) | `updated_at` | TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |

### 3.4 CDW_PMT_HIST → payments

| Legacy Column | Legacy Type | Target Column | Target Type | Transformation |
|---------------|-------------|---------------|-------------|----------------|
| `PMT_SEQ_NBR` | VARCHAR(20) | `legacy_sequence_nbr` | STRING | Preserved for audit trail |
| `LN_ACCT_NBR` | VARCHAR(20) | `loan_account_id` | BIGINT | FK lookup: `loan_accounts.loan_account_id` where `account_number` = `LN_ACCT_NBR` |
| `PMT_DT` | VARCHAR(10) | `payment_date` | DATE | Parse `MM/DD/YYYY` → date |
| `PMT_AMT` | VARCHAR(15) | `total_amount` | DECIMAL(10,2) | Remove commas, parse → decimal |
| `PMT_PRIN_AMT` | VARCHAR(15) | `principal_amount` | DECIMAL(10,2) | Remove commas, parse → decimal |
| `PMT_INT_AMT` | VARCHAR(15) | `interest_amount` | DECIMAL(10,2) | Remove commas, parse → decimal |
| `PMT_ESCROW_AMT` | VARCHAR(15) | `escrow_amount` | DECIMAL(10,2) | Remove commas, parse → decimal |
| `PMT_LATE_FEE` | VARCHAR(15) | `late_fee` | DECIMAL(10,2) | Remove commas, parse → decimal |
| `PMT_TYP_CD` | VARCHAR(5) | `type` | STRING | Expand: `REG`→`Regular`, `EXT`→`Extra`, `PRT`→`Partial`, `PRE`→`Prepayment` |
| `PMT_STAT_CD` | VARCHAR(5) | `status` | STRING | Expand: `PST`→`Posted`, `REV`→`Reversed`, `NSF`→`NSF`, `PND`→`Pending` |
| `PMT_RECV_DT` | VARCHAR(10) | `received_date` | DATE | Parse `MM/DD/YYYY` → date |
| `PMT_PROC_DT` | VARCHAR(10) | `processed_date` | DATE | Parse `MM/DD/YYYY` → date |
| `PMT_CRET_DT` | VARCHAR(10) | `created_at` | TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |
| `PMT_UPDT_DT` | VARCHAR(10) | `updated_at` | TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |
| *(derived)* | — | `payment_year` | INT | `year(payment_date)` — used as partition column |

---

## 4. Type Conversion Decisions

### Date Parsing

- **Format:** `MM/DD/YYYY` (e.g., `03/15/1978`, `01/01/2020`)
- **Target type:** `DATE` for pure dates, `TIMESTAMP` for audit fields (`created_at`, `updated_at`)
- **Implementation:** `F.to_date(col, "MM/dd/yyyy")` / `F.to_timestamp(col, "MM/dd/yyyy")`
- **Null handling:** Malformed strings become `NULL` with a parse-error flag column
- **Rationale for TIMESTAMP on audit fields:** Allows future enhancement to capture time-of-day without schema change

### Amount Parsing

- **Format:** Comma-separated strings (e.g., `"285,000"`, `"271,432.56"`, `"0.00"`)
- **Approach:** `regexp_replace(col, ",", "")` then `.cast(DecimalType(p, s))`
- **Precision choices:**
  - `DECIMAL(12,2)` for loan/property amounts (up to $9,999,999,999.99)
  - `DECIMAL(10,2)` for payment amounts and escrow (up to $99,999,999.99)
  - `DECIMAL(5,3)` for interest rates (up to 99.999%)
  - `DECIMAL(5,2)` for LTV percent (up to 999.99%)

### Integer Parsing

- **Fields:** `credit_score`, `term_months`, `delinquency_days`
- **Approach:** Direct `.cast(IntegerType())`
- **Edge case:** Non-numeric strings become `NULL` with a flag

### Status Code Expansion

| Domain | Code | Expanded Value |
|--------|------|----------------|
| Borrower status | `ACT` | `Active` |
| Borrower status | `INA` | `Inactive` |
| Loan status | `ACT` | `Active` |
| Loan status | `CLO` | `Closed` |
| Loan status | `DFT` | `Default` |
| Loan status | `FRB` | `Forbearance` |
| Product status | `ACT` | `true` (boolean) |
| Product status | `INA` | `false` (boolean) |
| Payment type | `REG` | `Regular` |
| Payment type | `EXT` | `Extra` |
| Payment type | `PRT` | `Partial` |
| Payment type | `PRE` | `Prepayment` |
| Payment status | `PST` | `Posted` |
| Payment status | `REV` | `Reversed` |
| Payment status | `NSF` | `NSF` |
| Payment status | `PND` | `Pending` |
| Property type | `SFR` | `Single Family` |
| Property type | `CND` | `Condominium` |
| Property type | `MFR` | `Multi-Family` |
| Property type | `TWN` | `Townhouse` |

**Unknown codes** are preserved as-is and flagged for review (not silently dropped).

---

## 5. Denormalization Removal

The legacy `CDW_LN_ACCT` table embeds borrower fields:
- `BORR_FST_NM` — first name (redundant with `CDW_BORR_MSTR`)
- `BORR_LST_NM` — last name (redundant)
- `BORR_SSN_LST4` — last 4 of SSN (redundant)

**Decision:** These columns are **dropped** during ingestion. The modern `loan_accounts` table references `borrowers` via `borrower_id` (resolved from `BORR_ID` → `borrowers.external_id`).

**FK Resolution Strategy:**
1. Ingest `borrowers` first so the lookup table is available.
2. During `loan_accounts` ingestion, join on `BORR_ID == borrowers.external_id` to get `borrower_id`.
3. Unresolved references are flagged (not dropped) and written to an error Parquet file.

The same pattern applies to `PROD_CD` → `loan_products.product_id` and `LN_ACCT_NBR` → `loan_accounts.loan_account_id` for payments.

---

## 6. Error Handling Strategy

The pipeline follows a **log-and-continue** approach — records are never silently dropped.

| Scenario | Behavior |
|----------|----------|
| Malformed date string | Value becomes `NULL`; `__<col>_parse_err = true` flag set |
| Malformed amount string | Value becomes `NULL`; parse-error flag set |
| Unknown status code | Original code preserved as-is; `__<col>_unmapped = true` flag set |
| NULL in source | Preserved as `NULL` in target (no flag needed) |
| Unresolved FK | `NULL` FK with `__<col>_unresolved = true` flag set |
| Empty source file | Warning printed; ingestion skipped for that table |

**Error audit:**
- Parse-error rows are written to `/mnt/migration_errors/<TABLE>_errors` as Parquet.
- Console output summarizes error counts per column.
- The data quality framework runs post-ingestion to catch any residual issues.

---

## 7. Execution Order

The pipeline must be run in this specific order due to FK dependencies:

```
Step 1: Create schema
        └── databricks/ddl/create_schema.sql

Step 2: Create tables (can run in parallel)
        ├── databricks/ddl/create_borrowers.sql
        ├── databricks/ddl/create_loan_products.sql
        ├── databricks/ddl/create_loan_accounts.sql
        └── databricks/ddl/create_payments.sql

Step 3: Ingest dimension tables (can run in parallel)
        ├── databricks/ingestion/ingest_borrowers.py
        └── databricks/ingestion/ingest_loan_products.py

Step 4: Ingest loan accounts (depends on Step 3)
        └── databricks/ingestion/ingest_loan_accounts.py

Step 5: Ingest payments (depends on Step 4)
        └── databricks/ingestion/ingest_payments.py

Step 6: Run data quality checks
        └── databricks/quality/data_quality_checks.py

Step 7: Generate quality report
        └── databricks/quality/generate_report.py
```

**Alternatively**, use the orchestrator to run Steps 3-5 automatically:
```bash
spark-submit databricks/ingestion/run_full_ingestion.py \
    --base-path /mnt/landing \
    --format csv
```

---

## 8. Databricks Execution Guide

### 8.1 Prerequisites

- Databricks workspace with Unity Catalog enabled
- A catalog where `loan_warehouse` schema will be created
- Source files uploaded to cloud storage (DBFS, ADLS, S3, or GCS)
- Cluster with Databricks Runtime 13.3 LTS or later

### 8.2 Source File Preparation

Export legacy tables as CSV or Parquet into the following structure:

```
/mnt/landing/
├── cdw_borr_mstr/        # CDW_BORR_MSTR export
│   └── part-*.csv
├── cdw_ln_prod/           # CDW_LN_PROD export
│   └── part-*.csv
├── cdw_ln_acct/           # CDW_LN_ACCT export
│   └── part-*.csv
└── cdw_pmt_hist/          # CDW_PMT_HIST export
    └── part-*.csv
```

CSV files must have a header row with the legacy column names.

### 8.3 Running DDL

Execute each SQL file in a Databricks SQL warehouse or notebook:

```sql
-- In a Databricks SQL notebook:
%run ./databricks/ddl/create_schema
%run ./databricks/ddl/create_borrowers
%run ./databricks/ddl/create_loan_products
%run ./databricks/ddl/create_loan_accounts
%run ./databricks/ddl/create_payments
```

### 8.4 Running Ingestion

**Option A — Orchestrator (recommended):**
```python
# In a Databricks notebook
%run ./databricks/ingestion/run_full_ingestion

spark = SparkSession.builder.getOrCreate()
results, success = run_pipeline(spark, "/mnt/landing", "csv", "overwrite")
```

**Option B — Individual scripts:**
```python
%run ./databricks/ingestion/ingest_borrowers
run(spark, "/mnt/landing/cdw_borr_mstr", "csv", "overwrite")

%run ./databricks/ingestion/ingest_loan_products
run(spark, "/mnt/landing/cdw_ln_prod", "csv", "overwrite")

# Must run AFTER borrowers + loan_products
%run ./databricks/ingestion/ingest_loan_accounts
run(spark, "/mnt/landing/cdw_ln_acct", "csv", "overwrite")

# Must run AFTER loan_accounts
%run ./databricks/ingestion/ingest_payments
run(spark, "/mnt/landing/cdw_pmt_hist", "csv", "overwrite")
```

### 8.5 Running Quality Checks

```python
%run ./databricks/quality/data_quality_checks

spark = SparkSession.builder.getOrCreate()
results = run_all_checks(spark, "/mnt/landing", "csv")

# Generate Markdown report
%run ./databricks/quality/generate_report

generate_report(results, "/Workspace/reports/DATA_QUALITY_REPORT.md")
```

### 8.6 Post-Migration Optimization

After the initial load, run these Delta Lake maintenance commands:

```sql
-- Optimize file sizes
OPTIMIZE loan_warehouse.borrowers;
OPTIMIZE loan_warehouse.loan_products;
OPTIMIZE loan_warehouse.loan_accounts ZORDER BY (borrower_id);
OPTIMIZE loan_warehouse.payments ZORDER BY (loan_account_id);

-- Analyze for query optimizer
ANALYZE TABLE loan_warehouse.borrowers COMPUTE STATISTICS FOR ALL COLUMNS;
ANALYZE TABLE loan_warehouse.loan_products COMPUTE STATISTICS FOR ALL COLUMNS;
ANALYZE TABLE loan_warehouse.loan_accounts COMPUTE STATISTICS FOR ALL COLUMNS;
ANALYZE TABLE loan_warehouse.payments COMPUTE STATISTICS FOR ALL COLUMNS;
```

---

## 9. Validation Checklist

After running the pipeline, verify:

- [ ] **Row counts match** — Source and target row counts are equal for all 4 tables
- [ ] **No NULL required fields** — `external_id`, `first_name`, `last_name`, `account_number`, etc. are populated
- [ ] **FK integrity** — All `borrower_id`, `product_id`, `loan_account_id` references resolve
- [ ] **Active loans have balance > 0** — No active loans with zero or negative balance
- [ ] **Closed loans have maturity date** — All closed loans have a non-null maturity date
- [ ] **Interest rates in range** — All rates between 0% and 100%
- [ ] **Dates are valid** — Origination date < maturity date for all loans
- [ ] **Payment components sum** — `principal + interest + escrow + late_fee ≈ total_amount`
- [ ] **Status codes expanded** — No abbreviated codes remain in target tables
- [ ] **Error audit reviewed** — Check `/mnt/migration_errors/` for any flagged rows

---

## 10. Rollback Procedure

If the migration needs to be rolled back:

```sql
-- Drop target tables (Delta Lake supports time travel, so data is recoverable)
DROP TABLE IF EXISTS loan_warehouse.payments;
DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
DROP TABLE IF EXISTS loan_warehouse.loan_products;
DROP TABLE IF EXISTS loan_warehouse.borrowers;

-- Or use time travel to restore a previous version:
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF 0;
```

---

## 11. Incremental Load Strategy (Future)

For ongoing incremental loads after the initial migration:

1. Use `MERGE INTO` (Delta Lake upsert) instead of `overwrite`:
   ```sql
   MERGE INTO loan_warehouse.borrowers AS target
   USING staging.new_borrowers AS source
   ON target.external_id = source.external_id
   WHEN MATCHED THEN UPDATE SET *
   WHEN NOT MATCHED THEN INSERT *;
   ```
2. Partition pruning on `payment_year` enables efficient incremental payment loads.
3. Use Delta Lake Change Data Feed (CDF) to track downstream changes.
