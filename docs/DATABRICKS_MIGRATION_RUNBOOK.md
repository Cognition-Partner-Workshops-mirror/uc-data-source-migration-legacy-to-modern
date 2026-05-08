# Databricks Migration Runbook

## Overview

This runbook documents the complete migration of loan management data from a **legacy CDW (Corporate Data Warehouse)** schema to a **modern Delta Lake** schema on Databricks. It covers every transformation decision, column mapping, type conversion, partitioning choice, and the recommended execution order.

---

## 1. Source System Summary

The legacy CDW stores all data in **four tables** using all-`VARCHAR` columns, cryptic abbreviated names, no foreign keys, and string-encoded dates/amounts.

| Legacy Table | Description | Row Count (seed) |
|---|---|---|
| `CDW_BORR_MSTR` | Borrower master | 5 |
| `CDW_LN_PROD` | Loan products | 5 |
| `CDW_LN_ACCT` | Loan accounts (denormalized) | 5 |
| `CDW_PMT_HIST` | Payment history | 10 |

### Key Legacy Problems

| Problem | Example |
|---------|---------|
| All-VARCHAR typing | `LN_CURR_BAL VARCHAR(15)` holds `"271,432.56"` |
| Cryptic names | `BORR_FST_NM` = borrower first name |
| Denormalization | `CDW_LN_ACCT` embeds `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |
| String dates | `"03/15/1978"` (MM/DD/YYYY format) |
| Abbreviation codes | `ACT`, `CLO`, `DFT`, `FRB` for loan status |
| No foreign keys | `CDW_LN_ACCT.BORR_ID` is just a string, not enforced |

---

## 2. Target Schema (Delta Lake)

The modern schema lives in the `loan_warehouse` database with four normalized Delta tables.

### 2.1 borrowers

| Modern Column | Type | Legacy Source | Transformation |
|---|---|---|---|
| `id` | BIGINT (auto) | — | Generated identity |
| `external_id` | STRING | `BORR_ID` | Direct copy |
| `first_name` | STRING | `BORR_FST_NM` | Direct copy |
| `last_name` | STRING | `BORR_LST_NM` | Direct copy |
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
| `credit_score` | INT | `BORR_CRDT_SCR` | Parse string → integer |
| `employment_status` | STRING | `BORR_EMP_STAT` | Direct copy |
| `annual_income` | DECIMAL(12,2) | `BORR_ANN_INCM` | Remove commas, parse → decimal |
| `status` | STRING | `BORR_STAT_CD` | Expand: ACT→ACTIVE, INA→INACTIVE |
| `created_at` | TIMESTAMP | `BORR_CRET_DT` | Parse `MM/DD/YYYY` → timestamp |
| `updated_at` | TIMESTAMP | `BORR_UPDT_DT` | Parse `MM/DD/YYYY` → timestamp |
| *(dropped)* | — | `BORR_REC_TYP` | Record type flag; no modern equivalent |

### 2.2 loan_products

| Modern Column | Type | Legacy Source | Transformation |
|---|---|---|---|
| `id` | BIGINT (auto) | — | Generated identity |
| `code` | STRING | `PROD_CD` | Direct copy |
| `name` | STRING | `PROD_DESC_TXT` | Direct copy |
| `type` | STRING | `PROD_TYP_CD` | Direct copy |
| `term_months` | INT | `PROD_TERM_MOS` | Parse string → integer |
| `rate_type` | STRING | `PROD_RT_TYP` | Direct copy |
| `min_amount` | DECIMAL(12,2) | `PROD_MIN_AMT` | Remove commas, parse → decimal |
| `max_amount` | DECIMAL(12,2) | `PROD_MAX_AMT` | Remove commas, parse → decimal |
| `is_active` | BOOLEAN | `PROD_STAT_CD` | ACT→true, INA→false |
| `effective_date` | DATE | `PROD_EFF_DT` | Parse `MM/DD/YYYY` → DATE |
| `expiration_date` | DATE | `PROD_EXP_DT` | Parse `MM/DD/YYYY` → DATE |

### 2.3 loan_accounts

| Modern Column | Type | Legacy Source | Transformation |
|---|---|---|---|
| `id` | BIGINT (auto) | — | Generated identity |
| `account_number` | STRING | `LN_ACCT_NBR` | Direct copy |
| `borrower_id` | BIGINT (FK) | `BORR_ID` | Lookup `borrowers.id` by `external_id` |
| `product_id` | BIGINT (FK) | `PROD_CD` | Lookup `loan_products.id` by `code` |
| `original_amount` | DECIMAL(12,2) | `LN_ORIG_AMT` | Remove commas, parse → decimal |
| `current_balance` | DECIMAL(12,2) | `LN_CURR_BAL` | Remove commas, parse → decimal |
| `interest_rate` | DECIMAL(5,3) | `LN_INT_RT` | Parse string → decimal |
| `term_months` | INT | `LN_TERM_MOS` | Parse string → integer |
| `monthly_payment` | DECIMAL(10,2) | `LN_PMT_AMT` | Remove commas, parse → decimal |
| `origination_date` | DATE | `LN_ORIG_DT` | Parse `MM/DD/YYYY` → DATE |
| `maturity_date` | DATE | `LN_MAT_DT` | Parse `MM/DD/YYYY` → DATE |
| `first_payment_date` | DATE | `LN_1ST_PMT_DT` | Parse `MM/DD/YYYY` → DATE |
| `next_payment_date` | DATE | `LN_NXT_PMT_DT` | Parse `MM/DD/YYYY` → DATE |
| `status` | STRING | `LN_STAT_CD` | Expand: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| `delinquency_days` | INT | `LN_DLQ_DAYS` | Parse string → integer |
| `escrow_balance` | DECIMAL(10,2) | `LN_ESCROW_BAL` | Remove commas, parse → decimal |
| `ltv_percent` | DECIMAL(5,2) | `LN_LTV_PCT` | Parse string → decimal |
| `property_address` | STRING | `PROP_ADDR_LN1` | Direct copy |
| `property_city` | STRING | `PROP_CTY_NM` | Direct copy |
| `property_state` | STRING | `PROP_ST_CD` | Direct copy |
| `property_zip` | STRING | `PROP_ZIP_CD` | Direct copy |
| `property_type` | STRING | `PROP_TYP_CD` | Expand: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| `appraised_value` | DECIMAL(12,2) | `PROP_APRS_VAL` | Remove commas, parse → decimal |
| `created_at` | TIMESTAMP | `LN_CRET_DT` | Parse `MM/DD/YYYY` → timestamp |
| `updated_at` | TIMESTAMP | `LN_UPDT_DT` | Parse `MM/DD/YYYY` → timestamp |
| *(dropped)* | — | `BORR_FST_NM` | Denormalized; use borrower FK |
| *(dropped)* | — | `BORR_LST_NM` | Denormalized; use borrower FK |
| *(dropped)* | — | `BORR_SSN_LST4` | Denormalized; use borrower FK |

### 2.4 payments

| Modern Column | Type | Legacy Source | Transformation |
|---|---|---|---|
| `id` | BIGINT (auto) | — | Generated identity |
| `legacy_sequence_nbr` | STRING | `PMT_SEQ_NBR` | Preserved for audit trail |
| `loan_account_id` | BIGINT (FK) | `LN_ACCT_NBR` | Lookup `loan_accounts.id` by `account_number` |
| `payment_date` | DATE | `PMT_DT` | Parse `MM/DD/YYYY` → DATE |
| `total_amount` | DECIMAL(10,2) | `PMT_AMT` | Remove commas, parse → decimal |
| `principal_amount` | DECIMAL(10,2) | `PMT_PRIN_AMT` | Remove commas, parse → decimal |
| `interest_amount` | DECIMAL(10,2) | `PMT_INT_AMT` | Remove commas, parse → decimal |
| `escrow_amount` | DECIMAL(10,2) | `PMT_ESCROW_AMT` | Remove commas, parse → decimal |
| `late_fee` | DECIMAL(10,2) | `PMT_LATE_FEE` | Remove commas, parse → decimal |
| `type` | STRING | `PMT_TYP_CD` | Expand: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| `status` | STRING | `PMT_STAT_CD` | Expand: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| `received_date` | DATE | `PMT_RECV_DT` | Parse `MM/DD/YYYY` → DATE |
| `processed_date` | DATE | `PMT_PROC_DT` | Parse `MM/DD/YYYY` → DATE |
| `created_at` | TIMESTAMP | `PMT_CRET_DT` | Parse `MM/DD/YYYY` → timestamp |
| `updated_at` | TIMESTAMP | `PMT_UPDT_DT` | Parse `MM/DD/YYYY` → timestamp |

---

## 3. Transformation Decisions

### 3.1 Date Handling

All legacy date columns store `MM/DD/YYYY` strings in VARCHAR. The PySpark ingestion scripts use `to_date(col, "MM/dd/yyyy")` for DATE targets and `to_timestamp(col, "MM/dd/yyyy")` for TIMESTAMP targets (defaulting to midnight `00:00:00`).

**Rationale:** The legacy system has no time component in its date strings. Converting to TIMESTAMP with midnight default preserves information without fabricating data. Future updates from the modern application will write full timestamps.

### 3.2 Amount Parsing

Amount strings like `"285,000"` and `"271,432.56"` are parsed by stripping commas with `regexp_replace(col, ",", "")` then casting to `DecimalType`. Precision/scale choices:

| Use Case | Precision | Scale | Rationale |
|----------|-----------|-------|-----------|
| Loan amounts, income, appraised value | 12 | 2 | Up to $9,999,999,999.99 — covers all residential + commercial loans |
| Payment amounts, escrow, fees | 10 | 2 | Up to $99,999,999.99 — covers any single payment |
| Interest rate | 5 | 3 | Up to 99.999% — covers all rate scenarios |
| LTV percent | 5 | 2 | Up to 999.99% — covers underwater loans |

### 3.3 Status Code Expansion

Legacy abbreviated codes are expanded to human-readable values:

| Domain | Code | Expanded Value |
|--------|------|----------------|
| Loan Status | ACT | ACTIVE |
| Loan Status | CLO | CLOSED |
| Loan Status | DFT | DEFAULT |
| Loan Status | FRB | FORBEARANCE |
| Borrower Status | ACT | ACTIVE |
| Borrower Status | INA | INACTIVE |
| Payment Type | REG | REGULAR |
| Payment Type | EXT | EXTRA |
| Payment Type | PRT | PARTIAL |
| Payment Type | PRE | PREPAYMENT |
| Payment Status | PST | POSTED |
| Payment Status | REV | REVERSED |
| Payment Status | NSF | NSF |
| Payment Status | PND | PENDING |
| Property Type | SFR | Single Family |
| Property Type | CND | Condominium |
| Property Type | MFR | Multi-Family |
| Property Type | TWN | Townhouse |
| Product Status | ACT | true (boolean) |
| Product Status | INA | false (boolean) |

**Unknown codes** are passed through unchanged and flagged in the quality report.

### 3.4 Denormalization Removal

`CDW_LN_ACCT` embeds three borrower columns (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) that duplicate data from `CDW_BORR_MSTR`. These are **dropped** in the modern schema; the `borrower_id` FK replaces them. This eliminates update anomalies and reduces storage.

### 3.5 FK Resolution

Legacy tables use string-based natural keys with no enforced relationships. The ingestion pipeline resolves these to surrogate BIGINT FKs via left joins:

| Child Column | Lookup Table | Lookup Column | Notes |
|---|---|---|---|
| `loan_accounts.borrower_id` | `borrowers` | `external_id` | Must ingest borrowers first |
| `loan_accounts.product_id` | `loan_products` | `code` | Must ingest loan_products first |
| `payments.loan_account_id` | `loan_accounts` | `account_number` | Must ingest loan_accounts first |

Unresolvable FKs result in NULL values and are logged in error tables — records are **never silently dropped**.

### 3.6 Dropped Columns

| Column | Table | Reason |
|--------|-------|--------|
| `BORR_REC_TYP` | CDW_BORR_MSTR | Internal record-type flag with no business meaning in the modern schema |
| `BORR_FST_NM` | CDW_LN_ACCT | Denormalized — use borrower FK instead |
| `BORR_LST_NM` | CDW_LN_ACCT | Denormalized — use borrower FK instead |
| `BORR_SSN_LST4` | CDW_LN_ACCT | Denormalized — use borrower FK instead |

---

## 4. Partitioning Strategy

| Table | Partition Column | Rationale |
|-------|------------------|-----------|
| `borrowers` | `status` | Queries often filter by active vs. inactive borrowers; low cardinality keeps partition count manageable |
| `loan_products` | *(none)* | Small reference table (<100 rows); partitioning adds overhead with no benefit |
| `loan_accounts` | `status` | Portfolio analysis frequently segments by loan status (active, closed, default, forbearance); enables partition pruning |
| `payments` | `payment_date` | Payment queries are almost always time-bounded (monthly statements, quarterly reviews); DATE partitioning enables efficient range scans |

All tables enable `delta.autoOptimize.optimizeWrite` and `delta.autoOptimize.autoCompact` to reduce small-file overhead.

---

## 5. Execution Order

Run the pipeline components **in this exact order** — each step depends on its predecessors for FK resolution.

### Step 0: Create Database

```sql
-- databricks/ddl/00_create_database.sql
CREATE DATABASE IF NOT EXISTS loan_warehouse;
```

### Step 1: Create Tables

Run DDL scripts in numeric order:

```
databricks/ddl/01_borrowers.sql
databricks/ddl/02_loan_products.sql
databricks/ddl/03_loan_accounts.sql
databricks/ddl/04_payments.sql
```

### Step 2: Export Legacy Data

Export the four legacy tables from the CDW as CSV or Parquet files to the staging mount:

```
dbfs:/mnt/legacy_exports/CDW_BORR_MSTR/
dbfs:/mnt/legacy_exports/CDW_LN_PROD/
dbfs:/mnt/legacy_exports/CDW_LN_ACCT/
dbfs:/mnt/legacy_exports/CDW_PMT_HIST/
```

### Step 3: Run Ingestion Pipeline

Option A — run the full orchestrator:

```bash
spark-submit databricks/ingestion/run_full_pipeline.py
```

Option B — run each step individually (useful for debugging):

```bash
# 3a. Borrowers (no dependencies)
spark-submit databricks/ingestion/ingest_borrowers.py

# 3b. Loan products (no dependencies — can run in parallel with 3a)
spark-submit databricks/ingestion/ingest_loan_products.py

# 3c. Loan accounts (depends on 3a + 3b)
spark-submit databricks/ingestion/ingest_loan_accounts.py

# 3d. Payments (depends on 3c)
spark-submit databricks/ingestion/ingest_payments.py
```

### Step 4: Run Data Quality Checks

```bash
spark-submit databricks/quality/data_quality_checks.py
```

This produces `DATA_QUALITY_REPORT.md` at `/dbfs/mnt/loan_warehouse/DATA_QUALITY_REPORT.md`.

### Step 5: Review Quality Report

Check the generated `DATA_QUALITY_REPORT.md` for:
- Row count mismatches between source and target
- NULL values in required columns
- Orphaned FK references
- Business rule violations

**Do not proceed to production cutover if any checks fail.**

---

## 6. Error Handling Strategy

The pipeline follows a **log-don't-drop** philosophy:

1. **Per-row error tracking:** Every ingestion script adds a `_parse_errors` array column that collects warnings for each row (e.g., "BORR_DOB_DT failed date parse").
2. **Error tables:** Rows with any parse warnings are persisted to `loan_warehouse._<table>_ingestion_errors` Delta tables for review.
3. **No silent drops:** Records with parse failures are still written to the target table (with NULL in the affected column) rather than being discarded.
4. **Console logging:** Summary counts and error details are printed to stdout for pipeline monitoring.
5. **Quality gate:** The `data_quality_checks.py` module serves as the final gate before production use.

---

## 7. Rollback Procedure

Since all target tables use Delta Lake, time travel provides a built-in rollback:

```sql
-- Restore to the state before migration
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.loan_products TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.payments TO VERSION AS OF 0;
```

Or simply drop and recreate:

```sql
DROP TABLE IF EXISTS loan_warehouse.payments;
DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
DROP TABLE IF EXISTS loan_warehouse.loan_products;
DROP TABLE IF EXISTS loan_warehouse.borrowers;
-- Re-run DDL scripts
```

---

## 8. Post-Migration Recommendations

1. **Re-encrypt SSN hashes:** The `ssn_hash` column is carried over as-is from `BORR_SSN_ENCR`. Evaluate re-encrypting with a modern algorithm.
2. **Add column-level statistics:** Run `ANALYZE TABLE` on all four tables to improve query planning.
3. **Set up Delta Live Tables (DLT):** For ongoing incremental ingestion from the CDW, convert the batch scripts to a DLT pipeline with expectations.
4. **Implement Change Data Feed (CDF):** Enable `delta.enableChangeDataFeed` on frequently updated tables (loan_accounts, payments) for downstream consumers.
5. **Archive legacy exports:** After successful migration and validation, archive the CSV/Parquet staging files to cold storage.
