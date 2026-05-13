# Databricks Migration Runbook — Legacy CDW → Delta Lake

## Overview

This runbook documents the migration of loan management data from the legacy Corporate Data Warehouse (CDW) with all-VARCHAR columns, cryptic names, and no constraints into a modern normalized Delta Lake schema on Databricks.

**Source System:** H2 in-memory database with 4 legacy tables (`CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST`)
**Target System:** Delta Lake tables in `loan_warehouse` database on Databricks
**Schema Definitions:** `databricks/ddl/`
**Ingestion Scripts:** `databricks/ingestion/`
**Quality Framework:** `databricks/quality/`

---

## 1. Transformation Decisions

### 1.1 Type Conversions

All legacy columns are `VARCHAR` (loose typing). The following type conversions are applied:

| Conversion | Legacy Format | Modern Type | Method | Edge Cases |
|-----------|--------------|-------------|--------|------------|
| **Date** | `MM/DD/YYYY` string | `DATE` / `TIMESTAMP` | `to_date(col, "MM/dd/yyyy")` | Returns `null` for unparseable values (e.g., `02/30/2020`, `N/A`, ISO format) |
| **Amount** | `"285,000"` or `"1,487.02"` with commas | `DECIMAL(12,2)` or `DECIMAL(10,2)` | Strip `$`, `%`, commas via regex, then cast | Returns `null` for non-numeric text (`N/A`, `PENDING`) |
| **Integer** | `"745"`, `"360"` | `INT` | Strip non-digits, cast | Returns `null` for non-numeric text |
| **Rate** | `"5.250"` | `DECIMAL(5,3)` | Strip noise chars, cast | Handles `%` suffix gracefully |
| **Percentage** | `"82.5"` | `DECIMAL(5,2)` | Strip noise chars, cast | Same as rate |

**Key principle:** No records are silently dropped. Unparseable values become `null` and are logged for investigation.

### 1.2 Status Code Expansion

Legacy status codes are abbreviated. The modern schema uses expanded readable values:

| Table | Legacy Column | Legacy Codes | Modern Column | Expanded Values |
|-------|--------------|-------------|---------------|-----------------|
| `CDW_BORR_MSTR` | `BORR_STAT_CD` | ACT, INA | `status` | ACTIVE, INACTIVE |
| `CDW_LN_PROD` | `PROD_STAT_CD` | ACT, INA | `is_active` | true, false (boolean) |
| `CDW_LN_ACCT` | `LN_STAT_CD` | ACT, CLO, DFT, FRB | `status` | ACTIVE, CLOSED, DEFAULT, FORBEARANCE |
| `CDW_LN_ACCT` | `PROP_TYP_CD` | SFR, CND, MFR, TWN | `property_type` | Single Family, Condominium, Multi-Family, Townhouse |
| `CDW_PMT_HIST` | `PMT_TYP_CD` | REG, EXT, PRT, PRE | `type` | REGULAR, EXTRA, PARTIAL, PREPAYMENT |
| `CDW_PMT_HIST` | `PMT_STAT_CD` | PST, REV, NSF, PND | `status` | POSTED, REVERSED, NSF, PENDING |

**Unmapped codes** are preserved as-is (not converted to null) so they remain visible for investigation.

### 1.3 Denormalization Removal

The legacy `CDW_LN_ACCT` table embeds borrower data (first name, last name, SSN last-4) directly in the loan record. The modern schema normalizes this:

- `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` → **dropped** from `loan_accounts`
- `BORR_ID` → resolved to `borrower_id` (FK to `borrowers.id`) via `external_id` lookup
- `PROD_CD` → resolved to `product_id` (FK to `loan_products.id`) via `code` lookup
- `LN_ACCT_NBR` → resolved to `loan_account_id` (FK to `loan_accounts.id`) in payments

### 1.4 Partitioning Strategy

| Table | Partition Column | Rationale |
|-------|-----------------|-----------|
| `borrowers` | `status` | Most queries filter active borrowers; low cardinality (2 values) |
| `loan_products` | *(none)* | Small reference table (<100 rows); partitioning adds overhead |
| `loan_accounts` | `status` | Common filtering by ACTIVE/CLOSED/DEFAULT; 4 partitions |
| `payments` | `status` | Separates POSTED from REVERSED/NSF for reconciliation queries |

All tables use Delta Lake `autoOptimize` (auto-compaction and optimized writes).

---

## 2. Column Mapping Reference

### 2.1 CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|--------------|---------------|-------------|----------------|
| `BORR_ID` | `external_id` | VARCHAR → STRING | Direct copy |
| `BORR_FST_NM` | `first_name` | VARCHAR → STRING | Trim whitespace |
| `BORR_LST_NM` | `last_name` | VARCHAR → STRING | Trim whitespace |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR → STRING | Trim, nullable |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR → STRING | Direct copy |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR → STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR → STRING | Direct copy, nullable |
| `BORR_CTY_NM` | `city` | VARCHAR → STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR → STRING | Direct copy |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR → STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR → STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR → STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR → INT | Parse integer |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR → STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `BORR_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |
| `BORR_STAT_CD` | `status` | VARCHAR → STRING | ACT→ACTIVE, INA→INACTIVE |
| `BORR_REC_TYP` | *(dropped)* | — | Not needed in modern schema |

### 2.2 CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|--------------|---------------|-------------|----------------|
| `PROD_CD` | `code` | VARCHAR → STRING | Direct copy |
| `PROD_DESC_TXT` | `name` | VARCHAR → STRING | Trim whitespace |
| `PROD_TYP_CD` | `type` | VARCHAR → STRING | Direct copy |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | Parse integer |
| `PROD_RT_TYP` | `rate_type` | VARCHAR → STRING | Direct copy |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `PROD_STAT_CD` | `is_active` | VARCHAR → BOOLEAN | ACT→true, INA→false |
| `PROD_EFF_DT` | `effective_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR → DATE | Parse MM/DD/YYYY |

### 2.3 CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|--------------|---------------|-------------|----------------|
| `LN_ACCT_NBR` | `account_number` | VARCHAR → STRING | Direct copy |
| `BORR_ID` | `borrower_id` | VARCHAR → BIGINT | FK lookup via borrowers.external_id |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_id` | VARCHAR → BIGINT | FK lookup via loan_products.code |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | Parse decimal |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | Parse integer |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `LN_ORIG_DT` | `origination_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `LN_MAT_DT` | `maturity_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `LN_STAT_CD` | `status` | VARCHAR → STRING | ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | Parse integer, default 0 |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | Parse decimal |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR → STRING | SFR→Single Family, CND→Condominium, etc. |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |
| `LN_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |

### 2.4 CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Change | Transformation |
|--------------|---------------|-------------|----------------|
| `PMT_SEQ_NBR` | `legacy_sequence_nbr` | VARCHAR → STRING | Preserved for traceability |
| `LN_ACCT_NBR` | `loan_account_id` | VARCHAR → BIGINT | FK lookup via loan_accounts.account_number |
| `PMT_DT` | `payment_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `PMT_AMT` | `total_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_TYP_CD` | `type` | VARCHAR → STRING | REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| `PMT_STAT_CD` | `status` | VARCHAR → STRING | PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| `PMT_RECV_DT` | `received_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `PMT_PROC_DT` | `processed_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `PMT_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |

---

## 3. Execution Order

The ingestion pipeline must run in dependency order because loan_accounts requires borrower and product IDs, and payments requires loan account IDs.

### Step 1: Create Database and Tables

```sql
-- Run in Databricks SQL or a notebook
CREATE DATABASE IF NOT EXISTS loan_warehouse;

-- Execute DDL files in order:
-- 1. databricks/ddl/borrowers.sql
-- 2. databricks/ddl/loan_products.sql
-- 3. databricks/ddl/loan_accounts.sql
-- 4. databricks/ddl/payments.sql
```

### Step 2: Export Legacy Data

Export the 4 legacy CDW tables to CSV or Parquet files in a landing zone:

```bash
# From the Spring Boot app's H2 console or via a JDBC export tool:
# Export CDW_BORR_MSTR → /mnt/landing/cdw_borr_mstr/
# Export CDW_LN_PROD   → /mnt/landing/cdw_ln_prod/
# Export CDW_LN_ACCT   → /mnt/landing/cdw_ln_acct/
# Export CDW_PMT_HIST  → /mnt/landing/cdw_pmt_hist/
```

### Step 3: Run Ingestion Scripts (in order)

```bash
# 1. Borrowers FIRST (no dependencies)
spark-submit databricks/ingestion/ingest_borrowers.py \
    --source /mnt/landing/cdw_borr_mstr/ --format csv

# 2. Loan Products SECOND (no dependencies)
spark-submit databricks/ingestion/ingest_loan_products.py \
    --source /mnt/landing/cdw_ln_prod/ --format csv

# 3. Loan Accounts THIRD (depends on borrowers + loan_products for FK resolution)
spark-submit databricks/ingestion/ingest_loan_accounts.py \
    --source /mnt/landing/cdw_ln_acct/ --format csv

# 4. Payments LAST (depends on loan_accounts for FK resolution)
spark-submit databricks/ingestion/ingest_payments.py \
    --source /mnt/landing/cdw_pmt_hist/ --format csv
```

### Step 4: Run Data Quality Checks

```bash
spark-submit databricks/quality/data_quality_checks.py \
    --source-borrowers /mnt/landing/cdw_borr_mstr/ \
    --source-products /mnt/landing/cdw_ln_prod/ \
    --source-loans /mnt/landing/cdw_ln_acct/ \
    --source-payments /mnt/landing/cdw_pmt_hist/ \
    --output-report docs/DATA_QUALITY_REPORT.md
```

### Step 5: Optimize Tables

```sql
-- After initial load, optimize for query performance
OPTIMIZE loan_warehouse.loan_accounts ZORDER BY (origination_date);
OPTIMIZE loan_warehouse.payments ZORDER BY (payment_date);
```

---

## 4. Known Data Anomalies

The legacy CDW data has documented quality issues (see `docs/DATA_ANOMALY_REPORT.md`). The pipeline handles these as follows:

| Anomaly | Severity | Pipeline Handling |
|---------|----------|-------------------|
| Payment component sum mismatch | Critical | Logged as warning; records ingested with original values. Quality check reports mismatches. |
| Malformed numeric values | Critical | Regex strips noise (`$`, `%`); remaining unparseable values become `null` with console warning. |
| Null required fields | High | Records quarantined (logged to console); not written to target table. |
| SSN last-4 = phone last-4 | High | SSN last-4 field dropped during denormalization removal (not migrated). |
| Delinquency vs. status inconsistency | Medium | Ingested as-is; quality check flags the inconsistency as a warning. |
| Invalid date formats | Medium | `to_date()` returns `null` for unparseable dates; logged at source. |
| Orphaned FK references | Medium | Left join during FK resolution; orphans get `null` FK and are logged. |
| Denormalized data drift | Low | Denormalized fields dropped; master table is source of truth. |

---

## 5. Rollback Procedure

Delta Lake supports time travel, so rollback is straightforward:

```sql
-- Restore to previous version (before migration)
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.loan_products TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.payments TO VERSION AS OF 0;

-- Or restore to a specific timestamp
RESTORE TABLE loan_warehouse.borrowers TO TIMESTAMP AS OF '2025-01-01T00:00:00';
```

---

## 6. Incremental Updates

For ongoing synchronization after the initial migration:

1. Export only changed records from the CDW (using `BORR_UPDT_DT` / `LN_UPDT_DT` / `PMT_UPDT_DT` as watermarks)
2. Run ingestion scripts with `--mode append`
3. Use Delta Lake `MERGE INTO` for upsert semantics (future enhancement)
4. Run quality checks after each incremental load
