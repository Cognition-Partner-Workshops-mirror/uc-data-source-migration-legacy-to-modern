# Databricks Migration Runbook — CDW Legacy to Modern Delta Lake

## Overview

This runbook documents the complete migration from the legacy **CDW (Corporate Data Warehouse)** schema to a modern, normalized Delta Lake schema on Databricks. It covers every transformation decision, column mapping, type conversion, partitioning strategy, and the recommended execution order.

### Source System

The legacy CDW is a loan management data warehouse with the following characteristics:

| Characteristic | Detail |
|---|---|
| **Database** | Legacy relational DB (simulated as CSV/Parquet extracts) |
| **Tables** | 4 tables: `CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Column types** | All `VARCHAR` — no proper types for dates, numbers, or booleans |
| **Date format** | `MM/DD/YYYY` stored as strings |
| **Amount format** | Strings with commas: `"285,000"`, `"1,487.02"` |
| **Status codes** | Cryptic abbreviations: `ACT`, `CLO`, `DFT`, `FRB`, `PST`, `NSF` |
| **Normalization** | Denormalized — borrower data duplicated in `CDW_LN_ACCT` |
| **Constraints** | No foreign keys, no CHECK constraints |

### Target System

| Characteristic | Detail |
|---|---|
| **Platform** | Databricks with Delta Lake |
| **Schema** | `loan_warehouse` |
| **Tables** | 4 tables: `borrowers`, `loan_products`, `loan_accounts`, `payments` |
| **Column types** | Proper Spark SQL types: `DATE`, `TIMESTAMP`, `DECIMAL`, `INT`, `BOOLEAN`, `STRING` |
| **Normalization** | Normalized with FK relationships via surrogate keys |
| **Partitioning** | Table-specific strategies (see below) |

---

## Execution Order

The pipeline must be executed in dependency order because loan accounts resolve FKs to borrowers and products, and payments resolve FKs to loan accounts.

```
Step 1: Create schema        →  databricks/ddl/*.sql
Step 2: Ingest borrowers     →  databricks/notebooks/01_ingest_borrowers.py
Step 3: Ingest loan products →  databricks/notebooks/02_ingest_loan_products.py
Step 4: Ingest loan accounts →  databricks/notebooks/03_ingest_loan_accounts.py
Step 5: Ingest payments      →  databricks/notebooks/04_ingest_payments.py
Step 6: Data quality checks  →  databricks/notebooks/06_data_quality_checks.py
```

Steps 2 and 3 have no inter-dependencies and can run in parallel. Steps 4 and 5 are strictly sequential.

The orchestrator notebook `databricks/notebooks/05_run_all.py` runs steps 2–5 automatically in the correct order.

---

## Table Definitions & Partitioning

### 1. `loan_warehouse.borrowers`

**Source:** `CDW_BORR_MSTR`
**DDL:** `databricks/ddl/01_borrowers.sql`
**Partition column:** `state` (VARCHAR(2))

**Partitioning rationale:** Borrower queries commonly filter by geographic region (state). Partitioning by state provides good cardinality (≤50 partitions for US data) and enables partition pruning on geographic filters.

| Target Column | Type | Source Column | Transformation |
|---|---|---|---|
| `borrower_key` | BIGINT (identity) | — | Auto-generated surrogate key |
| `external_id` | STRING NOT NULL | `BORR_ID` | Direct copy |
| `first_name` | STRING NOT NULL | `BORR_FST_NM` | Direct copy |
| `last_name` | STRING NOT NULL | `BORR_LST_NM` | Direct copy |
| `middle_initial` | STRING | `BORR_MID_INIT` | Direct copy |
| `ssn_hash` | STRING | `BORR_SSN_ENCR` | Direct copy (re-encryption recommended) |
| `date_of_birth` | DATE | `BORR_DOB_DT` | Parse `MM/DD/YYYY` → DATE |
| `address_line1` | STRING | `BORR_ADDR_LN1` | Direct copy |
| `address_line2` | STRING | `BORR_ADDR_LN2` | Direct copy |
| `city` | STRING | `BORR_CTY_NM` | Direct copy |
| `state` | STRING | `BORR_ST_CD` | Direct copy |
| `zip_code` | STRING | `BORR_ZIP_CD` | Direct copy |
| `phone` | STRING | `BORR_PH_NBR` | Direct copy |
| `email` | STRING | `BORR_EMAIL_ADDR` | Direct copy |
| `credit_score` | INT | `BORR_CRDT_SCR` | Cast string → integer |
| `employment_status` | STRING | `BORR_EMP_STAT` | Direct copy |
| `annual_income` | DECIMAL(12,2) | `BORR_ANN_INCM` | Strip commas, cast to decimal |
| `status` | STRING | `BORR_STAT_CD` | Expand: ACT→ACTIVE, INA→INACTIVE |
| `created_at` | TIMESTAMP | `BORR_CRET_DT` | Parse `MM/DD/YYYY` → TIMESTAMP |
| `updated_at` | TIMESTAMP | `BORR_UPDT_DT` | Parse `MM/DD/YYYY` → TIMESTAMP |

**Dropped column:** `BORR_REC_TYP` — Record type indicator not needed in modern schema.

### 2. `loan_warehouse.loan_products`

**Source:** `CDW_LN_PROD`
**DDL:** `databricks/ddl/02_loan_products.sql`
**Partition column:** None

**Partitioning rationale:** This is a small reference table (typically < 100 rows). Partitioning would create overhead without benefit.

| Target Column | Type | Source Column | Transformation |
|---|---|---|---|
| `product_key` | BIGINT (identity) | — | Auto-generated surrogate key |
| `code` | STRING NOT NULL | `PROD_CD` | Direct copy |
| `name` | STRING NOT NULL | `PROD_DESC_TXT` | Direct copy |
| `type` | STRING NOT NULL | `PROD_TYP_CD` | Direct copy (FXD, ARM, FHA, VA) |
| `term_months` | INT NOT NULL | `PROD_TERM_MOS` | Cast string → integer |
| `rate_type` | STRING NOT NULL | `PROD_RT_TYP` | Direct copy (FIXED, VARIABLE) |
| `min_amount` | DECIMAL(12,2) | `PROD_MIN_AMT` | Strip commas, cast to decimal |
| `max_amount` | DECIMAL(12,2) | `PROD_MAX_AMT` | Strip commas, cast to decimal |
| `is_active` | BOOLEAN | `PROD_STAT_CD` | Convert: ACT→true, INA→false |
| `effective_date` | DATE | `PROD_EFF_DT` | Parse `MM/DD/YYYY` → DATE |
| `expiration_date` | DATE | `PROD_EXP_DT` | Parse `MM/DD/YYYY` → DATE |

### 3. `loan_warehouse.loan_accounts`

**Source:** `CDW_LN_ACCT`
**DDL:** `databricks/ddl/03_loan_accounts.sql`
**Partition column:** `status`

**Partitioning rationale:** Loan account queries almost always filter by status (active vs. closed vs. default). With only 4 partition values (ACTIVE, CLOSED, DEFAULT, FORBEARANCE), the partition count is very low, enabling efficient partition pruning without small-file problems.

| Target Column | Type | Source Column | Transformation |
|---|---|---|---|
| `loan_account_key` | BIGINT (identity) | — | Auto-generated surrogate key |
| `account_number` | STRING NOT NULL | `LN_ACCT_NBR` | Direct copy |
| `borrower_key` | BIGINT NOT NULL | `BORR_ID` | FK lookup → `borrowers.borrower_key` via `external_id` |
| `product_key` | BIGINT NOT NULL | `PROD_CD` | FK lookup → `loan_products.product_key` via `code` |
| `original_amount` | DECIMAL(12,2) NOT NULL | `LN_ORIG_AMT` | Strip commas, cast to decimal |
| `current_balance` | DECIMAL(12,2) NOT NULL | `LN_CURR_BAL` | Strip commas, cast to decimal |
| `interest_rate` | DECIMAL(5,3) NOT NULL | `LN_INT_RT` | Cast string → decimal |
| `term_months` | INT NOT NULL | `LN_TERM_MOS` | Cast string → integer |
| `monthly_payment` | DECIMAL(10,2) NOT NULL | `LN_PMT_AMT` | Strip commas, cast to decimal |
| `origination_date` | DATE NOT NULL | `LN_ORIG_DT` | Parse `MM/DD/YYYY` → DATE |
| `maturity_date` | DATE NOT NULL | `LN_MAT_DT` | Parse `MM/DD/YYYY` → DATE |
| `first_payment_date` | DATE | `LN_1ST_PMT_DT` | Parse `MM/DD/YYYY` → DATE |
| `next_payment_date` | DATE | `LN_NXT_PMT_DT` | Parse `MM/DD/YYYY` → DATE |
| `status` | STRING | `LN_STAT_CD` | Expand: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| `delinquency_days` | INT | `LN_DLQ_DAYS` | Cast string → integer |
| `escrow_balance` | DECIMAL(10,2) | `LN_ESCROW_BAL` | Strip commas, cast to decimal |
| `ltv_percent` | DECIMAL(5,2) | `LN_LTV_PCT` | Cast string → decimal |
| `property_address` | STRING | `PROP_ADDR_LN1` | Direct copy |
| `property_city` | STRING | `PROP_CTY_NM` | Direct copy |
| `property_state` | STRING | `PROP_ST_CD` | Direct copy |
| `property_zip` | STRING | `PROP_ZIP_CD` | Direct copy |
| `property_type` | STRING | `PROP_TYP_CD` | Expand: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| `appraised_value` | DECIMAL(12,2) | `PROP_APRS_VAL` | Strip commas, cast to decimal |
| `origination_year` | INT | `LN_ORIG_DT` | Derived: `year(origination_date)` |
| `created_at` | TIMESTAMP | `LN_CRET_DT` | Parse `MM/DD/YYYY` → TIMESTAMP |
| `updated_at` | TIMESTAMP | `LN_UPDT_DT` | Parse `MM/DD/YYYY` → TIMESTAMP |

**Dropped columns (denormalized borrower data):**
- `BORR_FST_NM` — Use `borrower_key` FK to `borrowers` table instead
- `BORR_LST_NM` — Use `borrower_key` FK to `borrowers` table instead
- `BORR_SSN_LST4` — Use `borrower_key` FK to `borrowers` table instead

### 4. `loan_warehouse.payments`

**Source:** `CDW_PMT_HIST`
**DDL:** `databricks/ddl/04_payments.sql`
**Partition column:** `payment_year`

**Partitioning rationale:** Payment history is the highest-volume table. Partitioning by year enables efficient time-range queries (e.g., "all payments in 2025"), supports data lifecycle management (archive old years), and provides good partition sizes for large datasets.

| Target Column | Type | Source Column | Transformation |
|---|---|---|---|
| `payment_key` | BIGINT (identity) | — | Auto-generated surrogate key |
| `legacy_payment_id` | STRING | `PMT_SEQ_NBR` | Direct copy (preserved for audit trail) |
| `loan_account_key` | BIGINT NOT NULL | `LN_ACCT_NBR` | FK lookup → `loan_accounts.loan_account_key` via `account_number` |
| `payment_date` | DATE NOT NULL | `PMT_DT` | Parse `MM/DD/YYYY` → DATE |
| `total_amount` | DECIMAL(10,2) NOT NULL | `PMT_AMT` | Strip commas, cast to decimal |
| `principal_amount` | DECIMAL(10,2) | `PMT_PRIN_AMT` | Strip commas, cast to decimal |
| `interest_amount` | DECIMAL(10,2) | `PMT_INT_AMT` | Strip commas, cast to decimal |
| `escrow_amount` | DECIMAL(10,2) | `PMT_ESCROW_AMT` | Strip commas, cast to decimal |
| `late_fee` | DECIMAL(10,2) | `PMT_LATE_FEE` | Strip commas, cast to decimal |
| `type` | STRING NOT NULL | `PMT_TYP_CD` | Expand: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| `status` | STRING NOT NULL | `PMT_STAT_CD` | Expand: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| `received_date` | DATE | `PMT_RECV_DT` | Parse `MM/DD/YYYY` → DATE |
| `processed_date` | DATE | `PMT_PROC_DT` | Parse `MM/DD/YYYY` → DATE |
| `payment_year` | INT | `PMT_DT` | Derived: `year(payment_date)` |
| `created_at` | TIMESTAMP | `PMT_CRET_DT` | Parse `MM/DD/YYYY` → TIMESTAMP |
| `updated_at` | TIMESTAMP | `PMT_UPDT_DT` | Parse `MM/DD/YYYY` → TIMESTAMP |

---

## Transformation Patterns

### Date Parsing

All legacy dates are stored as `MM/DD/YYYY` VARCHAR(10) strings.

```python
# DateType
df = df.withColumn("target_col", F.to_date(F.col("SRC_COL"), "MM/dd/yyyy"))

# TimestampType (for created_at / updated_at)
df = df.withColumn("target_col", F.to_timestamp(F.col("SRC_COL"), "MM/dd/yyyy"))
```

**Edge cases:**
- Malformed dates (e.g., `"00/00/0000"`, `"13/32/2025"`) → `NULL` (Spark's `to_date` returns null for unparseable values)
- Raw values are preserved in `_raw_{column}` audit columns for traceability

### Amount Parsing

Legacy amounts contain commas (e.g., `"285,000"`, `"1,487.02"`).

```python
df = df.withColumn(
    "target_col",
    F.regexp_replace(F.col("SRC_COL"), ",", "").cast(DecimalType(12, 2))
)
```

**Edge cases:**
- Non-numeric strings → `NULL`
- Empty strings → `NULL`
- Dollar signs or other currency symbols → not present in source data, but would need stripping if encountered

### Status Code Expansion

| Table | Legacy Code | Modern Value |
|---|---|---|
| Borrowers | `ACT` | `ACTIVE` |
| Borrowers | `INA` | `INACTIVE` |
| Loan Accounts | `ACT` | `ACTIVE` |
| Loan Accounts | `CLO` | `CLOSED` |
| Loan Accounts | `DFT` | `DEFAULT` |
| Loan Accounts | `FRB` | `FORBEARANCE` |
| Loan Products | `ACT` | `true` (boolean) |
| Loan Products | `INA` | `false` (boolean) |
| Payments (type) | `REG` | `REGULAR` |
| Payments (type) | `EXT` | `EXTRA` |
| Payments (type) | `PRT` | `PARTIAL` |
| Payments (type) | `PRE` | `PREPAYMENT` |
| Payments (status) | `PST` | `POSTED` |
| Payments (status) | `REV` | `REVERSED` |
| Payments (status) | `NSF` | `NSF` |
| Payments (status) | `PND` | `PENDING` |
| Property Type | `SFR` | `Single Family` |
| Property Type | `CND` | `Condominium` |
| Property Type | `MFR` | `Multi-Family` |
| Property Type | `TWN` | `Townhouse` |

**Unrecognised codes** are preserved as-is (not dropped) and flagged with `_unmapped_{col} = true` for review.

### Denormalization Removal

The legacy `CDW_LN_ACCT` table contains three redundant borrower columns:
- `BORR_FST_NM` (first name)
- `BORR_LST_NM` (last name)
- `BORR_SSN_LST4` (last 4 of SSN)

These are **dropped** during migration. The modern schema uses `borrower_key` as a foreign key to the normalized `borrowers` table.

### Foreign Key Resolution

Legacy tables use natural keys (string IDs). The modern schema uses surrogate BIGINT keys generated by Delta Lake identity columns.

| Child Table | Child FK Column | Parent Table | Lookup Column |
|---|---|---|---|
| `loan_accounts` | `borrower_key` | `borrowers` | `external_id` |
| `loan_accounts` | `product_key` | `loan_products` | `code` |
| `payments` | `loan_account_key` | `loan_accounts` | `account_number` |

Unmatched FKs result in `NULL` surrogate keys. These are logged during ingestion and caught by the data quality referential integrity checks.

---

## Data Quality Framework

The post-ingestion quality framework (`databricks/quality/data_quality_checks.py`) runs four categories of checks:

### 1. Row Count Reconciliation
Compares expected source row counts against actual target row counts. Any mismatch indicates data loss or duplication.

### 2. Null Checks on Required Fields
Validates that NOT NULL columns contain no NULLs after transformation. Covers:
- `borrowers`: `external_id`, `first_name`, `last_name`
- `loan_products`: `code`, `name`, `type`, `term_months`, `rate_type`
- `loan_accounts`: `account_number`, `borrower_key`, `product_key`, `original_amount`, `current_balance`, `interest_rate`, `term_months`, `monthly_payment`, `origination_date`, `maturity_date`
- `payments`: `loan_account_key`, `payment_date`, `total_amount`, `type`, `status`

### 3. Referential Integrity
Checks for orphan foreign keys:
- `loan_accounts.borrower_key` → `borrowers.borrower_key`
- `loan_accounts.product_key` → `loan_products.product_key`
- `payments.loan_account_key` → `loan_accounts.loan_account_key`

### 4. Business Rule Validation
| Rule | Table | Condition |
|---|---|---|
| Active loans have positive balance | `loan_accounts` | `status = 'ACTIVE'` → `current_balance > 0` |
| No future origination dates | `loan_accounts` | `origination_date <= today` for active loans |
| Maturity after origination | `loan_accounts` | `maturity_date > origination_date` |
| Positive interest rate | `loan_accounts` | `interest_rate > 0` |
| LTV in range | `loan_accounts` | `0 <= ltv_percent <= 200` |
| Valid loan status | `loan_accounts` | Status in {ACTIVE, CLOSED, DEFAULT, FORBEARANCE} |
| Positive payment amount | `payments` | `total_amount > 0` |
| Valid payment type | `payments` | Type in {REGULAR, EXTRA, PARTIAL, PREPAYMENT} |
| Valid payment status | `payments` | Status in {POSTED, REVERSED, NSF, PENDING} |
| Credit score in range | `borrowers` | `300 <= credit_score <= 850` |
| Non-negative income | `borrowers` | `annual_income >= 0` |

The quality report is generated as a `DATA_QUALITY_REPORT.md` with pass/fail for each check.

---

## Quarantine Strategy

Rows that fail required-field validation are **never silently dropped**. Instead:

1. They are separated into a quarantine DataFrame during ingestion
2. Quarantine rows are written to a configurable path (e.g., `/mnt/quarantine/{table}/`)
3. The count of quarantined rows is included in the pipeline summary
4. Quarantined rows retain all original legacy column values for investigation

---

## Audit Columns

Every target table includes two audit columns appended during ingestion:

| Column | Type | Description |
|---|---|---|
| `_ingestion_ts` | TIMESTAMP | Timestamp when the row was loaded |
| `_source_system` | STRING | Source table name (e.g., `CDW_BORR_MSTR`) |

Additionally, during transformation, raw pre-conversion values are temporarily stored in `_raw_{column}` columns for debugging. These are excluded from the final target table select but are available in the intermediate DataFrames.

---

## Delta Lake Table Properties

All target tables are configured with:

```sql
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
)
```

- **Auto-optimize write** — Coalesces small files during writes
- **Auto-compact** — Automatically compacts small files in the background

---

## Databricks Execution Guide

### Prerequisites

1. A Databricks workspace with Unity Catalog enabled
2. A catalog and schema `loan_warehouse` created:
   ```sql
   CREATE CATALOG IF NOT EXISTS loan_catalog;
   CREATE SCHEMA IF NOT EXISTS loan_catalog.loan_warehouse;
   ```
3. Source data files placed in accessible storage (DBFS, S3, ADLS, or GCS)
4. Cluster with Databricks Runtime 13.3 LTS or later

### Running via Notebooks (Interactive)

1. Import all notebooks from `databricks/notebooks/` into your Databricks workspace
2. Run `05_run_all.py` with appropriate widget values:
   - `base_source_path`: Path to the directory containing source extracts
   - `file_format`: `csv` or `parquet`
   - `quarantine_base`: Path for quarantined rows
3. After completion, run `06_data_quality_checks.py`

### Running via Databricks Jobs (Automated)

Create a multi-task job:

```
Task 1: 01_ingest_borrowers      (no dependencies)
Task 2: 02_ingest_loan_products   (no dependencies)
Task 3: 03_ingest_loan_accounts   (depends on: Task 1, Task 2)
Task 4: 04_ingest_payments        (depends on: Task 3)
Task 5: 06_data_quality_checks    (depends on: Task 4)
```

### Running via Python Module

```python
from databricks.ingestion.run_all import run_pipeline
from databricks.quality.data_quality_checks import run_all_checks

# Run ingestion
results = run_pipeline(
    spark,
    base_source_path="/mnt/legacy-extract/",
    file_format="csv",
    quarantine_base="/mnt/quarantine/",
)

# Run quality checks
source_counts = {
    table: stats["loaded_count"]
    for table, stats in results.items()
    if table != "_pipeline"
}
report = run_all_checks(spark, source_counts=source_counts)
```

---

## Artifacts Inventory

| Path | Description |
|---|---|
| `databricks/ddl/01_borrowers.sql` | Delta Lake CREATE TABLE for borrowers |
| `databricks/ddl/02_loan_products.sql` | Delta Lake CREATE TABLE for loan_products |
| `databricks/ddl/03_loan_accounts.sql` | Delta Lake CREATE TABLE for loan_accounts |
| `databricks/ddl/04_payments.sql` | Delta Lake CREATE TABLE for payments |
| `databricks/ingestion/__init__.py` | Package init |
| `databricks/ingestion/utils.py` | Shared transformation utilities |
| `databricks/ingestion/ingest_borrowers.py` | Borrower ingestion module |
| `databricks/ingestion/ingest_loan_products.py` | Loan product ingestion module |
| `databricks/ingestion/ingest_loan_accounts.py` | Loan account ingestion module |
| `databricks/ingestion/ingest_payments.py` | Payment ingestion module |
| `databricks/ingestion/run_all.py` | Pipeline orchestrator module |
| `databricks/notebooks/01_ingest_borrowers.py` | Borrower ingestion notebook |
| `databricks/notebooks/02_ingest_loan_products.py` | Loan product ingestion notebook |
| `databricks/notebooks/03_ingest_loan_accounts.py` | Loan account ingestion notebook |
| `databricks/notebooks/04_ingest_payments.py` | Payment ingestion notebook |
| `databricks/notebooks/05_run_all.py` | Orchestrator notebook |
| `databricks/notebooks/06_data_quality_checks.py` | Data quality validation notebook |
| `databricks/quality/__init__.py` | Package init |
| `databricks/quality/data_quality_checks.py` | Quality check framework module |
| `docs/DATABRICKS_MIGRATION_RUNBOOK.md` | This document |
