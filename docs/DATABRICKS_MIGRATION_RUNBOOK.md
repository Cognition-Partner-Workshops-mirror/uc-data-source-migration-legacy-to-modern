# Databricks Migration Runbook

## Overview

This runbook documents the end-to-end migration of the legacy CDW (Corporate Data Warehouse) loan management data to a modern Delta Lake schema on Databricks. It covers every transformation decision, column mapping, type conversion, partitioning rationale, and the recommended execution order.

---

## 1. Source System Summary

### Legacy Tables

| Legacy Table | Description | Row Count (Seed) | Key Issues |
|-------------|-------------|-------------------|------------|
| `CDW_BORR_MSTR` | Borrower master | 5 | All VARCHAR columns, dates as MM/DD/YYYY strings, amounts with commas |
| `CDW_LN_PROD` | Loan products | 5 | Amounts as comma-strings, status codes (ACT/INA) |
| `CDW_LN_ACCT` | Loan accounts | 5 | Denormalized borrower fields, no FKs, all VARCHAR |
| `CDW_PMT_HIST` | Payment history | 10 | Amounts as comma-strings, dates as strings, status abbreviations |

### Legacy Schema Problems

1. **All-VARCHAR typing**: Every column is VARCHAR — dates, amounts, integers, booleans all stored as strings
2. **Cryptic column names**: Abbreviated names like `BORR_FST_NM`, `LN_CURR_BAL`, `PMT_ESCROW_AMT`
3. **No foreign keys**: `CDW_LN_ACCT.BORR_ID` references `CDW_BORR_MSTR.BORR_ID` but has no FK constraint
4. **Denormalization**: `CDW_LN_ACCT` duplicates borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`)
5. **Status code abbreviations**: `ACT`, `CLO`, `DFT`, `FRB` instead of readable values
6. **String-encoded numbers**: Amounts like `"285,000"` and `"271,432.56"` with embedded commas

---

## 2. Target Schema (Delta Lake)

### Database Setup

```sql
CREATE CATALOG IF NOT EXISTS loan_catalog;
CREATE SCHEMA IF NOT EXISTS loan_catalog.loan_warehouse;
```

### Target Tables

| Target Table | Source | Partition Column | Rationale |
|-------------|--------|-----------------|-----------|
| `loan_warehouse.borrowers` | `CDW_BORR_MSTR` | `status` | Most queries filter by ACTIVE/INACTIVE status |
| `loan_warehouse.loan_products` | `CDW_LN_PROD` | *(none)* | Small reference table (~10s of rows); partitioning would add overhead |
| `loan_warehouse.loan_accounts` | `CDW_LN_ACCT` | `origination_year` | Supports loan vintage analysis and time-range queries |
| `loan_warehouse.payments` | `CDW_PMT_HIST` | `payment_year` | Supports monthly reconciliation and time-range reporting |

### Partitioning Rationale

- **`borrowers` by `status`**: Low cardinality (ACTIVE/INACTIVE) creates 2 partitions. Most downstream queries filter on active borrowers, so partition pruning is highly effective.
- **`loan_accounts` by `origination_year`**: Loan vintage analysis is a core use case. Partitioning by year keeps partitions balanced (~uniform loans per year) and enables efficient range scans.
- **`payments` by `payment_year`**: Payment reconciliation runs monthly/quarterly against specific date ranges. Year-based partitioning enables efficient pruning for these workloads.
- **`loan_products`**: Not partitioned. Reference/dimension table with very few rows. Partitioning would introduce unnecessary file overhead.

### Delta Table Properties

All tables use:
- `delta.autoOptimize.optimizeWrite = true` — automatic bin-packing on write
- `delta.autoOptimize.autoCompact = true` — automatic small file compaction
- `delta.columnMapping.mode = name` — enables column rename/drop without rewriting data

---

## 3. Column Mapping Reference

### CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Conversion | Notes |
|--------------|---------------|-----------------|-------|
| `BORR_ID` | `external_id` | VARCHAR → STRING | Direct copy; unique constraint |
| `BORR_FST_NM` | `first_name` | VARCHAR → STRING | Trimmed |
| `BORR_LST_NM` | `last_name` | VARCHAR → STRING | Trimmed |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR → STRING | Direct copy; nullable |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR → STRING | Direct copy; re-encryption recommended post-migration |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR → DATE | Parse `MM/DD/YYYY` via `to_date()` |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR → STRING | Trimmed |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR → STRING | Trimmed; nullable |
| `BORR_CTY_NM` | `city` | VARCHAR → STRING | Trimmed |
| `BORR_ST_CD` | `state` | VARCHAR → STRING | 2-char state code |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR → STRING | Kept as string (leading zeros) |
| `BORR_PH_NBR` | `phone` | VARCHAR → STRING | Kept as string (formatting) |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR → STRING | Trimmed |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR → INT | `cast(INT)` |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR → STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR → DECIMAL(12,2) | Strip commas, `cast(DECIMAL)` |
| `BORR_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` via `to_timestamp()` |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` via `to_timestamp()` |
| `BORR_STAT_CD` | `status` | VARCHAR → STRING | Expand: `ACT`→`ACTIVE`, `INA`→`INACTIVE` |
| `BORR_REC_TYP` | *(dropped)* | — | Record type indicator; not needed in modern schema |

### CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Conversion | Notes |
|--------------|---------------|-----------------|-------|
| `PROD_CD` | `code` | VARCHAR → STRING | Direct copy; unique constraint |
| `PROD_DESC_TXT` | `name` | VARCHAR → STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR → STRING | Direct copy (FXD, ARM, FHA, VA) |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | `cast(INT)` |
| `PROD_RT_TYP` | `rate_type` | VARCHAR → STRING | Direct copy (FIXED, VARIABLE) |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) | Strip commas |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) | Strip commas |
| `PROD_STAT_CD` | `is_active` | VARCHAR → BOOLEAN | `ACT`→`true`, `INA`→`false` |
| `PROD_EFF_DT` | `effective_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |

### CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Conversion | Notes |
|--------------|---------------|-----------------|-------|
| `LN_ACCT_NBR` | `account_number` | VARCHAR → STRING | Direct copy; unique constraint |
| `BORR_ID` | `borrower_key` | VARCHAR → BIGINT | FK lookup: `borrowers.external_id` → `borrowers.borrower_key` |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_key` | VARCHAR → BIGINT | FK lookup: `loan_products.code` → `loan_products.product_key` |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) | Strip commas |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) | Strip commas |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | Parse string "5.250" |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | `cast(INT)` |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) | Strip commas |
| `LN_ORIG_DT` | `origination_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_MAT_DT` | `maturity_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_STAT_CD` | `status` | VARCHAR → STRING | Expand: `ACT`→`ACTIVE`, `CLO`→`CLOSED`, `DFT`→`DEFAULT`, `FRB`→`FORBEARANCE` |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | `cast(INT)` |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Strip commas |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | Parse string |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR → STRING | Trimmed |
| `PROP_CTY_NM` | `property_city` | VARCHAR → STRING | Trimmed |
| `PROP_ST_CD` | `property_state` | VARCHAR → STRING | 2-char state code |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR → STRING | Kept as string |
| `PROP_TYP_CD` | `property_type` | VARCHAR → STRING | Expand: `SFR`→`Single Family`, `CND`→`Condominium`, `MFR`→`Multi-Family`, `TWN`→`Townhouse` |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Strip commas |
| `LN_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `LN_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| *(derived)* | `origination_year` | — → INT | `YEAR(origination_date)` — partition column |

### CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Conversion | Notes |
|--------------|---------------|-----------------|-------|
| `PMT_SEQ_NBR` | `legacy_sequence_nbr` | VARCHAR → STRING | Preserved for traceability |
| `LN_ACCT_NBR` | `loan_key` | VARCHAR → BIGINT | FK lookup: `loan_accounts.account_number` → `loan_accounts.loan_key` |
| `PMT_DT` | `payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_AMT` | `total_amount` | VARCHAR → DECIMAL(10,2) | Strip commas |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR → DECIMAL(10,2) | Strip commas |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR → DECIMAL(10,2) | Strip commas |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR → DECIMAL(10,2) | Strip commas |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR → DECIMAL(10,2) | Strip commas |
| `PMT_TYP_CD` | `type` | VARCHAR → STRING | Expand: `REG`→`REGULAR`, `EXT`→`EXTRA`, `PRT`→`PARTIAL`, `PRE`→`PREPAYMENT` |
| `PMT_STAT_CD` | `status` | VARCHAR → STRING | Expand: `PST`→`POSTED`, `REV`→`REVERSED`, `NSF`→`NSF`, `PND`→`PENDING` |
| `PMT_RECV_DT` | `received_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_PROC_DT` | `processed_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| *(derived)* | `payment_year` | — → INT | `YEAR(payment_date)` — partition column |

---

## 4. Transformation Decisions

### 4.1 Date Parsing

All legacy date columns store dates as `MM/DD/YYYY` VARCHAR strings. The ingestion scripts use `to_date(col, "MM/dd/yyyy")` (PySpark) to convert to `DateType`. Columns that semantically represent record timestamps (`BORR_CRET_DT`, `BORR_UPDT_DT`, `LN_CRET_DT`, `LN_UPDT_DT`, `PMT_CRET_DT`, `PMT_UPDT_DT`) are converted to `TimestampType` (midnight of the given date) via `to_timestamp(col, "MM/dd/yyyy")`.

**Edge cases**: Null or malformed date strings produce `null` in the target. These rows are not dropped — they are flagged by the data quality framework.

### 4.2 Amount Parsing

Amounts in the legacy system are stored with commas as thousands separators (e.g., `"285,000"`, `"271,432.56"`). Some may also include dollar signs. The pipeline applies `regexp_replace(col, "[$,]", "")` to strip formatting characters, then casts to the appropriate `DecimalType`.

**Precision choices**:
- Loan amounts, appraised values, annual income: `DECIMAL(12,2)` — supports values up to $9,999,999,999.99
- Payment amounts, escrow, monthly payment: `DECIMAL(10,2)` — supports values up to $99,999,999.99
- Interest rate: `DECIMAL(5,3)` — supports rates up to 99.999%
- LTV percent: `DECIMAL(5,2)` — supports percentages up to 999.99%

### 4.3 Status Code Expansion

| Context | Code | Expanded Value |
|---------|------|----------------|
| Borrower status | `ACT` | `ACTIVE` |
| Borrower status | `INA` | `INACTIVE` |
| Loan status | `ACT` | `ACTIVE` |
| Loan status | `CLO` | `CLOSED` |
| Loan status | `DFT` | `DEFAULT` |
| Loan status | `FRB` | `FORBEARANCE` |
| Payment type | `REG` | `REGULAR` |
| Payment type | `EXT` | `EXTRA` |
| Payment type | `PRT` | `PARTIAL` |
| Payment type | `PRE` | `PREPAYMENT` |
| Payment status | `PST` | `POSTED` |
| Payment status | `REV` | `REVERSED` |
| Payment status | `NSF` | `NSF` |
| Payment status | `PND` | `PENDING` |
| Property type | `SFR` | `Single Family` |
| Property type | `CND` | `Condominium` |
| Property type | `MFR` | `Multi-Family` |
| Property type | `TWN` | `Townhouse` |
| Product status | `ACT` | `true` (boolean) |
| Product status | `INA` | `false` (boolean) |

Unrecognized codes default to `UNKNOWN` (or `Other` for property type, `false` for product status).

### 4.4 Denormalization Removal

The legacy `CDW_LN_ACCT` table embeds borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`). These are dropped during ingestion. Instead, the `borrower_key` foreign key references the `borrowers` dimension table.

### 4.5 Foreign Key Resolution

The legacy schema uses string-based IDs with no FK constraints. The migration resolves these to surrogate keys:

1. **`CDW_LN_ACCT.BORR_ID`** → Join against `borrowers.external_id` to get `borrower_key`
2. **`CDW_LN_ACCT.PROD_CD`** → Join against `loan_products.code` to get `product_key`
3. **`CDW_PMT_HIST.LN_ACCT_NBR`** → Join against `loan_accounts.account_number` to get `loan_key`

Unresolved lookups (null FK values) are logged as warnings and quarantined.

### 4.6 NULL and Malformed Value Handling

- **Nulls in required columns**: Rows with nulls in required columns are quarantined to a JSON error path (`dbfs:/mnt/quarantine/{table}/`) with metadata: reason, source table, and timestamp.
- **Malformed amounts**: `regexp_replace` + `cast` produces `null` for non-numeric strings. The row is preserved but flagged.
- **Malformed dates**: `to_date` with explicit format returns `null` for unparseable strings.
- **No silent drops**: Every source row either lands in the target table or in the quarantine path.

### 4.7 Derived Columns

| Column | Table | Derivation |
|--------|-------|-----------|
| `origination_year` | `loan_accounts` | `YEAR(origination_date)` |
| `payment_year` | `payments` | `YEAR(payment_date)` |
| `_ingestion_ts` | all tables | `current_timestamp()` at pipeline execution time |

---

## 5. Execution Order

### Prerequisites

1. Databricks workspace with Unity Catalog enabled
2. A compute cluster (DBR 13.3+ recommended)
3. Legacy data exported as CSV or Parquet files to DBFS or cloud storage:
   ```
   dbfs:/mnt/landing/cdw/
   ├── cdw_borr_mstr/    (CSV/Parquet files)
   ├── cdw_ln_prod/       (CSV/Parquet files)
   ├── cdw_ln_acct/       (CSV/Parquet files)
   └── cdw_pmt_hist/      (CSV/Parquet files)
   ```

### Step-by-Step Execution

#### Step 1: Create Database and Tables

Run the DDL scripts in order:

```sql
-- In a Databricks SQL notebook or SQL warehouse:
%run databricks/ddl/00_database.sql
%run databricks/ddl/01_borrowers.sql
%run databricks/ddl/02_loan_products.sql
%run databricks/ddl/03_loan_accounts.sql
%run databricks/ddl/04_payments.sql
```

#### Step 2: Run Ingestion Pipeline

```python
# In a Databricks Python notebook:
from ingestion.run_pipeline import run_full_pipeline

results = run_full_pipeline(
    spark,
    base_source_path="dbfs:/mnt/landing/cdw/",
    source_format="csv",          # or "parquet"
    write_mode="overwrite",       # "overwrite" for initial load, "append" for incremental
    quarantine_base="dbfs:/mnt/quarantine/",
)

# Review results
for table, summary in results.items():
    if table.startswith("_"):
        continue
    print(f"{table}: {summary}")
```

The pipeline executes in dependency order:
1. `borrowers` — no dependencies
2. `loan_products` — no dependencies
3. `loan_accounts` — depends on borrowers + loan_products for FK resolution
4. `payments` — depends on loan_accounts for FK resolution

#### Step 3: Run Data Quality Checks

```python
# In a Databricks Python notebook:
from quality.run_quality_checks import run

report = run(
    spark,
    source_counts={
        "borrowers": 5,
        "loan_products": 5,
        "loan_accounts": 5,
        "payments": 10,
    },
    report_path="dbfs:/mnt/reports/data_quality/",
)

# The report is written as DATA_QUALITY_REPORT.md at the specified path
```

Quality checks include:
- **Row count reconciliation**: Source vs target counts per table
- **Null checks**: All required columns verified
- **Referential integrity**: All FK relationships validated
- **Business rules**: Balance > 0 for active loans, valid date ranges, etc.

#### Step 4: Review Quarantine

```python
# Check for any quarantined records
for table in ["borrowers", "loan_products", "loan_accounts", "payments"]:
    try:
        quarantine_df = spark.read.json(f"dbfs:/mnt/quarantine/{table}/")
        count = quarantine_df.count()
        if count > 0:
            print(f"WARNING: {count} quarantined rows in {table}")
            quarantine_df.show(truncate=False)
    except Exception:
        print(f"{table}: No quarantined records")
```

#### Step 5: Optimize Tables

```sql
-- After initial load, optimize the Delta tables
OPTIMIZE loan_warehouse.borrowers ZORDER BY (external_id);
OPTIMIZE loan_warehouse.loan_accounts ZORDER BY (account_number, borrower_key);
OPTIMIZE loan_warehouse.payments ZORDER BY (loan_key, payment_date);
ANALYZE TABLE loan_warehouse.borrowers COMPUTE STATISTICS FOR ALL COLUMNS;
ANALYZE TABLE loan_warehouse.loan_products COMPUTE STATISTICS FOR ALL COLUMNS;
ANALYZE TABLE loan_warehouse.loan_accounts COMPUTE STATISTICS FOR ALL COLUMNS;
ANALYZE TABLE loan_warehouse.payments COMPUTE STATISTICS FOR ALL COLUMNS;
```

---

## 6. Incremental Load Strategy

For ongoing data synchronization after the initial migration:

1. **Source extraction**: Export only changed/new records from CDW using `BORR_UPDT_DT`, `LN_UPDT_DT`, `PMT_UPDT_DT` as watermarks.
2. **Pipeline execution**: Run with `write_mode="append"`.
3. **Deduplication**: Use Delta Lake `MERGE` statements to upsert on natural keys:
   - `borrowers.external_id`
   - `loan_products.code`
   - `loan_accounts.account_number`
   - `payments.legacy_sequence_nbr`
4. **Quality checks**: Run after each incremental load with updated source counts.

---

## 7. Rollback Strategy

Delta Lake supports time travel, enabling safe rollback:

```sql
-- View table history
DESCRIBE HISTORY loan_warehouse.loan_accounts;

-- Rollback to a specific version
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF <version_number>;

-- Or rollback to a timestamp
RESTORE TABLE loan_warehouse.loan_accounts TO TIMESTAMP AS OF '2026-01-15T00:00:00Z';
```

---

## 8. File Structure

```
databricks/
├── ddl/
│   ├── 00_database.sql              # Catalog and schema creation
│   ├── 01_borrowers.sql             # Borrower dimension table DDL
│   ├── 02_loan_products.sql         # Loan product reference table DDL
│   ├── 03_loan_accounts.sql         # Loan accounts fact table DDL
│   └── 04_payments.sql              # Payment history fact table DDL
├── ingestion/
│   ├── __init__.py
│   ├── transforms.py                # Shared UDFs: date parsing, amount parsing, status expansion
│   ├── ingest_borrowers.py          # CDW_BORR_MSTR → borrowers
│   ├── ingest_loan_products.py      # CDW_LN_PROD → loan_products
│   ├── ingest_loan_accounts.py      # CDW_LN_ACCT → loan_accounts (with FK resolution)
│   ├── ingest_payments.py           # CDW_PMT_HIST → payments (with FK resolution)
│   └── run_pipeline.py              # Master orchestrator (runs all 4 in order)
└── quality/
    ├── __init__.py
    ├── validators.py                # Validation checks: row counts, nulls, FKs, business rules
    └── run_quality_checks.py        # Entry point for quality validation
```
