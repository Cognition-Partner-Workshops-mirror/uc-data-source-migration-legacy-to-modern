# Databricks Migration Runbook

## CDW Legacy-to-Modern Loan Data Migration

This document describes every transformation decision, column mapping, type conversion, partitioning rationale, and the recommended execution order for migrating loan management data from the legacy CDW (Corporate Data Warehouse) schema to a modern Delta Lake schema on Databricks.

---

## Table of Contents

1. [Overview](#overview)
2. [Source Schema Summary](#source-schema-summary)
3. [Target Schema Summary](#target-schema-summary)
4. [Column Mapping Reference](#column-mapping-reference)
5. [Transformation Decisions](#transformation-decisions)
6. [Partitioning Strategy](#partitioning-strategy)
7. [Execution Order](#execution-order)
8. [Pre-Migration Checklist](#pre-migration-checklist)
9. [Running the Pipeline](#running-the-pipeline)
10. [Post-Migration Validation](#post-migration-validation)
11. [Rollback Procedure](#rollback-procedure)
12. [Known Edge Cases](#known-edge-cases)

---

## Overview

| Attribute         | Legacy (CDW)                  | Modern (Delta Lake)               |
|-------------------|-------------------------------|-----------------------------------|
| Storage           | Relational DB (H2/Oracle)     | Delta Lake on Databricks          |
| Typing            | All VARCHAR                   | Proper types (DATE, DECIMAL, INT) |
| Normalization     | Denormalized (borrower in loan) | Normalized with FK relationships |
| Constraints       | None                          | NOT NULL, identity columns        |
| Status codes      | Abbreviated (ACT, CLO)        | Expanded (ACTIVE, CLOSED)         |
| Date format       | MM/DD/YYYY strings            | Native DATE/TIMESTAMP             |
| Amount format     | Comma-separated strings       | DECIMAL with precision/scale      |

### Tables Being Migrated

| # | Legacy Table     | Target Table                   | Records (seed) |
|---|------------------|--------------------------------|----------------|
| 1 | CDW_BORR_MSTR    | loan_modernized.borrowers      | 5              |
| 2 | CDW_LN_PROD      | loan_modernized.loan_products  | 5              |
| 3 | CDW_LN_ACCT      | loan_modernized.loan_accounts  | 5              |
| 4 | CDW_PMT_HIST     | loan_modernized.payments       | 10             |

---

## Source Schema Summary

### CDW_BORR_MSTR (Borrower Master)
Contains borrower demographic data. All columns are VARCHAR. Dates stored as `MM/DD/YYYY` strings. Income stored as comma-formatted string (e.g., `"92,500"`). Status codes: `ACT` (Active), `INA` (Inactive).

### CDW_LN_PROD (Loan Products)
Reference table for product definitions. Term, min/max amounts all stored as VARCHAR. Status: `ACT`/`INA`.

### CDW_LN_ACCT (Loan Accounts)
Core loan data with **denormalized borrower fields** (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) redundantly duplicated from `CDW_BORR_MSTR`. Amounts, rates, and dates all VARCHAR. Loan status codes: `ACT`, `CLO`, `DFT`, `FRB`. Property type codes: `SFR`, `CND`, `MFR`, `TWN`.

### CDW_PMT_HIST (Payment History)
Payment transactions. All amounts and dates are VARCHAR. Payment type codes: `REG`, `EXT`, `PRT`, `PRE`. Payment status codes: `PST`, `REV`, `NSF`, `PND`.

---

## Target Schema Summary

All target tables live in the `loan_modernized` schema under the `loan_catalog` catalog. Tables use Delta Lake format with auto-optimize enabled.

### loan_modernized.borrowers
- **Identity column:** `borrower_id` (BIGINT, auto-generated)
- **Partitioned by:** `state` (geographic queries are common in loan servicing)
- **Key changes:** Dates converted to DATE/TIMESTAMP, income to DECIMAL, credit score to INT, status codes expanded

### loan_modernized.loan_products
- **Identity column:** `product_id` (BIGINT, auto-generated)
- **Not partitioned** (small reference table, ~10s of rows)
- **Key changes:** Term to INT, amounts to DECIMAL, status converted to BOOLEAN `is_active`

### loan_modernized.loan_accounts
- **Identity column:** `loan_account_id` (BIGINT, auto-generated)
- **Partitioned by:** `status` (frequent filtering by loan status)
- **Key changes:** Denormalized borrower fields dropped, FK to borrowers established, all amounts/rates/dates properly typed, property type codes expanded

### loan_modernized.payments
- **Identity column:** `payment_id` (BIGINT, auto-generated)
- **Partitioned by:** `payment_year`, `payment_month` (time-series access pattern)
- **Key changes:** All amounts to DECIMAL, dates to DATE/TIMESTAMP, payment type and status codes expanded

---

## Column Mapping Reference

### CDW_BORR_MSTR → borrowers

| Legacy Column    | Modern Column      | Type Change            | Transformation              |
|------------------|--------------------|------------------------|-----------------------------|
| BORR_ID          | external_id        | VARCHAR → STRING       | Direct copy                 |
| BORR_FST_NM      | first_name         | VARCHAR → STRING       | Direct copy (trimmed)       |
| BORR_LST_NM      | last_name          | VARCHAR → STRING       | Direct copy (trimmed)       |
| BORR_MID_INIT    | middle_initial     | VARCHAR → STRING       | Direct copy                 |
| BORR_SSN_ENCR    | ssn_hash           | VARCHAR → STRING       | Direct copy (re-encrypt recommended) |
| BORR_DOB_DT      | date_of_birth      | VARCHAR → DATE         | Parse MM/DD/YYYY            |
| BORR_ADDR_LN1    | address_line1      | VARCHAR → STRING       | Direct copy                 |
| BORR_ADDR_LN2    | address_line2      | VARCHAR → STRING       | Direct copy (nullable)      |
| BORR_CTY_NM      | city               | VARCHAR → STRING       | Direct copy                 |
| BORR_ST_CD        | state              | VARCHAR → STRING       | Direct copy                 |
| BORR_ZIP_CD       | zip_code           | VARCHAR → STRING       | Direct copy                 |
| BORR_PH_NBR       | phone              | VARCHAR → STRING       | Direct copy                 |
| BORR_EMAIL_ADDR   | email              | VARCHAR → STRING       | Direct copy                 |
| BORR_CRDT_SCR     | credit_score       | VARCHAR → INT          | Parse string to integer     |
| BORR_EMP_STAT     | employment_status  | VARCHAR → STRING       | Direct copy                 |
| BORR_ANN_INCM     | annual_income      | VARCHAR → DECIMAL(12,2)| Remove commas, parse        |
| BORR_CRET_DT      | created_at         | VARCHAR → TIMESTAMP    | Parse MM/DD/YYYY            |
| BORR_UPDT_DT      | updated_at         | VARCHAR → TIMESTAMP    | Parse MM/DD/YYYY            |
| BORR_STAT_CD       | status             | VARCHAR → STRING       | ACT→ACTIVE, INA→INACTIVE   |
| BORR_REC_TYP       | _legacy_record_type| VARCHAR → STRING       | Preserved for audit         |

### CDW_LN_PROD → loan_products

| Legacy Column    | Modern Column      | Type Change            | Transformation              |
|------------------|--------------------|------------------------|-----------------------------|
| PROD_CD          | code               | VARCHAR → STRING       | Direct copy                 |
| PROD_DESC_TXT    | name               | VARCHAR → STRING       | Direct copy                 |
| PROD_TYP_CD      | type               | VARCHAR → STRING       | Direct copy                 |
| PROD_TERM_MOS    | term_months        | VARCHAR → INT          | Parse string to integer     |
| PROD_RT_TYP      | rate_type          | VARCHAR → STRING       | Direct copy                 |
| PROD_MIN_AMT     | min_amount         | VARCHAR → DECIMAL(12,2)| Remove commas, parse        |
| PROD_MAX_AMT     | max_amount         | VARCHAR → DECIMAL(12,2)| Remove commas, parse        |
| PROD_STAT_CD     | is_active          | VARCHAR → BOOLEAN      | ACT→true, INA→false        |
| PROD_EFF_DT      | effective_date     | VARCHAR → DATE         | Parse MM/DD/YYYY            |
| PROD_EXP_DT      | expiration_date    | VARCHAR → DATE         | Parse MM/DD/YYYY            |

### CDW_LN_ACCT → loan_accounts

| Legacy Column    | Modern Column      | Type Change            | Transformation              |
|------------------|--------------------|------------------------|-----------------------------|
| LN_ACCT_NBR      | account_number     | VARCHAR → STRING       | Direct copy                 |
| BORR_ID          | borrower_id        | VARCHAR → BIGINT       | FK lookup via borrowers.external_id |
| BORR_FST_NM      | *(dropped)*        | —                      | Denormalized; use FK        |
| BORR_LST_NM      | *(dropped)*        | —                      | Denormalized; use FK        |
| BORR_SSN_LST4    | *(dropped)*        | —                      | Denormalized; use FK        |
| PROD_CD          | product_code       | VARCHAR → STRING       | FK reference to loan_products.code |
| LN_ORIG_AMT      | original_amount    | VARCHAR → DECIMAL(12,2)| Remove commas, parse        |
| LN_CURR_BAL      | current_balance    | VARCHAR → DECIMAL(12,2)| Remove commas, parse        |
| LN_INT_RT        | interest_rate      | VARCHAR → DECIMAL(5,3) | Parse string to decimal     |
| LN_TERM_MOS      | term_months        | VARCHAR → INT          | Parse string to integer     |
| LN_PMT_AMT       | monthly_payment    | VARCHAR → DECIMAL(10,2)| Remove commas, parse        |
| LN_ORIG_DT       | origination_date   | VARCHAR → DATE         | Parse MM/DD/YYYY            |
| LN_MAT_DT        | maturity_date      | VARCHAR → DATE         | Parse MM/DD/YYYY            |
| LN_1ST_PMT_DT    | first_payment_date | VARCHAR → DATE         | Parse MM/DD/YYYY            |
| LN_NXT_PMT_DT    | next_payment_date  | VARCHAR → DATE         | Parse MM/DD/YYYY            |
| LN_STAT_CD       | status             | VARCHAR → STRING       | ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| LN_DLQ_DAYS      | delinquency_days   | VARCHAR → INT          | Parse string to integer     |
| LN_ESCROW_BAL    | escrow_balance     | VARCHAR → DECIMAL(10,2)| Remove commas, parse        |
| LN_LTV_PCT       | ltv_percent        | VARCHAR → DECIMAL(5,2) | Parse string to decimal     |
| PROP_ADDR_LN1    | property_address   | VARCHAR → STRING       | Direct copy                 |
| PROP_CTY_NM      | property_city      | VARCHAR → STRING       | Direct copy                 |
| PROP_ST_CD       | property_state     | VARCHAR → STRING       | Direct copy                 |
| PROP_ZIP_CD      | property_zip       | VARCHAR → STRING       | Direct copy                 |
| PROP_TYP_CD      | property_type      | VARCHAR → STRING       | SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| PROP_APRS_VAL    | appraised_value    | VARCHAR → DECIMAL(12,2)| Remove commas, parse        |
| LN_CRET_DT       | created_at         | VARCHAR → TIMESTAMP    | Parse MM/DD/YYYY            |
| LN_UPDT_DT       | updated_at         | VARCHAR → TIMESTAMP    | Parse MM/DD/YYYY            |
| *(derived)*       | origination_year   | — → INT                | Extracted from origination_date for partitioning |

### CDW_PMT_HIST → payments

| Legacy Column    | Modern Column       | Type Change            | Transformation              |
|------------------|---------------------|------------------------|-----------------------------|
| PMT_SEQ_NBR      | legacy_sequence_nbr | VARCHAR → STRING       | Preserved for traceability  |
| LN_ACCT_NBR      | account_number      | VARCHAR → STRING       | FK reference to loan_accounts |
| PMT_DT           | payment_date        | VARCHAR → DATE         | Parse MM/DD/YYYY            |
| PMT_AMT          | total_amount        | VARCHAR → DECIMAL(10,2)| Remove commas, parse        |
| PMT_PRIN_AMT     | principal_amount    | VARCHAR → DECIMAL(10,2)| Remove commas, parse        |
| PMT_INT_AMT      | interest_amount     | VARCHAR → DECIMAL(10,2)| Remove commas, parse        |
| PMT_ESCROW_AMT   | escrow_amount       | VARCHAR → DECIMAL(10,2)| Remove commas, parse        |
| PMT_LATE_FEE     | late_fee            | VARCHAR → DECIMAL(10,2)| Remove commas, parse        |
| PMT_TYP_CD       | type                | VARCHAR → STRING       | REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| PMT_STAT_CD      | status              | VARCHAR → STRING       | PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| PMT_RECV_DT      | received_date       | VARCHAR → DATE         | Parse MM/DD/YYYY            |
| PMT_PROC_DT      | processed_date      | VARCHAR → DATE         | Parse MM/DD/YYYY            |
| PMT_CRET_DT      | created_at          | VARCHAR → TIMESTAMP    | Parse MM/DD/YYYY            |
| PMT_UPDT_DT      | updated_at          | VARCHAR → TIMESTAMP    | Parse MM/DD/YYYY            |
| *(derived)*       | payment_year        | — → INT                | Extracted from payment_date |
| *(derived)*       | payment_month       | — → INT                | Extracted from payment_date |

---

## Transformation Decisions

### 1. Date Parsing Strategy
**Decision:** Use PySpark's `to_date(col, "MM/dd/yyyy")` for DATE columns and `to_timestamp(col, "MM/dd/yyyy")` for TIMESTAMP columns.

**Rationale:** The legacy system stores all dates as `MM/DD/YYYY` strings. Empty strings and whitespace-only values are converted to NULL rather than failing the parse. Malformed dates produce NULL with a logged warning rather than causing row-level failures — the quarantine mechanism catches records where the date is a required field.

### 2. Amount Parsing Strategy
**Decision:** Strip commas and dollar signs with `regexp_replace`, then cast to `DecimalType(precision, scale)`.

**Rationale:** Legacy amounts like `"285,000"` and `"271,432.56"` use commas as thousands separators. The regex `[$,]` handles both comma-only and dollar-prefixed formats. Precision/scale are chosen per column:
- Loan amounts: `DECIMAL(12,2)` — supports up to $9,999,999,999.99
- Payment amounts: `DECIMAL(10,2)` — supports up to $99,999,999.99
- Interest rates: `DECIMAL(5,3)` — supports rates like 99.999%
- Percentages: `DECIMAL(5,2)` — supports percentages like 999.99%

### 3. Status Code Expansion
**Decision:** Map abbreviated codes to full English words using a deterministic lookup. Unknown codes map to `"UNKNOWN"` rather than NULL.

**Rationale:** Expanding codes improves readability for downstream consumers. Preserving unknown codes as `"UNKNOWN"` (instead of NULL or dropping) makes data quality issues visible and auditable.

| Domain         | Code | Expansion     |
|----------------|------|---------------|
| Loan Status    | ACT  | ACTIVE        |
| Loan Status    | CLO  | CLOSED        |
| Loan Status    | DFT  | DEFAULT       |
| Loan Status    | FRB  | FORBEARANCE   |
| Borrower Status| ACT  | ACTIVE        |
| Borrower Status| INA  | INACTIVE      |
| Payment Type   | REG  | REGULAR       |
| Payment Type   | EXT  | EXTRA         |
| Payment Type   | PRT  | PARTIAL       |
| Payment Type   | PRE  | PREPAYMENT    |
| Payment Status | PST  | POSTED        |
| Payment Status | REV  | REVERSED      |
| Payment Status | NSF  | NSF           |
| Payment Status | PND  | PENDING       |
| Property Type  | SFR  | Single Family |
| Property Type  | CND  | Condominium   |
| Property Type  | MFR  | Multi-Family  |
| Property Type  | TWN  | Townhouse     |
| Product Status | ACT  | true (BOOLEAN)|
| Product Status | INA  | false (BOOLEAN)|

### 4. Denormalization Removal
**Decision:** Drop `BORR_FST_NM`, `BORR_LST_NM`, and `BORR_SSN_LST4` from loan accounts. Replace with a `borrower_id` foreign key resolved by joining on `CDW_BORR_MSTR.BORR_ID`.

**Rationale:** The legacy schema duplicates borrower data inside every loan record. The modern schema normalizes this into a separate `borrowers` table. The `_legacy_borr_id` audit column is preserved so the original relationship is traceable.

### 5. Foreign Key Resolution
**Decision:** Use join-based FK resolution rather than surrogate key generation.

- `loan_accounts.borrower_id` ← join `borrowers` on `external_id = BORR_ID`
- `loan_accounts.product_code` ← kept as string reference to `loan_products.code`
- `payments.account_number` ← kept as string reference to `loan_accounts.account_number`

**Rationale:** String-based references (product_code, account_number) are stable natural keys that don't require sequential loading. The borrower FK uses the identity-generated `borrower_id`, which requires borrowers to be loaded first.

### 6. Audit Columns
**Decision:** Add `_migration_ts` (timestamp of migration run) and `_legacy_*` columns for traceability.

**Rationale:** These columns enable post-migration debugging without requiring access to the legacy system. They are prefixed with `_` to indicate they are metadata, not business data.

---

## Partitioning Strategy

| Table          | Partition Column(s)           | Rationale                                                |
|----------------|-------------------------------|----------------------------------------------------------|
| borrowers      | `state`                       | Geographic queries (compliance reporting, regional analytics) are common. ~50 partitions max. |
| loan_products  | *(none)*                      | Small reference table (~10s of rows). Partitioning would create excessive small files. |
| loan_accounts  | `status`                      | Most queries filter by active/closed/default status. 4 partitions keeps file sizes healthy. |
| payments       | `payment_year`, `payment_month`| Time-series access pattern (monthly reporting, year-over-year). Enables efficient pruning of historical data. |

All tables use Delta Lake auto-optimize (`optimizeWrite` + `autoCompact`) to manage small file problems that can arise from streaming inserts or frequent updates.

---

## Execution Order

The pipeline must run in dependency order because loan_accounts requires borrower FK resolution, and payments require loan account validation.

```
Phase 1 (parallel — no dependencies):
  ├── 1a. borrowers        (CDW_BORR_MSTR → loan_modernized.borrowers)
  └── 1b. loan_products    (CDW_LN_PROD   → loan_modernized.loan_products)

Phase 2 (sequential — depends on Phase 1):
  └── 2a. loan_accounts    (CDW_LN_ACCT   → loan_modernized.loan_accounts)
              ↳ Requires: borrowers (FK resolution)

Phase 3 (sequential — depends on Phase 2):
  └── 3a. payments         (CDW_PMT_HIST  → loan_modernized.payments)
              ↳ Requires: loan_accounts (FK validation)

Phase 4: Data Quality Validation
  └── 4a. Run data_quality_checks.py
```

### Databricks Workflow Configuration

```
Job: CDW_Migration_Pipeline
├── Task 1: create_schema     (notebook: databricks/ddl/000_schema.sql)
├── Task 2: ddl_borrowers     (notebook: databricks/ddl/001_borrowers.sql)     depends_on: [create_schema]
├── Task 3: ddl_products      (notebook: databricks/ddl/002_loan_products.sql) depends_on: [create_schema]
├── Task 4: ddl_accounts      (notebook: databricks/ddl/003_loan_accounts.sql) depends_on: [create_schema]
├── Task 5: ddl_payments      (notebook: databricks/ddl/004_payments.sql)      depends_on: [create_schema]
├── Task 6: ingest_borrowers  (script: databricks/ingestion/ingest_borrowers.py)
│                              depends_on: [ddl_borrowers]
├── Task 7: ingest_products   (script: databricks/ingestion/ingest_loan_products.py)
│                              depends_on: [ddl_products]
├── Task 8: ingest_accounts   (script: databricks/ingestion/ingest_loan_accounts.py)
│                              depends_on: [ddl_accounts, ingest_borrowers]
├── Task 9: ingest_payments   (script: databricks/ingestion/ingest_payments.py)
│                              depends_on: [ddl_payments, ingest_accounts]
└── Task 10: quality_checks   (script: databricks/quality/data_quality_checks.py)
                               depends_on: [ingest_borrowers, ingest_products, ingest_accounts, ingest_payments]
```

---

## Pre-Migration Checklist

- [ ] **Source data exported:** Legacy CDW tables exported as CSV/Parquet to the landing zone (`/mnt/landing/cdw/`)
- [ ] **Databricks cluster running:** Cluster with PySpark and Delta Lake runtime
- [ ] **Catalog/schema permissions:** Service principal has `CREATE TABLE`, `INSERT`, `SELECT` on `loan_catalog.loan_modernized`
- [ ] **Landing zone mounted:** `/mnt/landing/cdw/` accessible from the cluster
- [ ] **Source file headers match:** CSV column headers match the expected legacy column names
- [ ] **Quarantine paths writable:** `/mnt/landing/cdw/quarantine/` is writable
- [ ] **Report path writable:** `/mnt/landing/cdw/reports/` is writable

---

## Running the Pipeline

### Option A: Orchestrator Script (spark-submit)

```bash
cd databricks/ingestion
spark-submit --py-files transforms.py run_pipeline.py
```

### Option B: Databricks Workflow
Import the job configuration from the [Execution Order](#execution-order) section into your Databricks workspace as a multi-task job.

### Option C: Individual Notebooks
Run each ingestion script as a standalone Databricks notebook in the order specified above.

After ingestion completes:
```bash
cd databricks/quality
spark-submit data_quality_checks.py
```

---

## Post-Migration Validation

After the pipeline completes, the data quality framework (`databricks/quality/data_quality_checks.py`) automatically runs the following checks:

### Row Count Reconciliation
- Source row count = Target row count + Quarantine row count
- Any discrepancy indicates records were lost during transformation

### Null Checks
- All required fields (as defined in the DDL) must be non-null
- Fields: `external_id`, `first_name`, `last_name`, `account_number`, `borrower_id`, `payment_date`, etc.

### Referential Integrity
- Every `loan_accounts.borrower_id` references a valid `borrowers.borrower_id`
- Every `loan_accounts.product_code` references a valid `loan_products.code`
- Every `payments.account_number` references a valid `loan_accounts.account_number`

### Business Rules
- Active loans must have `current_balance > 0`
- Closed loans must have a `maturity_date`
- `origination_date < maturity_date` for all loans
- Interest rates in range `[0, 100]`
- LTV percentages in range `[0, 200]`
- Payment component sum ≈ total amount (±$0.02 tolerance)
- Credit scores in range `[300, 850]`
- Warning for active loans with `delinquency_days > 0`

Results are written to `DATA_QUALITY_REPORT.md` and printed to stdout.

---

## Rollback Procedure

Delta Lake supports time travel, making rollback straightforward:

```sql
-- View table history
DESCRIBE HISTORY loan_modernized.borrowers;

-- Restore to a specific version
RESTORE TABLE loan_modernized.borrowers TO VERSION AS OF 0;
RESTORE TABLE loan_modernized.loan_products TO VERSION AS OF 0;
RESTORE TABLE loan_modernized.loan_accounts TO VERSION AS OF 0;
RESTORE TABLE loan_modernized.payments TO VERSION AS OF 0;

-- Or restore to a point in time
RESTORE TABLE loan_modernized.borrowers TO TIMESTAMP AS OF '2025-01-01T00:00:00';
```

To completely remove migrated data:
```sql
DROP TABLE IF EXISTS loan_modernized.payments;
DROP TABLE IF EXISTS loan_modernized.loan_accounts;
DROP TABLE IF EXISTS loan_modernized.loan_products;
DROP TABLE IF EXISTS loan_modernized.borrowers;
DROP SCHEMA IF EXISTS loan_modernized;
```

---

## Known Edge Cases

| # | Edge Case | Handling |
|---|-----------|----------|
| 1 | NULL `BORR_MID_INIT` (e.g., Robert Williams) | Passed through as NULL — middle initial is optional |
| 2 | NULL `BORR_ADDR_LN2` | Passed through as NULL — secondary address is optional |
| 3 | Empty string dates | Converted to NULL via the `parse_date`/`parse_timestamp` functions |
| 4 | Unrecognized status codes | Mapped to `"UNKNOWN"` and logged — visible in quality report |
| 5 | Zero-value amounts (`"0"`, `"0.00"`) | Parsed normally to `DECIMAL(0.00)` — valid for fields like `late_fee` |
| 6 | Borrower not found during loan FK resolution | Loan record quarantined to `/mnt/landing/cdw/quarantine/loan_accounts` |
| 7 | Payment referencing unknown loan account | Payment still loaded (not quarantined) but flagged — may be loaded out of order |
| 8 | Duplicate legacy IDs | No dedup applied; rely on source system uniqueness. Add MERGE logic if duplicates are expected |
| 9 | Comma in amount with decimal (e.g., `"271,432.56"`) | Comma stripped, then parsed — handles mixed comma/decimal correctly |
| 10 | Late fee of `"0.00"` for on-time payments | Parsed to `DECIMAL(0.00)` — semantically correct |
