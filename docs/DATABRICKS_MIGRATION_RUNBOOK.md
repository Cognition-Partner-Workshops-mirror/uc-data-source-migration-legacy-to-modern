# Databricks Migration Runbook

## Legacy CDW to Delta Lake Migration

**Document Version:** 1.0
**Last Updated:** 2025-12-01
**Author:** Data Engineering Team

---

## Table of Contents

1. [Overview](#overview)
2. [Source System Analysis](#source-system-analysis)
3. [Column Mapping Reference](#column-mapping-reference)
4. [Type Conversion Decisions](#type-conversion-decisions)
5. [Status Code Expansion Reference](#status-code-expansion-reference)
6. [Partitioning Strategy](#partitioning-strategy)
7. [Execution Order](#execution-order)
8. [Running the Pipeline](#running-the-pipeline)
9. [Data Quality Validation](#data-quality-validation)
10. [Rollback Procedures](#rollback-procedures)
11. [Known Edge Cases](#known-edge-cases)
12. [Post-Migration Verification](#post-migration-verification)

---

## Overview

This runbook documents the migration of loan management data from the legacy CDW (Corporate Data Warehouse) system to a modern Delta Lake schema on Databricks. The legacy system stores all data as VARCHAR strings with cryptic abbreviated column names, denormalized structures, and no foreign key constraints. The target Delta Lake schema uses proper Spark SQL types, meaningful names, normalized tables, and referential integrity.

### Migration Scope

| Source Table | Target Delta Table | Record Count (Seed) | Description |
|---|---|---|---|
| `CDW_BORR_MSTR` | `loan_warehouse.borrowers` | 5 | Borrower demographics and financials |
| `CDW_LN_PROD` | `loan_warehouse.loan_products` | 5 | Loan product definitions |
| `CDW_LN_ACCT` | `loan_warehouse.loan_accounts` | 5 | Loan account details (normalized) |
| `CDW_PMT_HIST` | `loan_warehouse.payments` | 10 | Payment transaction history |

### Key Changes from Legacy

- **All-VARCHAR eliminated:** Every column now uses appropriate Spark SQL types (DATE, DECIMAL, INT, BOOLEAN, TIMESTAMP).
- **Denormalization removed:** Borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) are dropped from `loan_accounts`; a `borrower_id` FK reference replaces them.
- **Foreign keys enforced:** Relationships between `loan_accounts` → `borrowers`, `loan_accounts` → `loan_products`, and `payments` → `loan_accounts` are enforced via FK lookups during ingestion.
- **Status codes expanded:** Cryptic abbreviations replaced with readable values (see [Status Code Reference](#status-code-expansion-reference)).
- **Audit metadata added:** Every table includes `_ingestion_ts` and `_source_system` columns for traceability.

---

## Source System Analysis

### Legacy CDW Characteristics

The legacy CDW system has the following characteristics that drive transformation decisions:

1. **Loose typing:** All columns are `VARCHAR`, regardless of actual data type. Dates are `MM/DD/YYYY` strings, amounts are comma-formatted strings (e.g., `"285,000"`), and even integers are stored as strings.

2. **Cryptic column names:** Column names use abbreviated conventions:
   - `BORR_` prefix = Borrower fields
   - `LN_` prefix = Loan fields
   - `PMT_` prefix = Payment fields
   - `PROD_` prefix = Product fields
   - `_NM` suffix = Name, `_DT` suffix = Date, `_AMT` suffix = Amount
   - `_CD` suffix = Code, `_NBR` suffix = Number, `_PCT` suffix = Percent

3. **Denormalized structure:** `CDW_LN_ACCT` contains redundant borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) duplicated from `CDW_BORR_MSTR`.

4. **No foreign keys:** Tables are linked by string IDs (`BORR_ID`, `PROD_CD`, `LN_ACCT_NBR`) with no database-level referential integrity.

5. **Status code abbreviations:** Short codes like `ACT`, `CLO`, `DFT`, `FRB` instead of readable values.

### Source File Format

Legacy data is extracted to a landing zone as CSV or Parquet files:
- **Landing path:** `/mnt/landing/cdw/{TABLE_NAME}/`
- **CSV options:** Header row present, no schema inference (all strings), empty strings treated as NULL.
- **Parquet:** If exported as Parquet, column types are already strings from the legacy VARCHAR schema.

---

## Column Mapping Reference

### CDW_BORR_MSTR → loan_warehouse.borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| `BORR_ID` | `external_id` | VARCHAR(20) → STRING | Direct copy |
| `BORR_FST_NM` | `first_name` | VARCHAR(50) → STRING | Direct copy |
| `BORR_LST_NM` | `last_name` | VARCHAR(50) → STRING | Direct copy |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR(1) → STRING | Direct copy |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR(100) → STRING | Direct copy (re-encrypt recommended) |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → `DateType` |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR(100) → STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR(100) → STRING | Direct copy |
| `BORR_CTY_NM` | `city` | VARCHAR(50) → STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR(2) → STRING | Direct copy |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR(10) → STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR(15) → STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR(100) → STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR(5) → INT | Parse string → integer |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR(20) → STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR(15) → DECIMAL(12,2) | Remove commas, parse → decimal |
| `BORR_CRET_DT` | `created_at` | VARCHAR(10) → TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR(10) → TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |
| `BORR_STAT_CD` | `status` | VARCHAR(5) → STRING | Expand: ACT→Active, INA→Inactive |
| `BORR_REC_TYP` | *(dropped)* | — | Not needed in modern schema |

### CDW_LN_PROD → loan_warehouse.loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| `PROD_CD` | `code` | VARCHAR(10) → STRING | Direct copy |
| `PROD_DESC_TXT` | `name` | VARCHAR(200) → STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR(5) → STRING | Direct copy |
| `PROD_TERM_MOS` | `term_months` | VARCHAR(5) → INT | Parse string → integer |
| `PROD_RT_TYP` | `rate_type` | VARCHAR(10) → STRING | Direct copy |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR(15) → DECIMAL(12,2) | Remove commas, parse → decimal |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR(15) → DECIMAL(12,2) | Remove commas, parse → decimal |
| `PROD_STAT_CD` | `is_active` | VARCHAR(5) → BOOLEAN | ACT→true, INA→false |
| `PROD_EFF_DT` | `effective_date` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → `DateType` |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → `DateType` |

### CDW_LN_ACCT → loan_warehouse.loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| `LN_ACCT_NBR` | `account_number` | VARCHAR(20) → STRING | Direct copy |
| `BORR_ID` | `borrower_id` | VARCHAR(20) → BIGINT | FK lookup via `borrowers.external_id` |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_id` | VARCHAR(10) → BIGINT | FK lookup via `loan_products.code` |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR(15) → DECIMAL(12,2) | Remove commas, parse → decimal |
| `LN_CURR_BAL` | `current_balance` | VARCHAR(15) → DECIMAL(12,2) | Remove commas, parse → decimal |
| `LN_INT_RT` | `interest_rate` | VARCHAR(8) → DECIMAL(5,3) | Parse string → decimal |
| `LN_TERM_MOS` | `term_months` | VARCHAR(5) → INT | Parse string → integer |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR(15) → DECIMAL(10,2) | Remove commas, parse → decimal |
| `LN_ORIG_DT` | `origination_date` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → `DateType` |
| `LN_MAT_DT` | `maturity_date` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → `DateType` |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → `DateType` |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → `DateType` |
| `LN_STAT_CD` | `status` | VARCHAR(5) → STRING | Expand: ACT→Active, CLO→Closed, DFT→Default, FRB→Forbearance |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR(5) → INT | Parse string → integer |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR(15) → DECIMAL(10,2) | Remove commas, parse → decimal |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR(8) → DECIMAL(5,2) | Parse string → decimal |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR(100) → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR(50) → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR(2) → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR(10) → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR(10) → STRING | Expand: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR(15) → DECIMAL(12,2) | Remove commas, parse → decimal |
| `LN_CRET_DT` | `created_at` | VARCHAR(10) → TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |
| `LN_UPDT_DT` | `updated_at` | VARCHAR(10) → TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |

### CDW_PMT_HIST → loan_warehouse.payments

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| `PMT_SEQ_NBR` | `external_payment_id` | VARCHAR(20) → STRING | Preserved for traceability |
| `LN_ACCT_NBR` | `loan_account_id` | VARCHAR(20) → BIGINT | FK lookup via `loan_accounts.account_number` |
| `PMT_DT` | `payment_date` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → `DateType` |
| `PMT_AMT` | `total_amount` | VARCHAR(15) → DECIMAL(10,2) | Remove commas, parse → decimal |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR(15) → DECIMAL(10,2) | Remove commas, parse → decimal |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR(15) → DECIMAL(10,2) | Remove commas, parse → decimal |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR(15) → DECIMAL(10,2) | Remove commas, parse → decimal |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR(15) → DECIMAL(10,2) | Remove commas, parse → decimal |
| `PMT_TYP_CD` | `type` | VARCHAR(5) → STRING | Expand: REG→Regular, EXT→Extra, PRT→Partial, PRE→Prepayment |
| `PMT_STAT_CD` | `status` | VARCHAR(5) → STRING | Expand: PST→Posted, REV→Reversed, NSF→NSF, PND→Pending |
| `PMT_RECV_DT` | `received_date` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → `DateType` |
| `PMT_PROC_DT` | `processed_date` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → `DateType` |
| `PMT_CRET_DT` | `created_at` | VARCHAR(10) → TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR(10) → TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |

---

## Type Conversion Decisions

### Date Strings → DATE / TIMESTAMP

**Decision:** Use Spark's `to_date()` and `to_timestamp()` with format pattern `MM/dd/yyyy`.

**Rationale:** The legacy system consistently uses `MM/DD/YYYY` format. By parsing to native DATE/TIMESTAMP types:
- Enables proper date arithmetic and range queries
- Supports partitioning by date components (year, month)
- Eliminates string comparison issues (e.g., "12/01/2025" < "2/01/2025" in string sort)

**Edge case handling:** Malformed date strings produce NULL values. A `_bad_*` flag column tracks parse failures for investigation.

### Amount Strings → DECIMAL

**Decision:** Strip commas and dollar signs via regex, then cast to `DecimalType(precision, scale)`.

**Rationale:** Amounts like `"285,000"` and `"271,432.56"` use comma formatting common in US financial systems. DECIMAL is preferred over DOUBLE for financial data to avoid floating-point rounding errors.

**Precision choices:**
- `DECIMAL(12,2)` for loan amounts, income, appraised values (up to $9,999,999,999.99)
- `DECIMAL(10,2)` for payment amounts, escrow, fees (up to $99,999,999.99)
- `DECIMAL(5,3)` for interest rates (up to 99.999%)
- `DECIMAL(5,2)` for LTV percentages (up to 999.99%)

### Status Codes → Expanded Strings

**Decision:** Expand abbreviations to readable strings rather than using enum types.

**Rationale:** Spark SQL does not natively support enum constraints. Using full strings improves readability for downstream BI/reporting tools. Unknown codes are preserved as-is (not dropped) and flagged for review.

### Borrower ID Resolution → BIGINT FK

**Decision:** Generate surrogate BIGINT keys for all dimension tables and resolve FK references during ingestion via join lookups.

**Rationale:** The legacy system uses string IDs (`B-10001`, `LN-2019-00142`). While functional, BIGINT surrogate keys are more efficient for joins and indexing in Delta Lake. The original string IDs are preserved as `external_id` / `account_number` / `external_payment_id` columns for traceability.

---

## Status Code Expansion Reference

### Borrower Status (`BORR_STAT_CD` → `status`)

| Legacy Code | Modern Value | Description |
|---|---|---|
| `ACT` | `Active` | Currently active borrower |
| `INA` | `Inactive` | Inactive/closed borrower account |

### Loan Status (`LN_STAT_CD` → `status`)

| Legacy Code | Modern Value | Description |
|---|---|---|
| `ACT` | `Active` | Loan is currently active and being serviced |
| `CLO` | `Closed` | Loan has been fully paid off or settled |
| `DFT` | `Default` | Loan is in default status |
| `FRB` | `Forbearance` | Loan is in forbearance (temporarily reduced/suspended payments) |

### Payment Type (`PMT_TYP_CD` → `type`)

| Legacy Code | Modern Value | Description |
|---|---|---|
| `REG` | `Regular` | Scheduled monthly payment |
| `EXT` | `Extra` | Additional payment beyond the monthly amount |
| `PRT` | `Partial` | Payment less than the full monthly amount |
| `PRE` | `Prepayment` | Early principal paydown |

### Payment Status (`PMT_STAT_CD` → `status`)

| Legacy Code | Modern Value | Description |
|---|---|---|
| `PST` | `Posted` | Payment successfully applied to the loan |
| `REV` | `Reversed` | Payment was reversed/returned |
| `NSF` | `NSF` | Non-sufficient funds (payment bounced) |
| `PND` | `Pending` | Payment received but not yet processed |

### Property Type (`PROP_TYP_CD` → `property_type`)

| Legacy Code | Modern Value | Description |
|---|---|---|
| `SFR` | `Single Family` | Single-family residential property |
| `CND` | `Condominium` | Condominium unit |
| `MFR` | `Multi-Family` | Multi-family residential property |
| `TWN` | `Townhouse` | Townhouse property |

### Product Status (`PROD_STAT_CD` → `is_active`)

| Legacy Code | Modern Value | Description |
|---|---|---|
| `ACT` | `true` | Product is currently offered |
| `INA` | `false` | Product is no longer offered |

---

## Partitioning Strategy

### borrowers — Partitioned by `status`

**Rationale:** Queries frequently filter by borrower status (active vs. inactive). The borrower table is relatively small, so single-column partitioning keeps partition count low while providing the most common filter optimization.

### loan_products — No partitioning

**Rationale:** This is a small reference/dimension table (typically < 100 rows). Partitioning would create unnecessary overhead with no query benefit.

### loan_accounts — Partitioned by `status` and `origination_year`

**Rationale:**
- **`status`**: Most queries filter by loan status (active loans, defaulted loans, etc.)
- **`origination_year`**: Derived from `origination_date`, enables efficient time-range queries (e.g., "all loans originated in 2020") and supports data lifecycle management (archiving old loans)
- This dual-partition strategy balances between common access patterns and partition granularity

### payments — Partitioned by `payment_year` and `payment_month`

**Rationale:**
- Payment queries almost always involve date ranges (monthly statements, quarterly reports)
- Year/month partitioning provides good granularity for partition pruning
- Supports data lifecycle management (archiving old payment history)
- Partition count grows linearly with time (12 partitions/year) which is manageable

---

## Execution Order

The pipeline must be executed in the following order due to FK dependencies:

```
Step 0: Create database    → loan_warehouse database
Step 1: Ingest borrowers   → loan_warehouse.borrowers     (no dependencies)
Step 2: Ingest products    → loan_warehouse.loan_products  (no dependencies)
Step 3: Ingest accounts    → loan_warehouse.loan_accounts  (depends on Steps 1 & 2)
Step 4: Ingest payments    → loan_warehouse.payments       (depends on Step 3)
Step 5: Data quality checks → validates all tables
```

**Dependency graph:**

```
borrowers ────────┐
                  ├── loan_accounts ──── payments
loan_products ────┘
```

Steps 1 and 2 can run in parallel since they have no dependencies on each other. Steps 3, 4, and 5 must run sequentially.

---

## Running the Pipeline

### Prerequisites

1. **Databricks workspace** with a cluster running Databricks Runtime 13.0+ (Spark 3.4+)
2. **Landing zone** mounted at `/mnt/landing/cdw/` with the extracted legacy data:
   - `/mnt/landing/cdw/CDW_BORR_MSTR/` — borrower CSV/Parquet files
   - `/mnt/landing/cdw/CDW_LN_PROD/` — loan product CSV/Parquet files
   - `/mnt/landing/cdw/CDW_LN_ACCT/` — loan account CSV/Parquet files
   - `/mnt/landing/cdw/CDW_PMT_HIST/` — payment history CSV/Parquet files
3. **Permissions** to create databases and tables in the target catalog

### Option A: Run the Full Pipeline (Recommended)

Execute `databricks/ingestion/run_all.py` as a Databricks notebook or job:

```python
# In a Databricks notebook:
%run ./databricks/ingestion/run_all

results = run_pipeline(
    spark,
    source_base_path="/mnt/landing/cdw",
    source_format="csv",
    run_quality_checks=True
)
```

### Option B: Run Individual Steps

Execute each ingestion script independently:

```python
# Step 0: Create database
spark.sql("CREATE DATABASE IF NOT EXISTS loan_warehouse")

# Step 1: Borrowers
%run ./databricks/ingestion/ingest_borrowers
run(spark, "/mnt/landing/cdw/CDW_BORR_MSTR", "csv")

# Step 2: Loan Products
%run ./databricks/ingestion/ingest_loan_products
run(spark, "/mnt/landing/cdw/CDW_LN_PROD", "csv")

# Step 3: Loan Accounts (after Steps 1 & 2)
%run ./databricks/ingestion/ingest_loan_accounts
run(spark, "/mnt/landing/cdw/CDW_LN_ACCT", "csv")

# Step 4: Payments (after Step 3)
%run ./databricks/ingestion/ingest_payments
run(spark, "/mnt/landing/cdw/CDW_PMT_HIST", "csv")

# Step 5: Data Quality
%run ./databricks/quality/data_quality
results = run_all_checks(spark, use_known_counts=True)
```

### Option C: Databricks Workflow Job

Create a multi-task Databricks Workflow:

| Task | Notebook | Depends On |
|---|---|---|
| `create_database` | `databricks/ddl/00_database.sql` | — |
| `ingest_borrowers` | `databricks/ingestion/ingest_borrowers.py` | `create_database` |
| `ingest_products` | `databricks/ingestion/ingest_loan_products.py` | `create_database` |
| `ingest_accounts` | `databricks/ingestion/ingest_loan_accounts.py` | `ingest_borrowers`, `ingest_products` |
| `ingest_payments` | `databricks/ingestion/ingest_payments.py` | `ingest_accounts` |
| `quality_checks` | `databricks/quality/data_quality.py` | `ingest_payments` |

---

## Data Quality Validation

The data quality framework (`databricks/quality/data_quality.py`) runs four categories of checks:

### 1. Row Count Reconciliation
- Compares source file row counts against target Delta table counts
- Ensures no records were silently dropped during transformation
- Can use hardcoded seed counts if source files are unavailable

### 2. Null Checks on Required Fields
- Verifies NOT NULL constraints on columns marked as required
- Catches cases where transformations produced unexpected NULLs

### 3. Referential Integrity
- Validates `loan_accounts.borrower_id` references exist in `borrowers`
- Validates `loan_accounts.product_id` references exist in `loan_products`
- Validates `payments.loan_account_id` references exist in `loan_accounts`

### 4. Business Rules
- Active loans must have `current_balance > 0`
- Closed loans must have a `maturity_date`
- Interest rates must be between 0 and 100
- Credit scores must be between 300 and 850 (or NULL)
- Payment amounts must be non-negative
- `origination_date` must be before `maturity_date`
- Active borrowers should have an email address

### Report Output
The framework generates `DATA_QUALITY_REPORT.md` at the configured output path (default: `/dbfs/tmp/DATA_QUALITY_REPORT.md`).

---

## Rollback Procedures

### Full Rollback

To remove all migrated data and start fresh:

```sql
-- Drop all target tables in reverse dependency order
DROP TABLE IF EXISTS loan_warehouse.payments;
DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
DROP TABLE IF EXISTS loan_warehouse.loan_products;
DROP TABLE IF EXISTS loan_warehouse.borrowers;

-- Optionally drop the database
DROP DATABASE IF EXISTS loan_warehouse CASCADE;
```

### Partial Re-ingestion

To re-ingest a specific table (e.g., payments):

```python
# Re-run only the payments ingestion (uses overwrite mode)
from ingest_payments import run
run(spark, "/mnt/landing/cdw/CDW_PMT_HIST", "csv")
```

Note: Re-ingesting `borrowers` or `loan_products` may invalidate FK references in `loan_accounts`. Always re-ingest downstream tables if you re-ingest upstream dimension tables.

### Delta Lake Time Travel

Delta Lake supports time travel, allowing you to query previous versions:

```sql
-- Query the previous version of loan_accounts
SELECT * FROM loan_warehouse.loan_accounts VERSION AS OF 0;

-- Restore to a previous version if needed
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF 0;
```

---

## Known Edge Cases

### 1. NULL Middle Initials
Some borrowers (e.g., Robert Williams) have NULL `BORR_MID_INIT`. The pipeline preserves NULLs; `middle_initial` is not a required field.

### 2. NULL Address Line 2
Many borrowers have no secondary address. `address_line2` is nullable in the target schema.

### 3. Payment Escrow Amounts of Zero
Some loans (e.g., LN-2021-00567) have `$0.00` escrow amounts in payments. These are legitimate — not all loans have escrow requirements.

### 4. Late Fees on Delinquent Payments
Loan LN-2018-00089 has a payment (PMT-2025110003) with a `$47.50` late fee and 15 days delinquency. This is correctly migrated; the late fee field defaults to `0.00` when no fee applies.

### 5. Self-Employed Borrowers
Borrower Michael Torres has `employment_status = 'SELF-EMP'`. This value is preserved as-is since it is not a status code requiring expansion.

### 6. Surrogate Key Generation
`monotonically_increasing_id()` generates IDs that are unique but not necessarily sequential. This is expected and acceptable for surrogate keys. If sequential IDs are required, use `row_number()` over a window instead.

---

## Post-Migration Verification

After the pipeline completes and data quality checks pass, perform these manual verification steps:

### 1. Spot-Check Sample Records

```sql
-- Verify borrower James Mitchell was correctly transformed
SELECT * FROM loan_warehouse.borrowers WHERE external_id = 'B-10001';
-- Expected: first_name='James', credit_score=745, annual_income=92500.00, status='Active'

-- Verify loan account with all fields
SELECT * FROM loan_warehouse.loan_accounts WHERE account_number = 'LN-2019-00142';
-- Expected: original_amount=285000.00, interest_rate=4.750, status='Active', property_type='Single Family'

-- Verify payment with late fee
SELECT * FROM loan_warehouse.payments WHERE external_payment_id = 'PMT-2025110003';
-- Expected: late_fee=47.50, type='Regular', status='Posted'
```

### 2. Verify FK Relationships

```sql
-- All loan accounts should join successfully to borrowers
SELECT la.account_number, b.first_name, b.last_name
FROM loan_warehouse.loan_accounts la
JOIN loan_warehouse.borrowers b ON la.borrower_id = b.borrower_id;
-- Expected: 5 rows

-- All payments should join to loan accounts
SELECT p.external_payment_id, la.account_number
FROM loan_warehouse.payments p
JOIN loan_warehouse.loan_accounts la ON p.loan_account_id = la.loan_account_id;
-- Expected: 10 rows
```

### 3. Verify Partition Structure

```sql
-- Check loan_accounts partitions
SHOW PARTITIONS loan_warehouse.loan_accounts;

-- Check payments partitions
SHOW PARTITIONS loan_warehouse.payments;
```

---

## Appendix: File Structure

```
databricks/
├── ddl/
│   ├── 00_database.sql              # Create loan_warehouse database
│   ├── 01_borrowers.sql             # borrowers Delta table DDL
│   ├── 02_loan_products.sql         # loan_products Delta table DDL
│   ├── 03_loan_accounts.sql         # loan_accounts Delta table DDL
│   └── 04_payments.sql              # payments Delta table DDL
├── ingestion/
│   ├── __init__.py                  # Package documentation
│   ├── transformations.py           # Shared transformation functions and UDFs
│   ├── ingest_borrowers.py          # CDW_BORR_MSTR → borrowers pipeline
│   ├── ingest_loan_products.py      # CDW_LN_PROD → loan_products pipeline
│   ├── ingest_loan_accounts.py      # CDW_LN_ACCT → loan_accounts pipeline
│   ├── ingest_payments.py           # CDW_PMT_HIST → payments pipeline
│   └── run_all.py                   # Master orchestrator script
└── quality/
    ├── __init__.py                  # Package documentation
    └── data_quality.py              # Data quality validation framework
docs/
└── DATABRICKS_MIGRATION_RUNBOOK.md  # This document
```
