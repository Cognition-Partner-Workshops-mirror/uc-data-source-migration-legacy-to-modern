# Databricks Migration Runbook

> CDW Legacy Data Warehouse → Modern Delta Lake Loan Warehouse

---

## Table of Contents

1. [Overview](#overview)
2. [Source Schema Summary](#source-schema-summary)
3. [Target Schema Summary](#target-schema-summary)
4. [Column Mapping Reference](#column-mapping-reference)
5. [Transformation Decisions](#transformation-decisions)
6. [Type Conversion Details](#type-conversion-details)
7. [Status Code Expansion](#status-code-expansion)
8. [Partitioning Strategy](#partitioning-strategy)
9. [Execution Order](#execution-order)
10. [Pre-Migration Checklist](#pre-migration-checklist)
11. [Running the Pipeline](#running-the-pipeline)
12. [Post-Migration Validation](#post-migration-validation)
13. [Troubleshooting](#troubleshooting)
14. [Rollback Procedure](#rollback-procedure)

---

## Overview

This runbook documents the migration of a loan management application's data from a
legacy CDW (Corporate Data Warehouse) schema to a modern Delta Lake schema on Databricks.

**Key problems with the legacy schema:**

| Problem | Example |
|---------|---------|
| All columns are `VARCHAR` | `LN_CURR_BAL VARCHAR(15)` stores `"271,432.56"` |
| Cryptic abbreviated names | `BORR_FST_NM`, `PMT_ESCROW_AMT`, `LN_LTV_PCT` |
| No foreign key constraints | `CDW_LN_ACCT.BORR_ID` has no FK to `CDW_BORR_MSTR` |
| Denormalized borrower data | Borrower name/SSN duplicated in `CDW_LN_ACCT` |
| Status codes as abbreviations | `ACT`, `CLO`, `DFT`, `FRB` |
| Dates as strings | `"03/15/1978"` stored in `VARCHAR(10)` |
| Amounts as comma-formatted strings | `"285,000"`, `"1,487.02"` |

**Legacy tables (4):**

- `CDW_BORR_MSTR` — Borrower master (20 columns)
- `CDW_LN_PROD` — Loan products (10 columns)
- `CDW_LN_ACCT` — Loan accounts, denormalized (29 columns)
- `CDW_PMT_HIST` — Payment history (14 columns)

**Modern tables (4):**

- `loan_warehouse.borrowers` — Normalized borrower dimension
- `loan_warehouse.loan_products` — Product reference table
- `loan_warehouse.loan_accounts` — Loan fact table with FK references
- `loan_warehouse.payments` — Payment transaction fact table

---

## Source Schema Summary

### CDW_BORR_MSTR (Borrower Master)

| Column | Type | Description |
|--------|------|-------------|
| `BORR_ID` | VARCHAR(20) | Primary key (e.g., `B-10001`) |
| `BORR_FST_NM` | VARCHAR(50) | First name |
| `BORR_LST_NM` | VARCHAR(50) | Last name |
| `BORR_MID_INIT` | VARCHAR(1) | Middle initial |
| `BORR_SSN_ENCR` | VARCHAR(100) | Encrypted SSN |
| `BORR_DOB_DT` | VARCHAR(10) | Date of birth (MM/DD/YYYY) |
| `BORR_ADDR_LN1` | VARCHAR(100) | Address line 1 |
| `BORR_ADDR_LN2` | VARCHAR(100) | Address line 2 |
| `BORR_CTY_NM` | VARCHAR(50) | City |
| `BORR_ST_CD` | VARCHAR(2) | State code |
| `BORR_ZIP_CD` | VARCHAR(10) | ZIP code |
| `BORR_PH_NBR` | VARCHAR(15) | Phone number |
| `BORR_EMAIL_ADDR` | VARCHAR(100) | Email |
| `BORR_CRDT_SCR` | VARCHAR(5) | Credit score as string |
| `BORR_EMP_STAT` | VARCHAR(20) | Employment status |
| `BORR_ANN_INCM` | VARCHAR(15) | Annual income with commas |
| `BORR_CRET_DT` | VARCHAR(10) | Created date (MM/DD/YYYY) |
| `BORR_UPDT_DT` | VARCHAR(10) | Updated date (MM/DD/YYYY) |
| `BORR_STAT_CD` | VARCHAR(5) | Status code |
| `BORR_REC_TYP` | VARCHAR(10) | Record type |

### CDW_LN_PROD (Loan Products)

| Column | Type | Description |
|--------|------|-------------|
| `PROD_CD` | VARCHAR(10) | Product code (e.g., `FXD30`) |
| `PROD_DESC_TXT` | VARCHAR(200) | Description |
| `PROD_TYP_CD` | VARCHAR(5) | Type: FXD, ARM, FHA, VA |
| `PROD_TERM_MOS` | VARCHAR(5) | Term in months as string |
| `PROD_RT_TYP` | VARCHAR(10) | FIXED or VARIABLE |
| `PROD_MIN_AMT` | VARCHAR(15) | Min amount with commas |
| `PROD_MAX_AMT` | VARCHAR(15) | Max amount with commas |
| `PROD_STAT_CD` | VARCHAR(5) | Status code |
| `PROD_EFF_DT` | VARCHAR(10) | Effective date (MM/DD/YYYY) |
| `PROD_EXP_DT` | VARCHAR(10) | Expiration date (MM/DD/YYYY) |

### CDW_LN_ACCT (Loan Accounts — Denormalized)

| Column | Type | Description |
|--------|------|-------------|
| `LN_ACCT_NBR` | VARCHAR(20) | Account number (e.g., `LN-2019-00142`) |
| `BORR_ID` | VARCHAR(20) | Borrower reference (no FK) |
| `BORR_FST_NM` | VARCHAR(50) | Denormalized borrower first name |
| `BORR_LST_NM` | VARCHAR(50) | Denormalized borrower last name |
| `BORR_SSN_LST4` | VARCHAR(4) | Last 4 of SSN (denormalized) |
| `PROD_CD` | VARCHAR(10) | Product code reference (no FK) |
| `LN_ORIG_AMT` | VARCHAR(15) | Original amount |
| `LN_CURR_BAL` | VARCHAR(15) | Current balance |
| `LN_INT_RT` | VARCHAR(8) | Interest rate as string |
| `LN_TERM_MOS` | VARCHAR(5) | Term months |
| `LN_PMT_AMT` | VARCHAR(15) | Monthly payment |
| `LN_ORIG_DT` | VARCHAR(10) | Origination date |
| `LN_MAT_DT` | VARCHAR(10) | Maturity date |
| `LN_1ST_PMT_DT` | VARCHAR(10) | First payment date |
| `LN_NXT_PMT_DT` | VARCHAR(10) | Next payment date |
| `LN_STAT_CD` | VARCHAR(5) | Loan status code |
| `LN_DLQ_DAYS` | VARCHAR(5) | Delinquency days |
| `LN_ESCROW_BAL` | VARCHAR(15) | Escrow balance |
| `LN_LTV_PCT` | VARCHAR(8) | Loan-to-value ratio |
| `PROP_ADDR_LN1` | VARCHAR(100) | Property address |
| `PROP_CTY_NM` | VARCHAR(50) | Property city |
| `PROP_ST_CD` | VARCHAR(2) | Property state |
| `PROP_ZIP_CD` | VARCHAR(10) | Property ZIP |
| `PROP_TYP_CD` | VARCHAR(10) | Property type code |
| `PROP_APRS_VAL` | VARCHAR(15) | Appraised value |
| `LN_CRET_DT` | VARCHAR(10) | Created date |
| `LN_UPDT_DT` | VARCHAR(10) | Updated date |

### CDW_PMT_HIST (Payment History)

| Column | Type | Description |
|--------|------|-------------|
| `PMT_SEQ_NBR` | VARCHAR(20) | Payment sequence ID |
| `LN_ACCT_NBR` | VARCHAR(20) | Loan account reference (no FK) |
| `PMT_DT` | VARCHAR(10) | Payment date |
| `PMT_AMT` | VARCHAR(15) | Total payment amount |
| `PMT_PRIN_AMT` | VARCHAR(15) | Principal portion |
| `PMT_INT_AMT` | VARCHAR(15) | Interest portion |
| `PMT_ESCROW_AMT` | VARCHAR(15) | Escrow portion |
| `PMT_LATE_FEE` | VARCHAR(15) | Late fee |
| `PMT_TYP_CD` | VARCHAR(5) | Payment type code |
| `PMT_STAT_CD` | VARCHAR(5) | Payment status code |
| `PMT_RECV_DT` | VARCHAR(10) | Received date |
| `PMT_PROC_DT` | VARCHAR(10) | Processed date |
| `PMT_CRET_DT` | VARCHAR(10) | Created date |
| `PMT_UPDT_DT` | VARCHAR(10) | Updated date |

---

## Target Schema Summary

All modern tables live in the `loan_warehouse` Unity Catalog schema and are stored as
Delta Lake tables with auto-optimize enabled.

| Table | Partitioned By | Rationale |
|-------|---------------|-----------|
| `borrowers` | `state` | Geographic queries are common for compliance |
| `loan_products` | *(none)* | Small reference table (~10s of rows) |
| `loan_accounts` | `origination_year` | Time-based queries (vintage analysis) dominate |
| `payments` | `payment_year` | Time-range scans for reconciliation |

---

## Column Mapping Reference

Full column-level mappings are maintained in
[`data/mappings/column_mappings.md`](../data/mappings/column_mappings.md).

### Key transformations at a glance

| Pattern | Count | Example |
|---------|-------|---------|
| Date string → `DATE` | 16 columns | `"03/15/1978"` → `1978-03-15` |
| Date string → `TIMESTAMP` | 8 columns | `"01/15/2019"` → `2019-01-15 00:00:00` |
| Comma amount → `DECIMAL` | 14 columns | `"285,000"` → `285000.00` |
| String → `INTEGER` | 5 columns | `"360"` → `360` |
| String → `DECIMAL` (rate) | 2 columns | `"4.750"` → `4.750` |
| Status expansion | 4 columns | `"ACT"` → `"Active"` |
| Boolean derivation | 1 column | `"ACT"` → `true` |
| Column dropped | 4 columns | Denormalized borrower fields in `CDW_LN_ACCT` |
| FK resolution | 3 columns | `BORR_ID` string → `borrower_id` BIGINT |

---

## Transformation Decisions

### 1. Denormalization removal

The legacy `CDW_LN_ACCT` table duplicates borrower fields (`BORR_FST_NM`, `BORR_LST_NM`,
`BORR_SSN_LST4`). In the modern schema these are **dropped** from `loan_accounts` and a
`borrower_id` FK points to the `borrowers` dimension table.

**Rationale:** Eliminates data duplication and inconsistency risk. Any borrower updates
propagate automatically without needing to sync multiple tables.

### 2. Foreign key resolution

Legacy tables use string-based references (`BORR_ID`, `PROD_CD`, `LN_ACCT_NBR`) with no
enforced constraints. The ingestion scripts resolve these to auto-generated `BIGINT` IDs
via lookup joins against the already-loaded dimension tables.

Unresolvable references are logged as warnings but **not dropped** — the FK column is set
to `NULL` and the row is retained for manual review.

### 3. Record type field (`BORR_REC_TYP`)

The column mapping specifies this field as "dropped" for the modern schema. However, we
preserve it as `_legacy_record_type` in the borrowers table for **audit traceability**.
This prefixed column is clearly marked as non-functional.

### 4. Legacy payment ID preservation

`PMT_SEQ_NBR` is stored as `legacy_payment_id` in the payments table. The modern table
uses an auto-generated `BIGINT` `id`, but the original sequence number is retained for
reconciliation with legacy systems during the transition period.

### 5. Derived partition columns

- `origination_year = year(origination_date)` added to `loan_accounts`
- `payment_year = year(payment_date)` added to `payments`

These are computed during ingestion and stored as physical columns to enable efficient
Delta Lake partitioning.

### 6. Ingestion timestamp

All tables include a `_ingestion_ts` column (defaults to `current_timestamp()`) to track
when each row was loaded by the pipeline.

---

## Type Conversion Details

### Date parsing (`MM/DD/YYYY` → `DATE`)

```python
F.to_date(F.trim(col), "MM/dd/yyyy")
```

- Blank/null strings → `NULL`
- Invalid date strings (e.g., `"99/99/9999"`) → `NULL` (logged as warning)
- Uses Spark's `CORRECTED` time parser policy

### Timestamp parsing (`MM/DD/YYYY` → `TIMESTAMP`)

```python
F.to_timestamp(F.trim(col), "MM/dd/yyyy")
```

- Produces midnight (`00:00:00`) timestamps since legacy dates have no time component

### Amount parsing (comma-formatted string → `DECIMAL`)

```python
F.regexp_replace(F.trim(col), ",", "").cast(DecimalType(12, 2))
```

- Handles: `"285,000"`, `"271,432.56"`, `"0"`, `"0.00"`
- Blank/null strings → `NULL`
- Precision/scale varies by column (see DDL)

### Integer parsing

```python
F.regexp_replace(F.trim(col), ",", "").cast(IntegerType())
```

- Handles: `"360"`, `"15"`, `"0"`
- Non-numeric values → `NULL` (logged as warning)

### Rate parsing (string → `DECIMAL(5,3)`)

```python
F.trim(col).cast(DecimalType(5, 3))
```

- Handles: `"4.750"`, `"3.125"`

---

## Status Code Expansion

### Borrower status (`BORR_STAT_CD`)

| Legacy Code | Modern Value |
|-------------|-------------|
| `ACT` | `Active` |
| `INA` | `Inactive` |
| *(other)* | `UNKNOWN(<original>)` |

### Loan status (`LN_STAT_CD`)

| Legacy Code | Modern Value |
|-------------|-------------|
| `ACT` | `Active` |
| `CLO` | `Closed` |
| `DFT` | `Default` |
| `FRB` | `Forbearance` |
| *(other)* | `UNKNOWN(<original>)` |

### Product status (`PROD_STAT_CD`)

| Legacy Code | Modern Value |
|-------------|-------------|
| `ACT` | `true` (boolean) |
| *(other)* | `false` (boolean) |

### Payment type (`PMT_TYP_CD`)

| Legacy Code | Modern Value |
|-------------|-------------|
| `REG` | `Regular` |
| `EXT` | `Extra` |
| `PRT` | `Partial` |
| `PRE` | `Prepayment` |
| *(other)* | `UNKNOWN(<original>)` |

### Payment status (`PMT_STAT_CD`)

| Legacy Code | Modern Value |
|-------------|-------------|
| `PST` | `Posted` |
| `REV` | `Reversed` |
| `NSF` | `NSF` |
| `PND` | `Pending` |
| *(other)* | `UNKNOWN(<original>)` |

### Property type (`PROP_TYP_CD`)

| Legacy Code | Modern Value |
|-------------|-------------|
| `SFR` | `Single Family` |
| `CND` | `Condominium` |
| `MFR` | `Multi-Family` |
| `TWN` | `Townhouse` |
| *(other)* | `UNKNOWN(<original>)` |

---

## Partitioning Strategy

| Table | Partition Column | Type | Rationale |
|-------|-----------------|------|-----------|
| `borrowers` | `state` | STRING | Low cardinality (~50 values); geographic compliance queries |
| `loan_products` | *(none)* | — | Very small table; partitioning would create excessive small files |
| `loan_accounts` | `origination_year` | INT | Vintage analysis is the primary analytical access pattern; year-level provides good partition granularity without excessive small files |
| `payments` | `payment_year` | INT | Time-range queries dominate payment analytics; monthly partitioning would be too fine-grained for this data volume |

All tables use Delta Lake with the following table properties:
- `delta.autoOptimize.optimizeWrite = true` — coalesces small files on write
- `delta.autoOptimize.autoCompact = true` — runs compaction asynchronously
- `delta.columnMapping.mode = name` — enables column rename/drop operations

---

## Execution Order

The pipeline must be run in strict dependency order because dimension tables must be loaded
before fact tables that reference them via FK lookups.

```
Step 1: 00_create_schema.sql      — Create the loan_warehouse schema
Step 2: 01_borrowers.sql           — Create borrowers table DDL
Step 3: 02_loan_products.sql       — Create loan_products table DDL
Step 4: 03_loan_accounts.sql       — Create loan_accounts table DDL
Step 5: 04_payments.sql            — Create payments table DDL
Step 6: ingest_borrowers.py        — Load borrower data (no dependencies)
Step 7: ingest_loan_products.py    — Load product data (no dependencies)
Step 8: ingest_loan_accounts.py    — Load loan data (depends on Steps 6 & 7)
Step 9: ingest_payments.py         — Load payment data (depends on Step 8)
Step 10: data_quality_checks.py    — Run post-migration validation
```

Steps 6 and 7 can run **in parallel** since they have no interdependency.

The `run_pipeline.py` orchestrator script executes Steps 6–9 sequentially in the correct
order. DDL (Steps 1–5) should be run separately as SQL notebooks before the ingestion.

---

## Pre-Migration Checklist

- [ ] Verify Unity Catalog access and permissions for `loan_warehouse` schema
- [ ] Export legacy CSV/Parquet files to `dbfs:/mnt/legacy-export/` mount point:
  - `CDW_BORR_MSTR/` (with header row)
  - `CDW_LN_PROD/` (with header row)
  - `CDW_LN_ACCT/` (with header row)
  - `CDW_PMT_HIST/` (with header row)
- [ ] Verify CSV column headers match legacy table column names exactly
- [ ] Run all DDL scripts (`databricks/ddl/00_*.sql` through `04_*.sql`) in order
- [ ] Confirm cluster has PySpark runtime >= 13.x (Databricks Runtime)
- [ ] Set `spark.sql.legacy.timeParserPolicy` to `CORRECTED` (set by scripts automatically)
- [ ] Verify `dbfs:/mnt/migration-reports/` directory exists for quality report output

---

## Running the Pipeline

### Option A: Orchestrator script (recommended)

```bash
spark-submit databricks/ingestion/run_pipeline.py
```

This runs all four ingestion steps in dependency order and reports a summary.

### Option B: Individual notebooks

Import each script as a Databricks notebook and run in order:

1. `databricks/ingestion/ingest_borrowers.py`
2. `databricks/ingestion/ingest_loan_products.py`
3. `databricks/ingestion/ingest_loan_accounts.py`
4. `databricks/ingestion/ingest_payments.py`

### Option C: Databricks Workflow

Create a multi-task Databricks Workflow:

```
Task 1: ingest_borrowers     ─┐
Task 2: ingest_loan_products  ├─→ Task 3: ingest_loan_accounts ─→ Task 4: ingest_payments ─→ Task 5: data_quality_checks
                              ─┘
```

Tasks 1 and 2 run in parallel; Task 3 depends on both; Task 4 depends on Task 3.

### Configuration overrides

All scripts accept these variables (set via Databricks widgets or edit the constants):

| Variable | Default | Description |
|----------|---------|-------------|
| `SOURCE_PATH` | `dbfs:/mnt/legacy-export/<TABLE>` | Source data location |
| `SOURCE_FORMAT` | `csv` | `csv` or `parquet` |
| `TARGET_TABLE` | `loan_warehouse.<table>` | Target Delta table name |
| `WRITE_MODE` | `overwrite` | `overwrite` or `append` |

---

## Post-Migration Validation

After ingestion completes, run the data quality framework:

```bash
spark-submit databricks/quality/data_quality_checks.py
```

This produces a `DATA_QUALITY_REPORT.md` at `dbfs:/mnt/migration-reports/` with:

### Check categories

1. **Row-count reconciliation** — Source row count must equal target row count for each table
2. **Null checks** — Required fields must have no NULL values
3. **Referential integrity** — All FK columns must resolve to valid parent rows
4. **Business rules:**
   - Active loans must have `current_balance > 0`
   - Closed loans must have a `maturity_date`
   - Payment component amounts should sum to `total_amount` (within 1 cent tolerance)
   - `delinquency_days` must be >= 0
   - `interest_rate` must be > 0
   - `origination_date` must be before `maturity_date`

### Quality gate

The pipeline is considered **PASS** only if all `ERROR`-severity checks pass. `WARNING`
checks (e.g., payment component sum) are reported but do not block the gate.

---

## Troubleshooting

| Symptom | Likely Cause | Resolution |
|---------|-------------|------------|
| `NULL` values in `borrower_id` | `BORR_ID` in loan data doesn't match any `external_id` in borrowers | Run borrower ingestion first; verify CSV export completeness |
| `NULL` values in `product_id` | `PROD_CD` in loan data not found in loan_products | Run product ingestion first; verify all product codes are exported |
| Date parsing returns all `NULL` | Source dates not in `MM/DD/YYYY` format | Check source date format; adjust `parse_date_mmddyyyy` pattern |
| Amount parsing returns all `NULL` | Unexpected characters in amount strings | Check for currency symbols (`$`), spaces, or alternative decimal separators |
| Row count mismatch | CSV header or encoding issues | Verify `header=true` and UTF-8 encoding; check for trailing empty rows |
| `UNKNOWN(...)` status values | Unmapped status codes in source data | Add new code mappings to `transforms.py` |

---

## Rollback Procedure

Delta Lake supports time travel, making rollback straightforward:

```sql
-- View table history
DESCRIBE HISTORY loan_warehouse.borrowers;

-- Restore to version before migration
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF <version_number>;
RESTORE TABLE loan_warehouse.loan_products TO VERSION AS OF <version_number>;
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF <version_number>;
RESTORE TABLE loan_warehouse.payments TO VERSION AS OF <version_number>;
```

For a full rollback to pre-migration state, drop and recreate the schema:

```sql
DROP SCHEMA IF EXISTS loan_warehouse CASCADE;
```

Then re-run the DDL scripts to recreate empty tables.
