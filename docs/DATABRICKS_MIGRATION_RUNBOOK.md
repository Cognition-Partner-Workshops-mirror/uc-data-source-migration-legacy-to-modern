# Databricks Migration Runbook

## CDW Legacy Schema -> Delta Lake Modern Schema

This runbook documents the complete migration pipeline that transforms data from the legacy Corporate Data Warehouse (CDW) all-VARCHAR tables into a properly typed, normalized Delta Lake schema on Databricks.

---

## Table of Contents

1. [Source Schema Overview](#1-source-schema-overview)
2. [Target Schema Overview](#2-target-schema-overview)
3. [Column Mapping Reference](#3-column-mapping-reference)
4. [Type Conversion Decisions](#4-type-conversion-decisions)
5. [Status Code Expansion](#5-status-code-expansion)
6. [Denormalization Removal](#6-denormalization-removal)
7. [Partitioning Strategy](#7-partitioning-strategy)
8. [Execution Order](#8-execution-order)
9. [Data Quality Checks](#9-data-quality-checks)
10. [Rollback Procedure](#10-rollback-procedure)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Source Schema Overview

The legacy CDW schema consists of four tables, all using VARCHAR columns with no foreign keys and cryptic abbreviated column names:

| Legacy Table | Description | Row Count (Seed) | Key Issues |
|--------------|-------------|-------------------|------------|
| `CDW_BORR_MSTR` | Borrower master | 5 | Dates as MM/DD/YYYY strings, income as comma-formatted string |
| `CDW_LN_PROD` | Loan products | 5 | Term/amounts as strings, status codes |
| `CDW_LN_ACCT` | Loan accounts | 5 | Denormalized borrower fields, all amounts as strings |
| `CDW_PMT_HIST` | Payment history | 10 | All amounts/dates as strings, abbreviated type/status codes |

**Legacy characteristics:**
- All columns are `VARCHAR` (loose typing)
- Dates stored as `MM/DD/YYYY` strings
- Amounts stored as comma-formatted strings (e.g., `"285,000"`, `"1,487.02"`)
- Status codes are 3-letter abbreviations (ACT, CLO, DFT, FRB)
- No referential integrity constraints
- Borrower data duplicated in `CDW_LN_ACCT` (denormalized)

---

## 2. Target Schema Overview

The modern Delta Lake schema in the `loan_warehouse` database:

| Target Table | Description | Format | Partitioning |
|--------------|-------------|--------|--------------|
| `loan_warehouse.borrowers` | Borrower dimension | Delta | None (small table) |
| `loan_warehouse.loan_products` | Product reference | Delta | None (small table) |
| `loan_warehouse.loan_accounts` | Loan account fact | Delta | `status` |
| `loan_warehouse.payments` | Payment fact | Delta | `status` |

**Modern characteristics:**
- Proper Spark SQL types (DATE, DECIMAL, INT, BOOLEAN, TIMESTAMP)
- Meaningful column names
- Normalized structure with foreign keys
- Delta Lake with auto-optimize and auto-compact
- Migration lineage columns (`_migration_source`, `_migrated_at`)

---

## 3. Column Mapping Reference

### CDW_BORR_MSTR -> borrowers

| Legacy Column | Modern Column | Transformation |
|---------------|---------------|----------------|
| `BORR_ID` | `external_id` | Direct copy |
| `BORR_FST_NM` | `first_name` | Direct copy |
| `BORR_LST_NM` | `last_name` | Direct copy |
| `BORR_MID_INIT` | `middle_initial` | Direct copy |
| `BORR_SSN_ENCR` | `ssn_hash` | Direct copy (re-encryption recommended post-migration) |
| `BORR_DOB_DT` | `date_of_birth` | Parse MM/DD/YYYY -> DATE |
| `BORR_ADDR_LN1` | `address_line1` | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | Direct copy |
| `BORR_CTY_NM` | `city` | Direct copy |
| `BORR_ST_CD` | `state` | Direct copy |
| `BORR_ZIP_CD` | `zip_code` | Direct copy |
| `BORR_PH_NBR` | `phone` | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | Parse string -> INT |
| `BORR_EMP_STAT` | `employment_status` | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | Remove commas, parse -> DECIMAL(12,2) |
| `BORR_CRET_DT` | `created_at` | Parse MM/DD/YYYY -> TIMESTAMP |
| `BORR_UPDT_DT` | `updated_at` | Parse MM/DD/YYYY -> TIMESTAMP |
| `BORR_STAT_CD` | `status` | Expand: ACT->ACTIVE, INA->INACTIVE |
| `BORR_REC_TYP` | *(dropped)* | Not needed in modern schema |

### CDW_LN_PROD -> loan_products

| Legacy Column | Modern Column | Transformation |
|---------------|---------------|----------------|
| `PROD_CD` | `code` | Direct copy |
| `PROD_DESC_TXT` | `name` | Direct copy |
| `PROD_TYP_CD` | `type` | Direct copy |
| `PROD_TERM_MOS` | `term_months` | Parse string -> INT |
| `PROD_RT_TYP` | `rate_type` | Direct copy |
| `PROD_MIN_AMT` | `min_amount` | Remove commas, parse -> DECIMAL(12,2) |
| `PROD_MAX_AMT` | `max_amount` | Remove commas, parse -> DECIMAL(12,2) |
| `PROD_STAT_CD` | `is_active` | ACT->true, INA->false |
| `PROD_EFF_DT` | `effective_date` | Parse MM/DD/YYYY -> DATE |
| `PROD_EXP_DT` | `expiration_date` | Parse MM/DD/YYYY -> DATE |

### CDW_LN_ACCT -> loan_accounts

| Legacy Column | Modern Column | Transformation |
|---------------|---------------|----------------|
| `LN_ACCT_NBR` | `account_number` | Direct copy |
| `BORR_ID` | `borrower_id` | FK lookup: borrowers.borrower_id via external_id |
| `BORR_FST_NM` | *(dropped)* | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | Denormalized; use borrower FK |
| `PROD_CD` | `product_id` | FK lookup: loan_products.product_id via code |
| `LN_ORIG_AMT` | `original_amount` | Remove commas, parse -> DECIMAL(12,2) |
| `LN_CURR_BAL` | `current_balance` | Remove commas, parse -> DECIMAL(12,2) |
| `LN_INT_RT` | `interest_rate` | Parse -> DECIMAL(5,3) |
| `LN_TERM_MOS` | `term_months` | Parse string -> INT |
| `LN_PMT_AMT` | `monthly_payment` | Remove commas, parse -> DECIMAL(10,2) |
| `LN_ORIG_DT` | `origination_date` | Parse MM/DD/YYYY -> DATE |
| `LN_MAT_DT` | `maturity_date` | Parse MM/DD/YYYY -> DATE |
| `LN_1ST_PMT_DT` | `first_payment_date` | Parse MM/DD/YYYY -> DATE |
| `LN_NXT_PMT_DT` | `next_payment_date` | Parse MM/DD/YYYY -> DATE |
| `LN_STAT_CD` | `status` | Expand: ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE |
| `LN_DLQ_DAYS` | `delinquency_days` | Parse string -> INT |
| `LN_ESCROW_BAL` | `escrow_balance` | Remove commas, parse -> DECIMAL(10,2) |
| `LN_LTV_PCT` | `ltv_percent` | Parse -> DECIMAL(5,2) |
| `PROP_ADDR_LN1` | `property_address` | Direct copy |
| `PROP_CTY_NM` | `property_city` | Direct copy |
| `PROP_ST_CD` | `property_state` | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | Direct copy |
| `PROP_TYP_CD` | `property_type` | Expand: SFR->Single Family, CND->Condominium, MFR->Multi-Family, TWN->Townhouse |
| `PROP_APRS_VAL` | `appraised_value` | Remove commas, parse -> DECIMAL(12,2) |
| `LN_CRET_DT` | `created_at` | Parse MM/DD/YYYY -> TIMESTAMP |
| `LN_UPDT_DT` | `updated_at` | Parse MM/DD/YYYY -> TIMESTAMP |

### CDW_PMT_HIST -> payments

| Legacy Column | Modern Column | Transformation |
|---------------|---------------|----------------|
| `PMT_SEQ_NBR` | `legacy_sequence_nbr` | Preserved for traceability |
| `LN_ACCT_NBR` | `loan_account_id` | FK lookup: loan_accounts.loan_account_id via account_number |
| `PMT_DT` | `payment_date` | Parse MM/DD/YYYY -> DATE |
| `PMT_AMT` | `total_amount` | Remove commas, parse -> DECIMAL(10,2) |
| `PMT_PRIN_AMT` | `principal_amount` | Remove commas, parse -> DECIMAL(10,2) |
| `PMT_INT_AMT` | `interest_amount` | Remove commas, parse -> DECIMAL(10,2) |
| `PMT_ESCROW_AMT` | `escrow_amount` | Remove commas, parse -> DECIMAL(10,2) |
| `PMT_LATE_FEE` | `late_fee` | Remove commas, parse -> DECIMAL(10,2) |
| `PMT_TYP_CD` | `type` | Expand: REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT |
| `PMT_STAT_CD` | `status` | Expand: PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING |
| `PMT_RECV_DT` | `received_date` | Parse MM/DD/YYYY -> DATE |
| `PMT_PROC_DT` | `processed_date` | Parse MM/DD/YYYY -> DATE |
| `PMT_CRET_DT` | `created_at` | Parse MM/DD/YYYY -> TIMESTAMP |
| `PMT_UPDT_DT` | `updated_at` | Parse MM/DD/YYYY -> TIMESTAMP |

---

## 4. Type Conversion Decisions

### Date Strings -> DATE / TIMESTAMP

- **Source format:** `MM/DD/YYYY` (e.g., `"03/15/1978"`)
- **Target type:** `DATE` for business dates (DOB, origination, payment), `TIMESTAMP` for audit dates (created_at, updated_at)
- **Parse function:** `to_date(col, "MM/dd/yyyy")` / `to_timestamp(col, "MM/dd/yyyy")`
- **Rationale:** Audit timestamps use TIMESTAMP to allow future sub-day precision. Business dates use DATE since they inherently represent calendar days.
- **Edge cases:** Malformed dates are set to NULL and flagged in the bad-value report (never silently dropped).

### Amount Strings -> DECIMAL

- **Source format:** Comma-separated strings (e.g., `"285,000"`, `"1,487.02"`)
- **Target type:** `DECIMAL(12,2)` for large amounts (loan amounts, income), `DECIMAL(10,2)` for payment amounts, `DECIMAL(5,3)` for interest rates, `DECIMAL(5,2)` for percentages
- **Parse function:** `regexp_replace(col, ",", "").cast(DecimalType(p, s))`
- **Rationale:** DECIMAL chosen over DOUBLE for exact financial arithmetic. Precision chosen to accommodate the largest values in the source data with headroom.
- **Edge cases:** Non-numeric or empty strings produce NULL and are flagged.

### Integer Strings -> INT

- **Source format:** Numeric strings (e.g., `"360"`, `"745"`)
- **Target type:** `INT`
- **Parse function:** `col.cast(IntegerType())`
- **Fields:** `credit_score`, `term_months`, `delinquency_days`

### Status Codes -> BOOLEAN

- **Applies to:** `CDW_LN_PROD.PROD_STAT_CD` only
- **Mapping:** `ACT` -> `true`, `INA` -> `false`
- **Rationale:** Product active/inactive is a binary state; BOOLEAN is more expressive than storing a string.

---

## 5. Status Code Expansion

All status code mappings are defined in `databricks/ingestion/transform_utils.py`:

### Loan Status (`LN_STAT_CD`)
| Code | Expanded |
|------|----------|
| ACT | ACTIVE |
| CLO | CLOSED |
| DFT | DEFAULT |
| FRB | FORBEARANCE |

### Borrower Status (`BORR_STAT_CD`)
| Code | Expanded |
|------|----------|
| ACT | ACTIVE |
| INA | INACTIVE |

### Payment Type (`PMT_TYP_CD`)
| Code | Expanded |
|------|----------|
| REG | REGULAR |
| EXT | EXTRA |
| PRT | PARTIAL |
| PRE | PREPAYMENT |

### Payment Status (`PMT_STAT_CD`)
| Code | Expanded |
|------|----------|
| PST | POSTED |
| REV | REVERSED |
| NSF | NSF |
| PND | PENDING |

### Property Type (`PROP_TYP_CD`)
| Code | Expanded |
|------|----------|
| SFR | Single Family |
| CND | Condominium |
| MFR | Multi-Family |
| TWN | Townhouse |

**Unknown codes** are preserved as-is (uppercased/trimmed) and flagged in the bad-value report. Records are never dropped due to an unknown code.

---

## 6. Denormalization Removal

The legacy `CDW_LN_ACCT` table embeds borrower fields directly:
- `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`

These are **dropped** in the modern schema. Instead, `loan_accounts.borrower_id` is a foreign key resolved by joining `CDW_LN_ACCT.BORR_ID` against `borrowers.external_id`.

**Why this matters:**
- Eliminates data duplication (borrower name stored once, not in every loan)
- Ensures name updates propagate automatically
- Enforces referential integrity

---

## 7. Partitioning Strategy

| Table | Partition Column | Rationale |
|-------|-----------------|-----------|
| `borrowers` | None | Small dimension table; partitioning adds overhead without benefit |
| `loan_products` | None | Small reference table (~5-50 rows) |
| `loan_accounts` | `status` | Most operational queries filter by status (active, closed, default). Partition pruning provides significant speedup for dashboards and reports. Few distinct values (4) keeps partition count manageable. |
| `payments` | `status` | Payment queries commonly filter by status (posted vs. pending). Partition by status enables efficient filtering for reconciliation and audit workflows. |

**Alternative considered:** Partitioning `loan_accounts` by `origination_year` was considered. While it provides good distribution for historical analysis, the `status` partition better serves the primary operational query patterns (servicing active loans, monitoring defaults). The `origination_year` column is included as a generated column for use in secondary filtering.

---

## 8. Execution Order

Run the pipeline in this exact order due to foreign key dependencies:

### Step 0: Create Database
```sql
-- databricks/ddl/000_database.sql
CREATE DATABASE IF NOT EXISTS loan_warehouse ...
```

### Step 1: Create Tables (DDL)
Run in order:
1. `databricks/ddl/001_borrowers.sql`
2. `databricks/ddl/002_loan_products.sql`
3. `databricks/ddl/003_loan_accounts.sql`
4. `databricks/ddl/004_payments.sql`

### Step 2: Export Legacy Data
Export each CDW table as CSV or Parquet files to a staging area:
```
dbfs:/mnt/legacy_export/
  CDW_BORR_MSTR/
  CDW_LN_PROD/
  CDW_LN_ACCT/
  CDW_PMT_HIST/
```

### Step 3: Run Ingestion Pipeline
Execute `databricks/ingestion/run_pipeline.py` which runs:
1. **Borrowers** (no FK dependencies)
2. **Loan Products** (no FK dependencies)
3. **Loan Accounts** (depends on borrowers + loan_products for FK resolution)
4. **Payments** (depends on loan_accounts for FK resolution)

```python
from ingestion.run_pipeline import run_full_pipeline

bad_report = run_full_pipeline(
    spark,
    base_path="dbfs:/mnt/legacy_export",
    fmt="csv",
    write_mode="overwrite",
)
```

### Step 4: Run Quality Checks
Execute `databricks/quality/run_quality_checks.py`:
```python
from quality.data_quality_checks import run_all_checks, generate_report

report = run_all_checks(spark, source_counts={
    "CDW_BORR_MSTR": 5,
    "CDW_LN_PROD": 5,
    "CDW_LN_ACCT": 5,
    "CDW_PMT_HIST": 10,
})
generate_report(report, output_path="/dbfs/mnt/reports/DATA_QUALITY_REPORT.md")
```

### Step 5: Review Quality Report
Check `DATA_QUALITY_REPORT.md` for:
- Row count mismatches
- NULL violations on required fields
- Orphaned foreign keys
- Business rule failures
- Parse error counts from the bad-value report

---

## 9. Data Quality Checks

The quality framework (`databricks/quality/data_quality_checks.py`) validates:

| Category | Check | Severity |
|----------|-------|----------|
| Row Count | Source vs. target count per table | ERROR |
| Null Check | Required fields contain no NULLs | ERROR |
| Referential Integrity | loan_accounts.borrower_id references valid borrower | ERROR |
| Referential Integrity | loan_accounts.product_id references valid product | ERROR |
| Referential Integrity | payments.loan_account_id references valid loan | ERROR |
| Business Rule | Active loans have current_balance > 0 | ERROR |
| Business Rule | Active loans have next_payment_date set | WARNING |
| Business Rule | origination_date < maturity_date | ERROR |
| Business Rule | Interest rate in (0, 30] | WARNING |
| Business Rule | LTV percent in [0, 200] | WARNING |
| Business Rule | Payment total = sum of components | ERROR |
| Business Rule | Credit score in [300, 850] | WARNING |
| Business Rule | Active loan delinquency awareness | INFO |

---

## 10. Rollback Procedure

Delta Lake supports time travel, making rollback straightforward:

```sql
-- View table history
DESCRIBE HISTORY loan_warehouse.loan_accounts;

-- Restore to a specific version
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF <version>;

-- Or restore to a timestamp
RESTORE TABLE loan_warehouse.payments TO TIMESTAMP AS OF '2026-01-15T00:00:00';
```

To fully roll back the migration:
```sql
DROP TABLE IF EXISTS loan_warehouse.payments;
DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
DROP TABLE IF EXISTS loan_warehouse.loan_products;
DROP TABLE IF EXISTS loan_warehouse.borrowers;
DROP DATABASE IF EXISTS loan_warehouse;
```

---

## 11. Troubleshooting

### Parse errors in bad-value report
- Check `_bad_*` flag columns in the ingestion output for the specific malformed values
- Common causes: extra whitespace, non-standard date formats, currency symbols in amounts
- Fix the source data extract and re-run the affected ingestion step

### Foreign key lookup failures
- Ensure dimension tables (borrowers, loan_products) are loaded before fact tables (loan_accounts, payments)
- Check for mismatched IDs between CDW_LN_ACCT.BORR_ID and CDW_BORR_MSTR.BORR_ID
- Unmatched rows are logged as warnings but NOT dropped

### Row count mismatches
- Source counts in `run_quality_checks.py` must match the actual extract file row counts
- Duplicate primary keys in source data can cause issues with IDENTITY columns
- Check for header rows being counted as data in CSV files

### Unknown status codes
- Unknown codes are preserved as-is (uppercased) and flagged in `_unmapped_*` columns
- Add new codes to the mapping dictionaries in `transform_utils.py`
- Re-run only the affected ingestion step
