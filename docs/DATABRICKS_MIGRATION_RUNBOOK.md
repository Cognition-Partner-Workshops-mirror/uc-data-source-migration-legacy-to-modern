# Databricks Migration Runbook

## Legacy CDW → Modern Delta Lake Loan Data Warehouse

**Version:** 1.0
**Date:** 2026-05-07
**Source System:** Corporate Data Warehouse (CDW) — H2/SQL legacy tables
**Target System:** Databricks Delta Lake (`loan_warehouse` schema)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Source Schema Summary](#2-source-schema-summary)
3. [Target Schema Summary](#3-target-schema-summary)
4. [Column Mapping Reference](#4-column-mapping-reference)
5. [Type Conversion Decisions](#5-type-conversion-decisions)
6. [Status Code Expansion](#6-status-code-expansion)
7. [Partitioning Strategy](#7-partitioning-strategy)
8. [Transformation Details](#8-transformation-details)
9. [Execution Order](#9-execution-order)
10. [Data Quality Validation](#10-data-quality-validation)
11. [Rollback Procedure](#11-rollback-procedure)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Overview

The loan-service application currently reads from four legacy CDW tables that exhibit
common data warehouse anti-patterns:

- **All columns are VARCHAR** — dates, amounts, integers, and booleans are stored as
  untyped strings.
- **Cryptic column names** — abbreviated conventions like `BORR_FST_NM`, `LN_CURR_BAL`,
  `PMT_ESCROW_AMT`.
- **Denormalized structures** — `CDW_LN_ACCT` duplicates borrower fields (`BORR_FST_NM`,
  `BORR_LST_NM`, `BORR_SSN_LST4`) instead of using a foreign key.
- **No referential integrity** — no FK constraints between tables.
- **Status code abbreviations** — `ACT`, `CLO`, `DFT`, `FRB` instead of readable values.

This pipeline migrates data into a normalised Delta Lake schema with proper types,
meaningful names, enforced constraints, and partitioning optimised for loan analytics.

---

## 2. Source Schema Summary

### CDW_BORR_MSTR (Borrower Master)
| Column | Type | Description |
|--------|------|-------------|
| BORR_ID | VARCHAR(20) | Primary key |
| BORR_FST_NM | VARCHAR(50) | First name |
| BORR_LST_NM | VARCHAR(50) | Last name |
| BORR_MID_INIT | VARCHAR(1) | Middle initial |
| BORR_SSN_ENCR | VARCHAR(100) | Encrypted SSN |
| BORR_DOB_DT | VARCHAR(10) | Date of birth (MM/DD/YYYY string) |
| BORR_ADDR_LN1/LN2 | VARCHAR(100) | Address lines |
| BORR_CTY_NM / BORR_ST_CD / BORR_ZIP_CD | VARCHAR | City, state, zip |
| BORR_PH_NBR | VARCHAR(15) | Phone |
| BORR_EMAIL_ADDR | VARCHAR(100) | Email |
| BORR_CRDT_SCR | VARCHAR(5) | Credit score as string |
| BORR_EMP_STAT | VARCHAR(20) | Employment status |
| BORR_ANN_INCM | VARCHAR(15) | Annual income as string with commas |
| BORR_CRET_DT / BORR_UPDT_DT | VARCHAR(10) | Created/updated dates as strings |
| BORR_STAT_CD | VARCHAR(5) | Status code (ACT, INA) |
| BORR_REC_TYP | VARCHAR(10) | Record type — **dropped in migration** |

### CDW_LN_PROD (Loan Products)
| Column | Type | Description |
|--------|------|-------------|
| PROD_CD | VARCHAR(10) | Product code (primary key) |
| PROD_DESC_TXT | VARCHAR(200) | Product description |
| PROD_TYP_CD | VARCHAR(5) | Type code (FXD, ARM, FHA, VA) |
| PROD_TERM_MOS | VARCHAR(5) | Term in months as string |
| PROD_RT_TYP | VARCHAR(10) | Rate type (FIXED, VARIABLE) |
| PROD_MIN_AMT / PROD_MAX_AMT | VARCHAR(15) | Min/max amounts as strings |
| PROD_STAT_CD | VARCHAR(5) | Status (ACT, INA) → mapped to boolean |
| PROD_EFF_DT / PROD_EXP_DT | VARCHAR(10) | Effective/expiry dates |

### CDW_LN_ACCT (Loan Accounts — Denormalized)
| Column | Type | Description |
|--------|------|-------------|
| LN_ACCT_NBR | VARCHAR(20) | Account number (primary key) |
| BORR_ID | VARCHAR(20) | Borrower reference (no FK enforced) |
| BORR_FST_NM / BORR_LST_NM / BORR_SSN_LST4 | VARCHAR | **Denormalized — dropped** |
| PROD_CD | VARCHAR(10) | Product reference (no FK enforced) |
| LN_ORIG_AMT / LN_CURR_BAL | VARCHAR(15) | Amounts as strings |
| LN_INT_RT | VARCHAR(8) | Interest rate as string |
| LN_TERM_MOS | VARCHAR(5) | Term in months |
| LN_PMT_AMT | VARCHAR(15) | Monthly payment as string |
| LN_ORIG_DT / LN_MAT_DT / LN_1ST_PMT_DT / LN_NXT_PMT_DT | VARCHAR(10) | Dates |
| LN_STAT_CD | VARCHAR(5) | Status (ACT, CLO, DFT, FRB) |
| LN_DLQ_DAYS | VARCHAR(5) | Delinquency days as string |
| LN_ESCROW_BAL | VARCHAR(15) | Escrow balance as string |
| LN_LTV_PCT | VARCHAR(8) | LTV ratio as string |
| PROP_* columns | VARCHAR | Property address and type |
| LN_CRET_DT / LN_UPDT_DT | VARCHAR(10) | Audit timestamps |

### CDW_PMT_HIST (Payment History)
| Column | Type | Description |
|--------|------|-------------|
| PMT_SEQ_NBR | VARCHAR(20) | Sequence number (primary key) |
| LN_ACCT_NBR | VARCHAR(20) | Loan account reference (no FK) |
| PMT_DT | VARCHAR(10) | Payment date |
| PMT_AMT / PMT_PRIN_AMT / PMT_INT_AMT / PMT_ESCROW_AMT / PMT_LATE_FEE | VARCHAR(15) | Amounts |
| PMT_TYP_CD | VARCHAR(5) | Type (REG, EXT, PRT, PRE) |
| PMT_STAT_CD | VARCHAR(5) | Status (PST, REV, NSF, PND) |
| PMT_RECV_DT / PMT_PROC_DT | VARCHAR(10) | Received/processed dates |
| PMT_CRET_DT / PMT_UPDT_DT | VARCHAR(10) | Audit timestamps |

---

## 3. Target Schema Summary

| Delta Table | Source | Partition Key | Row Count (Seed) |
|-------------|--------|---------------|------------------|
| `loan_warehouse.borrowers` | CDW_BORR_MSTR | `state` | 5 |
| `loan_warehouse.loan_products` | CDW_LN_PROD | *(none — small dimension)* | 5 |
| `loan_warehouse.loan_accounts` | CDW_LN_ACCT | `status` | 5 |
| `loan_warehouse.payments` | CDW_PMT_HIST | `payment_year` | 10 |

All tables use Delta Lake format with:
- `delta.autoOptimize.optimizeWrite = true`
- `delta.autoOptimize.autoCompact = true`
- `delta.enableChangeDataFeed = true`

---

## 4. Column Mapping Reference

### CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Modern Type | Transformation |
|---------------|---------------|-------------|----------------|
| BORR_ID | external_id | STRING | Direct copy |
| BORR_FST_NM | first_name | STRING | Direct copy |
| BORR_LST_NM | last_name | STRING | Direct copy |
| BORR_MID_INIT | middle_initial | STRING | Direct copy |
| BORR_SSN_ENCR | ssn_hash | STRING | Direct copy (re-encrypt recommended) |
| BORR_DOB_DT | date_of_birth | DATE | Parse MM/DD/YYYY |
| BORR_ADDR_LN1 | address_line1 | STRING | Direct copy |
| BORR_ADDR_LN2 | address_line2 | STRING | Direct copy |
| BORR_CTY_NM | city | STRING | Direct copy |
| BORR_ST_CD | state | STRING | Direct copy |
| BORR_ZIP_CD | zip_code | STRING | Direct copy |
| BORR_PH_NBR | phone | STRING | Direct copy |
| BORR_EMAIL_ADDR | email | STRING | Direct copy |
| BORR_CRDT_SCR | credit_score | INT | Parse string → integer |
| BORR_EMP_STAT | employment_status | STRING | Direct copy |
| BORR_ANN_INCM | annual_income | DECIMAL(12,2) | Remove commas, parse |
| BORR_CRET_DT | created_at | TIMESTAMP | Parse MM/DD/YYYY |
| BORR_UPDT_DT | updated_at | TIMESTAMP | Parse MM/DD/YYYY |
| BORR_STAT_CD | status | STRING | Expand code |
| BORR_REC_TYP | *(dropped)* | — | Not needed in modern schema |

### CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Modern Type | Transformation |
|---------------|---------------|-------------|----------------|
| PROD_CD | code | STRING | Direct copy |
| PROD_DESC_TXT | name | STRING | Direct copy |
| PROD_TYP_CD | type | STRING | Direct copy |
| PROD_TERM_MOS | term_months | INT | Parse string → integer |
| PROD_RT_TYP | rate_type | STRING | Direct copy |
| PROD_MIN_AMT | min_amount | DECIMAL(12,2) | Remove commas, parse |
| PROD_MAX_AMT | max_amount | DECIMAL(12,2) | Remove commas, parse |
| PROD_STAT_CD | is_active | BOOLEAN | ACT → true, INA → false |
| PROD_EFF_DT | effective_date | DATE | Parse MM/DD/YYYY |
| PROD_EXP_DT | expiration_date | DATE | Parse MM/DD/YYYY |

### CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Modern Type | Transformation |
|---------------|---------------|-------------|----------------|
| LN_ACCT_NBR | account_number | STRING | Direct copy |
| BORR_ID | borrower_id | BIGINT | FK lookup → borrowers |
| BORR_FST_NM | *(dropped)* | — | Denormalized; use FK |
| BORR_LST_NM | *(dropped)* | — | Denormalized; use FK |
| BORR_SSN_LST4 | *(dropped)* | — | Denormalized; use FK |
| PROD_CD | product_id | BIGINT | FK lookup → loan_products |
| LN_ORIG_AMT | original_amount | DECIMAL(12,2) | Remove commas, parse |
| LN_CURR_BAL | current_balance | DECIMAL(12,2) | Remove commas, parse |
| LN_INT_RT | interest_rate | DECIMAL(5,3) | Parse string |
| LN_TERM_MOS | term_months | INT | Parse string → integer |
| LN_PMT_AMT | monthly_payment | DECIMAL(10,2) | Remove commas, parse |
| LN_ORIG_DT | origination_date | DATE | Parse MM/DD/YYYY |
| LN_MAT_DT | maturity_date | DATE | Parse MM/DD/YYYY |
| LN_1ST_PMT_DT | first_payment_date | DATE | Parse MM/DD/YYYY |
| LN_NXT_PMT_DT | next_payment_date | DATE | Parse MM/DD/YYYY |
| LN_STAT_CD | status | STRING | Expand code |
| LN_DLQ_DAYS | delinquency_days | INT | Parse string → integer |
| LN_ESCROW_BAL | escrow_balance | DECIMAL(10,2) | Remove commas, parse |
| LN_LTV_PCT | ltv_percent | DECIMAL(5,2) | Parse string |
| PROP_ADDR_LN1 | property_address | STRING | Direct copy |
| PROP_CTY_NM | property_city | STRING | Direct copy |
| PROP_ST_CD | property_state | STRING | Direct copy |
| PROP_ZIP_CD | property_zip | STRING | Direct copy |
| PROP_TYP_CD | property_type | STRING | Expand code |
| PROP_APRS_VAL | appraised_value | DECIMAL(12,2) | Remove commas, parse |
| *(derived)* | origination_year | INT | year(origination_date) |
| LN_CRET_DT | created_at | TIMESTAMP | Parse MM/DD/YYYY |
| LN_UPDT_DT | updated_at | TIMESTAMP | Parse MM/DD/YYYY |

### CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Modern Type | Transformation |
|---------------|---------------|-------------|----------------|
| PMT_SEQ_NBR | legacy_sequence_nbr | STRING | Preserved for audit |
| LN_ACCT_NBR | loan_account_id | BIGINT | FK lookup → loan_accounts |
| PMT_DT | payment_date | DATE | Parse MM/DD/YYYY |
| PMT_AMT | total_amount | DECIMAL(10,2) | Remove commas, parse |
| PMT_PRIN_AMT | principal_amount | DECIMAL(10,2) | Remove commas, parse |
| PMT_INT_AMT | interest_amount | DECIMAL(10,2) | Remove commas, parse |
| PMT_ESCROW_AMT | escrow_amount | DECIMAL(10,2) | Remove commas, parse |
| PMT_LATE_FEE | late_fee | DECIMAL(10,2) | Remove commas, parse |
| PMT_TYP_CD | type | STRING | Expand code |
| PMT_STAT_CD | status | STRING | Expand code |
| PMT_RECV_DT | received_date | DATE | Parse MM/DD/YYYY |
| PMT_PROC_DT | processed_date | DATE | Parse MM/DD/YYYY |
| *(derived)* | payment_year | INT | year(payment_date) |
| PMT_CRET_DT | created_at | TIMESTAMP | Parse MM/DD/YYYY |
| PMT_UPDT_DT | updated_at | TIMESTAMP | Parse MM/DD/YYYY |

---

## 5. Type Conversion Decisions

| Source Pattern | Target Type | Conversion Logic | Rationale |
|----------------|-------------|------------------|-----------|
| MM/DD/YYYY string | `DATE` | `to_date(col, "MM/dd/yyyy")` | Standard Spark date parsing; NULL on failure |
| MM/DD/YYYY string → TIMESTAMP | `TIMESTAMP` | `to_timestamp(col, "MM/dd/yyyy")` | Midnight time for date-only legacy fields mapped to timestamp |
| Amount string with commas ("285,000") | `DECIMAL(12,2)` | Strip commas via `regexp_replace`, then cast | DECIMAL preserves exact financial amounts without float rounding |
| Interest rate string ("5.250") | `DECIMAL(5,3)` | Cast after trim | 3 decimal places capture basis-point precision |
| Percentage string ("82.5") | `DECIMAL(5,2)` | Cast after trim | 2 decimal places sufficient for LTV |
| Integer string ("360") | `INT` | Cast after trim | Term in months, delinquency days, credit score |
| Status abbreviation | `STRING` | Dictionary lookup | Expanded for readability; "Unknown" for unrecognised codes |
| Product status → boolean | `BOOLEAN` | ACT = true, else false | Binary active/inactive maps naturally to boolean |

**Design decision — DECIMAL over DOUBLE:** Financial amounts use `DECIMAL` to avoid
IEEE 754 floating-point rounding errors that would cause reconciliation mismatches.

**Design decision — NULL over default for failed parses:** When a date or amount string
cannot be parsed, the result is NULL rather than a sentinel value. The data quality
framework detects these NULLs on required fields and the quarantine mechanism prevents
them from reaching the target table.

---

## 6. Status Code Expansion

### Loan Status (LN_STAT_CD)
| Code | Expanded Value |
|------|---------------|
| ACT | Active |
| CLO | Closed |
| DFT | Default |
| FRB | Forbearance |

### Borrower Status (BORR_STAT_CD)
| Code | Expanded Value |
|------|---------------|
| ACT | Active |
| INA | Inactive |

### Payment Type (PMT_TYP_CD)
| Code | Expanded Value |
|------|---------------|
| REG | Regular |
| EXT | Extra |
| PRT | Partial |
| PRE | Prepayment |

### Payment Status (PMT_STAT_CD)
| Code | Expanded Value |
|------|---------------|
| PST | Posted |
| REV | Reversed |
| NSF | NSF |
| PND | Pending |

### Property Type (PROP_TYP_CD)
| Code | Expanded Value |
|------|---------------|
| SFR | Single Family |
| CND | Condominium |
| MFR | Multi-Family |
| TWN | Townhouse |

Unrecognised codes are mapped to a default string (`"Unknown"` or `"Other"`) rather than
NULL, so the record is not quarantined but the anomaly is visible in quality reports.

---

## 7. Partitioning Strategy

| Table | Partition Column | Rationale |
|-------|-----------------|-----------|
| `borrowers` | `state` | Regional portfolio analysis is a primary query pattern; ~50 distinct values keeps partition count manageable |
| `loan_products` | *(none)* | Small reference table (~10s of rows); partitioning adds overhead with no benefit |
| `loan_accounts` | `status` | Most queries filter by active/closed/default status; 4 partitions provide excellent pruning |
| `payments` | `payment_year` | Time-series queries (monthly statements, annual reports) benefit from year-level pruning; partition count grows slowly (1/year) |

**Design decision — `status` over `origination_year` for loan_accounts:**
While origination year provides good historical segmentation, the dominant access pattern
for operational dashboards is filtering by loan status (active loans, defaults, etc.).
An `origination_year` column is still included as a non-partition column for ad-hoc
historical queries. If both patterns are equally important, consider Z-ordering on
`origination_year` within each status partition.

---

## 8. Transformation Details

### 8.1 Denormalization Removal

The legacy `CDW_LN_ACCT` table embeds three borrower columns:
- `BORR_FST_NM` — borrower first name
- `BORR_LST_NM` — borrower last name
- `BORR_SSN_LST4` — last 4 of SSN

These are **dropped** in the modern schema. Instead, `loan_accounts.borrower_id` is a
foreign key resolved by joining `CDW_LN_ACCT.BORR_ID` to `borrowers.external_id`.

This eliminates data duplication and the risk of borrower data becoming inconsistent
across tables.

### 8.2 Foreign Key Resolution

The legacy schema has no enforced FK constraints. The ingestion pipeline resolves
references by joining on business keys:

| Relationship | Legacy Join | Modern FK |
|-------------|------------|-----------|
| Loan → Borrower | `CDW_LN_ACCT.BORR_ID = CDW_BORR_MSTR.BORR_ID` | `loan_accounts.borrower_id → borrowers.borrower_id` |
| Loan → Product | `CDW_LN_ACCT.PROD_CD = CDW_LN_PROD.PROD_CD` | `loan_accounts.product_id → loan_products.product_id` |
| Payment → Loan | `CDW_PMT_HIST.LN_ACCT_NBR = CDW_LN_ACCT.LN_ACCT_NBR` | `payments.loan_account_id → loan_accounts.loan_account_id` |

If a FK cannot be resolved (e.g., an orphaned BORR_ID), the row is **quarantined** with
a reason, not silently dropped.

### 8.3 Quarantine Strategy

Each table has a corresponding quarantine table (`_quarantine_borrowers`, etc.) that
captures:
- All original and transformed columns
- `_quarantine_reason` — human-readable explanation
- `_quarantine_ts` — timestamp of quarantine

Quarantine criteria per table:
- **borrowers:** NULL in external_id, first_name, or last_name
- **loan_products:** NULL in code, name, type, or rate_type
- **loan_accounts:** NULL in required fields OR unresolvable borrower/product FK
- **payments:** Unresolvable loan_account FK, unparseable date/amount

### 8.4 Lineage Columns

Every target table includes:
- `_migration_source` — name of the legacy source table
- `_migration_ts` — ingestion timestamp

These support audit and debugging without requiring external lineage tools.

---

## 9. Execution Order

The pipeline **must** run in this order due to FK dependencies:

```
Step 1: databricks/ddl/00_create_schema.sql     — Create loan_warehouse schema
Step 2: databricks/ddl/01_borrowers.sql          — Create borrowers table
Step 3: databricks/ddl/02_loan_products.sql      — Create loan_products table
Step 4: databricks/ddl/03_loan_accounts.sql      — Create loan_accounts table
Step 5: databricks/ddl/04_payments.sql           — Create payments table
Step 6: databricks/ingestion/run_pipeline.py     — Run full ingestion pipeline
  6a: ingest_borrowers.py                        — No dependencies
  6b: ingest_loan_products.py                    — No dependencies
  6c: ingest_loan_accounts.py                    — Requires 6a + 6b
  6d: ingest_payments.py                         — Requires 6c
Step 7: databricks/quality/data_quality_checks.py — Validate migrated data
```

Steps 6a and 6b can run in parallel. Steps 6c and 6d are sequential.

### Recommended Databricks Execution

**Option A: Databricks Notebook Workflow**
1. Create a Databricks workflow with tasks chained in dependency order.
2. Import each `.sql` file as a SQL task and each `.py` file as a Python task.
3. Set the DDL tasks as upstream dependencies of the ingestion tasks.

**Option B: Manual Execution**
1. Open a Databricks SQL editor and execute DDL files 00–04 in order.
2. Open a notebook, set cluster to a PySpark-enabled cluster, and `%run ./run_pipeline`.
3. Run `data_quality_checks.py` and review the generated `DATA_QUALITY_REPORT.md`.

### Pre-flight Checklist

- [ ] Legacy source files (CSV or Parquet) are available at the configured `SOURCE_PATH`
      locations under `/mnt/landing/legacy/`.
- [ ] The Databricks cluster has Delta Lake support (DBR 10+ recommended).
- [ ] The `loan_warehouse` schema does not already exist (or you intend to overwrite).
- [ ] Network connectivity to the landing zone storage is confirmed.

---

## 10. Data Quality Validation

After ingestion, run `databricks/quality/data_quality_checks.py` to validate:

| Category | Checks |
|----------|--------|
| **Row Count Reconciliation** | source_count == target_count + quarantine_count for each table |
| **Null Checks** | No NULLs in required columns (external_id, first_name, account_number, etc.) |
| **Referential Integrity** | loan_accounts.borrower_id exists in borrowers; loan_accounts.product_id exists in loan_products; payments.loan_account_id exists in loan_accounts |
| **Business Rules** | Active loans have balance > 0; origination_date < maturity_date; LTV in [0, 200]; credit score in [300, 850]; payment amounts > 0; payment components sum ≈ total |

The framework generates a `DATA_QUALITY_REPORT.md` with per-check PASS/FAIL results,
severity levels, and affected row counts.

### Expected Results for Seed Data

With the 5 borrowers, 5 products, 5 loans, and 10 payments in the seed data:
- All row counts should balance (0 quarantined records)
- No NULL violations expected
- All FK references should resolve
- All business rules should pass

---

## 11. Rollback Procedure

Delta Lake's time-travel capability allows instant rollback:

```sql
-- Restore a table to its state before migration
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.loan_products TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.payments TO VERSION AS OF 0;

-- Or drop the entire schema
DROP SCHEMA IF EXISTS loan_warehouse CASCADE;
```

Quarantine tables are append-only and preserved across rollbacks for audit purposes.

---

## 12. Troubleshooting

| Symptom | Likely Cause | Resolution |
|---------|-------------|------------|
| `Table not found: loan_warehouse.borrowers` during loan_accounts ingestion | DDL not executed or ingestion order wrong | Run DDL files 00–04 first, then ingestion in order |
| High quarantine count on loan_accounts | Borrower or product IDs in CDW_LN_ACCT don't match CDW_BORR_MSTR/CDW_LN_PROD | Check for leading/trailing whitespace, case mismatches in IDs |
| Dates parsing as NULL | Unexpected date format (e.g., YYYY-MM-DD instead of MM/DD/YYYY) | Update `parse_date()` format string in `transforms.py` |
| Amounts parsing as NULL | Unexpected thousands separator or currency symbols | Extend `parse_amount()` regex in `transforms.py` |
| `AnalysisException: cannot resolve column` | Schema drift between expected and actual source columns | Compare source file headers against `LEGACY_SCHEMA` in each ingest script |
| Payment component sum ≠ total_amount | Rounding in source data or undocumented fee components | Review quarantine table; may need to widen the tolerance in quality checks |
