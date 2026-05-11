# Databricks Migration Runbook — CDW Legacy to Modern Loan Warehouse

## Table of Contents

1. [Overview](#overview)
2. [Source System Summary](#source-system-summary)
3. [Column Mapping Reference](#column-mapping-reference)
4. [Type Conversion Decisions](#type-conversion-decisions)
5. [Status Code Expansion Reference](#status-code-expansion-reference)
6. [Partitioning Strategy](#partitioning-strategy)
7. [Execution Order](#execution-order)
8. [Pre-Migration Checklist](#pre-migration-checklist)
9. [Running the Pipeline](#running-the-pipeline)
10. [Post-Migration Validation](#post-migration-validation)
11. [Rollback Procedure](#rollback-procedure)
12. [Troubleshooting](#troubleshooting)

---

## Overview

This runbook documents the full migration of the legacy CDW (Corporate Data Warehouse)
loan management tables to a modern, strongly-typed Delta Lake schema on Databricks.

**Source:** 4 legacy CDW tables with all-VARCHAR columns, cryptic names, no foreign keys,
and status code abbreviations.

**Target:** 4 normalised Delta Lake tables with proper Spark SQL types, meaningful column
names, enforced constraints, and partition strategies optimised for loan analytics.

| Legacy Table | Target Table | Record Type |
|--------------|--------------|-------------|
| CDW_BORR_MSTR | `loan_warehouse.borrowers` | Dimension |
| CDW_LN_PROD | `loan_warehouse.loan_products` | Dimension |
| CDW_LN_ACCT | `loan_warehouse.loan_accounts` | Fact |
| CDW_PMT_HIST | `loan_warehouse.payments` | Fact |

---

## Source System Summary

The legacy CDW tables exhibit the following characteristics that the migration addresses:

| Issue | Description | Resolution |
|-------|-------------|------------|
| All-VARCHAR typing | Every column is VARCHAR regardless of actual data type | Converted to DATE, DECIMAL, INT, BOOLEAN, TIMESTAMP |
| Cryptic names | `BORR_FST_NM`, `LN_CURR_BAL`, `PMT_ESCROW_AMT` | Renamed to `first_name`, `current_balance`, `escrow_amount` |
| No foreign keys | Tables are loosely related by string IDs with no constraints | FK relationships enforced via surrogate BIGINT keys |
| Denormalized data | CDW_LN_ACCT embeds borrower fields (name, SSN last 4) | Redundant columns dropped; borrower FK used instead |
| Status abbreviations | ACT, CLO, DFT, FRB, PST, REV, NSF, PND | Expanded to full readable values (ACTIVE, CLOSED, etc.) |
| Date strings | Stored as MM/DD/YYYY varchar | Parsed to Spark DATE / TIMESTAMP types |
| Amount strings | Stored with commas ("285,000") as varchar | Parsed to DECIMAL with appropriate precision/scale |

---

## Column Mapping Reference

### CDW_BORR_MSTR → `loan_warehouse.borrowers`

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| BORR_ID | external_id | VARCHAR → STRING | Direct copy |
| BORR_FST_NM | first_name | VARCHAR → STRING | Direct copy |
| BORR_LST_NM | last_name | VARCHAR → STRING | Direct copy |
| BORR_MID_INIT | middle_initial | VARCHAR → STRING | Direct copy |
| BORR_SSN_ENCR | ssn_hash | VARCHAR → STRING | Direct copy (re-encrypt recommended) |
| BORR_DOB_DT | date_of_birth | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| BORR_ADDR_LN1 | address_line1 | VARCHAR → STRING | Direct copy |
| BORR_ADDR_LN2 | address_line2 | VARCHAR → STRING | Direct copy |
| BORR_CTY_NM | city | VARCHAR → STRING | Direct copy |
| BORR_ST_CD | state | VARCHAR → STRING | Direct copy |
| BORR_ZIP_CD | zip_code | VARCHAR → STRING | Direct copy |
| BORR_PH_NBR | phone | VARCHAR → STRING | Direct copy |
| BORR_EMAIL_ADDR | email | VARCHAR → STRING | Direct copy |
| BORR_CRDT_SCR | credit_score | VARCHAR → INT | `col.cast(IntegerType())` |
| BORR_EMP_STAT | employment_status | VARCHAR → STRING | Direct copy |
| BORR_ANN_INCM | annual_income | VARCHAR → DECIMAL(12,2) | Remove commas, cast |
| BORR_CRET_DT | created_at | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| BORR_UPDT_DT | updated_at | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| BORR_STAT_CD | status | VARCHAR → STRING | ACT→ACTIVE, INA→INACTIVE |
| BORR_REC_TYP | *(dropped)* | — | Not needed in modern schema |

### CDW_LN_PROD → `loan_warehouse.loan_products`

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| PROD_CD | code | VARCHAR → STRING | Direct copy (natural key) |
| PROD_DESC_TXT | name | VARCHAR → STRING | Direct copy |
| PROD_TYP_CD | type | VARCHAR → STRING | Direct copy |
| PROD_TERM_MOS | term_months | VARCHAR → INT | `col.cast(IntegerType())` |
| PROD_RT_TYP | rate_type | VARCHAR → STRING | Direct copy |
| PROD_MIN_AMT | min_amount | VARCHAR → DECIMAL(12,2) | Remove commas, cast |
| PROD_MAX_AMT | max_amount | VARCHAR → DECIMAL(12,2) | Remove commas, cast |
| PROD_STAT_CD | is_active | VARCHAR → BOOLEAN | ACT→true, INA→false |
| PROD_EFF_DT | effective_date | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| PROD_EXP_DT | expiration_date | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |

### CDW_LN_ACCT → `loan_warehouse.loan_accounts`

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| LN_ACCT_NBR | account_number | VARCHAR → STRING | Direct copy |
| BORR_ID | borrower_id | VARCHAR → BIGINT | FK lookup via borrowers.external_id |
| BORR_FST_NM | *(dropped)* | — | Denormalized; use borrower FK |
| BORR_LST_NM | *(dropped)* | — | Denormalized; use borrower FK |
| BORR_SSN_LST4 | *(dropped)* | — | Denormalized; use borrower FK |
| PROD_CD | product_id | VARCHAR → BIGINT | FK lookup via loan_products.code |
| LN_ORIG_AMT | original_amount | VARCHAR → DECIMAL(12,2) | Remove commas, cast |
| LN_CURR_BAL | current_balance | VARCHAR → DECIMAL(12,2) | Remove commas, cast |
| LN_INT_RT | interest_rate | VARCHAR → DECIMAL(5,3) | Cast string → decimal |
| LN_TERM_MOS | term_months | VARCHAR → INT | Cast string → integer |
| LN_PMT_AMT | monthly_payment | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| LN_ORIG_DT | origination_date | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| LN_MAT_DT | maturity_date | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| LN_1ST_PMT_DT | first_payment_date | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| LN_NXT_PMT_DT | next_payment_date | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| LN_STAT_CD | status | VARCHAR → STRING | ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| LN_DLQ_DAYS | delinquency_days | VARCHAR → INT | Cast string → integer |
| LN_ESCROW_BAL | escrow_balance | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| LN_LTV_PCT | ltv_percent | VARCHAR → DECIMAL(5,2) | Cast string → decimal |
| PROP_ADDR_LN1 | property_address | VARCHAR → STRING | Direct copy |
| PROP_CTY_NM | property_city | VARCHAR → STRING | Direct copy |
| PROP_ST_CD | property_state | VARCHAR → STRING | Direct copy |
| PROP_ZIP_CD | property_zip | VARCHAR → STRING | Direct copy |
| PROP_TYP_CD | property_type | VARCHAR → STRING | SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| PROP_APRS_VAL | appraised_value | VARCHAR → DECIMAL(12,2) | Remove commas, cast |
| LN_CRET_DT | created_at | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| LN_UPDT_DT | updated_at | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |

### CDW_PMT_HIST → `loan_warehouse.payments`

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| PMT_SEQ_NBR | legacy_sequence_nbr | VARCHAR → STRING | Preserved for traceability |
| LN_ACCT_NBR | loan_account_id | VARCHAR → BIGINT | FK lookup via loan_accounts.account_number |
| PMT_DT | payment_date | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| PMT_AMT | total_amount | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| PMT_PRIN_AMT | principal_amount | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| PMT_INT_AMT | interest_amount | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| PMT_ESCROW_AMT | escrow_amount | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| PMT_LATE_FEE | late_fee | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| PMT_TYP_CD | type | VARCHAR → STRING | REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| PMT_STAT_CD | status | VARCHAR → STRING | PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| PMT_RECV_DT | received_date | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| PMT_PROC_DT | processed_date | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| PMT_CRET_DT | created_at | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| PMT_UPDT_DT | updated_at | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| *(derived)* | payment_year | — | `year(payment_date)` — for partitioning |

---

## Type Conversion Decisions

| Source Pattern | Target Type | Rationale |
|----------------|-------------|-----------|
| Date strings `MM/DD/YYYY` | `DATE` | Native date type enables date arithmetic, filtering, and partition pruning |
| Timestamp strings `MM/DD/YYYY` | `TIMESTAMP` | Audit columns (created_at, updated_at) use TIMESTAMP for time precision; midnight assumed since source lacks time component |
| Amount strings `"285,000"` | `DECIMAL(12,2)` | Sufficient for loan amounts up to 9,999,999,999.99; avoids floating-point rounding |
| Interest rate strings `"5.250"` | `DECIMAL(5,3)` | Three decimal places preserve basis point precision |
| LTV percentage strings `"82.5"` | `DECIMAL(5,2)` | Two decimal places sufficient for percentage values |
| Integer strings (term, score, days) | `INT` | Native integer for aggregation performance |
| Status code abbreviations | `STRING` | Expanded to human-readable values for downstream analytics |
| Boolean-like status codes | `BOOLEAN` | ACT/INA for product status maps naturally to true/false |

---

## Status Code Expansion Reference

### Borrower Status (`BORR_STAT_CD`)
| Code | Expanded Value |
|------|---------------|
| ACT | ACTIVE |
| INA | INACTIVE |

### Loan Status (`LN_STAT_CD`)
| Code | Expanded Value |
|------|---------------|
| ACT | ACTIVE |
| CLO | CLOSED |
| DFT | DEFAULT |
| FRB | FORBEARANCE |

### Product Status (`PROD_STAT_CD`)
| Code | Expanded Value |
|------|---------------|
| ACT | true (boolean) |
| INA | false (boolean) |

### Payment Type (`PMT_TYP_CD`)
| Code | Expanded Value |
|------|---------------|
| REG | REGULAR |
| EXT | EXTRA |
| PRT | PARTIAL |
| PRE | PREPAYMENT |

### Payment Status (`PMT_STAT_CD`)
| Code | Expanded Value |
|------|---------------|
| PST | POSTED |
| REV | REVERSED |
| NSF | NSF |
| PND | PENDING |

### Property Type (`PROP_TYP_CD`)
| Code | Expanded Value |
|------|---------------|
| SFR | Single Family |
| CND | Condominium |
| MFR | Multi-Family |
| TWN | Townhouse |

---

## Partitioning Strategy

| Table | Partition Column(s) | Rationale |
|-------|---------------------|-----------|
| `borrowers` | *(none)* | Small dimension table; partitioning would create excessive small files |
| `loan_products` | *(none)* | Very small reference table (~5-20 rows); partitioning unnecessary |
| `loan_accounts` | `status` | Low cardinality (4 values: ACTIVE, CLOSED, DEFAULT, FORBEARANCE); most queries filter by status for portfolio analytics. Enables efficient partition pruning |
| `payments` | `payment_year` | Payment history grows monotonically; year partitioning gives good file sizes and enables time-range pruning for monthly/quarterly reports |

**Delta Lake Auto-Optimization** is enabled on all tables via table properties:
- `delta.autoOptimize.optimizeWrite = true` — Coalesces small files during writes
- `delta.autoOptimize.autoCompact = true` — Automatically compacts small files in background

---

## Execution Order

The pipeline **must** be executed in dependency order because fact tables require
foreign key lookups against previously loaded dimension tables.

```
Step 1: databricks/ddl/00_create_schema.sql     — Create loan_warehouse schema
Step 2: databricks/ddl/01_borrowers.sql          — Create borrowers table
Step 3: databricks/ddl/02_loan_products.sql      — Create loan_products table
Step 4: databricks/ddl/03_loan_accounts.sql      — Create loan_accounts table
Step 5: databricks/ddl/04_payments.sql           — Create payments table
Step 6: databricks/ingestion/ingest_borrowers.py — Load borrower dimension
Step 7: databricks/ingestion/ingest_loan_products.py — Load product dimension
Step 8: databricks/ingestion/ingest_loan_accounts.py — Load loan facts (needs Steps 6+7)
Step 9: databricks/ingestion/ingest_payments.py  — Load payment facts (needs Step 8)
Step 10: databricks/quality/data_quality_checks.py — Validate all tables
```

**Shortcut:** Run `databricks/ingestion/run_all_ingestion.py` to execute Steps 6-9
in the correct order automatically.

---

## Pre-Migration Checklist

Before running the migration pipeline, verify:

- [ ] **Source files are staged:** Legacy CSV/Parquet extracts are available at the
      configured `SOURCE_PATH` locations (default: `dbfs:/mnt/legacy-extract/`)
- [ ] **Databricks cluster is running:** Minimum configuration: Standard_DS3_v2
      or equivalent with Delta Lake runtime 13.0+
- [ ] **Unity Catalog access:** The executing user/service principal has `CREATE SCHEMA`
      and `CREATE TABLE` privileges in the target catalog
- [ ] **Network access:** Cluster can reach the mounted storage containing source files
- [ ] **Python dependencies:** `delta-spark` library available (included in Databricks
      Runtime by default)

---

## Running the Pipeline

### Option A: Databricks Notebooks (Interactive)

1. Import the `databricks/` directory into your Databricks workspace
2. Run the DDL scripts (00–04) in a SQL notebook, in order
3. Run `databricks/ingestion/run_all_ingestion.py` as a Python notebook
4. Run `databricks/quality/data_quality_checks.py` as a Python notebook
5. Review the generated `DATA_QUALITY_REPORT.md`

### Option B: Databricks Jobs (Automated)

Create a multi-task job with the following task chain:

```
Task 1: DDL Setup (SQL task — run all DDL scripts)
   ↓
Task 2: Ingestion (Python task — run_all_ingestion.py)
   ↓
Task 3: Quality Checks (Python task — data_quality_checks.py)
```

Configure Task 3 to fail the job if the exit code is non-zero (quality check failure).

### Option C: CLI / dbx

```bash
# Upload scripts to DBFS
databricks fs cp -r databricks/ dbfs:/migration-pipeline/

# Run via databricks-cli
databricks jobs create --json @job_config.json
databricks jobs run-now --job-id <JOB_ID>
```

---

## Post-Migration Validation

After the pipeline completes:

1. **Review the quality report:** Check `DATA_QUALITY_REPORT.md` for any FAIL results
2. **Spot-check data:** Run sample queries to compare legacy source with target:
   ```sql
   -- Compare a known borrower record
   SELECT * FROM loan_warehouse.borrowers WHERE external_id = 'B-10001';

   -- Verify loan account FK resolution
   SELECT la.account_number, b.first_name, b.last_name, lp.name as product_name
   FROM loan_warehouse.loan_accounts la
   JOIN loan_warehouse.borrowers b ON la.borrower_id = b.id
   JOIN loan_warehouse.loan_products lp ON la.product_id = lp.id;

   -- Check payment totals per loan
   SELECT la.account_number, COUNT(*) as payment_count,
          SUM(p.total_amount) as total_paid
   FROM loan_warehouse.payments p
   JOIN loan_warehouse.loan_accounts la ON p.loan_account_id = la.id
   GROUP BY la.account_number;
   ```
3. **Validate row counts:** Ensure source and target counts match exactly
4. **Check Delta Lake table health:**
   ```sql
   DESCRIBE HISTORY loan_warehouse.borrowers;
   DESCRIBE DETAIL loan_warehouse.loan_accounts;
   ```

---

## Rollback Procedure

Delta Lake supports time travel, making rollback straightforward:

```sql
-- Restore a table to its state before the migration
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF 0;

-- Or drop the entire schema and re-run
DROP SCHEMA IF EXISTS loan_warehouse CASCADE;
```

For a clean re-run, drop the schema and execute the pipeline from Step 1.

---

## Troubleshooting

| Symptom | Likely Cause | Resolution |
|---------|-------------|------------|
| `FileNotFoundException` on source path | Legacy extract not staged | Upload CSV/Parquet files to the configured `SOURCE_PATH` |
| NULL foreign keys after ingestion | Dimension tables not loaded before facts | Re-run in correct dependency order (borrowers → products → accounts → payments) |
| Date parse failures (NULLs in date columns) | Non-standard date format in source | Check source data for formats other than MM/DD/YYYY; adjust `to_date` pattern |
| Amount parse failures | Unexpected characters (currency symbols, spaces) | Extend `parse_amount_col` regex to strip additional characters |
| Duplicate rows in target | Pipeline run multiple times without MERGE | Use the MERGE-based `write_target` functions (default); avoid direct INSERT |
| Quality check exit code 1 | One or more business rules failed | Review `DATA_QUALITY_REPORT.md` for specific failures and investigate source data |
