# Databricks Migration Runbook

## Legacy CDW → Modern Delta Lake Migration

This runbook documents every transformation decision, column mapping, type conversion, partitioning rationale, and the recommended execution order for migrating the legacy CDW loan management data warehouse to a modern Delta Lake schema on Databricks.

---

## Table of Contents

1. [Overview](#overview)
2. [Source System Summary](#source-system-summary)
3. [Target Schema Design](#target-schema-design)
4. [Column Mapping Reference](#column-mapping-reference)
5. [Transformation Decisions](#transformation-decisions)
6. [Partitioning Strategy](#partitioning-strategy)
7. [Execution Order](#execution-order)
8. [Data Quality Checks](#data-quality-checks)
9. [Quarantine Strategy](#quarantine-strategy)
10. [Rollback Procedure](#rollback-procedure)
11. [Post-Migration Validation](#post-migration-validation)

---

## Overview

| Attribute | Value |
|-----------|-------|
| **Source System** | Legacy CDW (Corporate Data Warehouse) — H2/RDBMS |
| **Target System** | Databricks Delta Lake (Unity Catalog) |
| **Source Tables** | `CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Target Tables** | `borrowers`, `loan_products`, `loan_accounts`, `payments` |
| **Target Database** | `loan_warehouse` |
| **Pipeline Technology** | PySpark (Databricks Runtime) |
| **Data Format** | Delta Lake with Change Data Feed enabled |

### Key Migration Goals

- Replace all-VARCHAR columns with properly typed columns (DATE, DECIMAL, INT, BOOLEAN)
- Expand cryptic column abbreviations to human-readable names
- Normalize denormalized structures (remove embedded borrower data from loan accounts)
- Establish foreign key relationships between tables
- Expand status code abbreviations to full text values
- Implement data quality validation as a post-ingestion step

---

## Source System Summary

### Legacy Schema Characteristics

| Issue | Example |
|-------|---------|
| All columns VARCHAR | `LN_CURR_BAL VARCHAR(15)` stores `"271,432.56"` |
| Cryptic names | `BORR_FST_NM` = Borrower First Name |
| Dates as strings | `BORR_DOB_DT = "03/15/1978"` (MM/DD/YYYY) |
| Amounts with commas | `LN_ORIG_AMT = "285,000"` |
| Abbreviated status codes | `ACT`, `CLO`, `DFT`, `FRB` |
| Denormalized | `CDW_LN_ACCT` contains borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) |
| No foreign keys | No constraints between tables |

### Legacy Tables

| Table | Description | Row Count (Seed) |
|-------|-------------|------------------|
| `CDW_BORR_MSTR` | Borrower master records | 5 |
| `CDW_LN_PROD` | Loan product catalog | 5 |
| `CDW_LN_ACCT` | Loan accounts (denormalized) | 5 |
| `CDW_PMT_HIST` | Payment transaction history | 10 |

---

## Target Schema Design

### `loan_warehouse.borrowers`

| Column | Type | Nullable | Source | Notes |
|--------|------|----------|--------|-------|
| `borrower_key` | BIGINT (identity) | No | — | Auto-generated surrogate key |
| `external_id` | STRING | No | `BORR_ID` | Legacy natural key preserved |
| `first_name` | STRING | No | `BORR_FST_NM` | Direct copy |
| `last_name` | STRING | No | `BORR_LST_NM` | Direct copy |
| `middle_initial` | STRING | Yes | `BORR_MID_INIT` | Direct copy |
| `ssn_hash` | STRING | Yes | `BORR_SSN_ENCR` | Direct copy; re-encryption recommended |
| `date_of_birth` | DATE | Yes | `BORR_DOB_DT` | Parsed from MM/DD/YYYY |
| `address_line1` | STRING | Yes | `BORR_ADDR_LN1` | Direct copy |
| `address_line2` | STRING | Yes | `BORR_ADDR_LN2` | Direct copy |
| `city` | STRING | Yes | `BORR_CTY_NM` | Direct copy |
| `state` | STRING | Yes | `BORR_ST_CD` | 2-char state code; used as partition key |
| `zip_code` | STRING | Yes | `BORR_ZIP_CD` | Direct copy |
| `phone` | STRING | Yes | `BORR_PH_NBR` | Direct copy |
| `email` | STRING | Yes | `BORR_EMAIL_ADDR` | Direct copy |
| `credit_score` | INT | Yes | `BORR_CRDT_SCR` | Parsed string → integer |
| `employment_status` | STRING | Yes | `BORR_EMP_STAT` | Direct copy |
| `annual_income` | DECIMAL(12,2) | Yes | `BORR_ANN_INCM` | Removed commas, parsed to decimal |
| `status` | STRING | No | `BORR_STAT_CD` | Expanded: ACT→Active, INA→Inactive |
| `created_at` | TIMESTAMP | Yes | `BORR_CRET_DT` | Parsed from MM/DD/YYYY |
| `updated_at` | TIMESTAMP | Yes | `BORR_UPDT_DT` | Parsed from MM/DD/YYYY |
| `_migration_ts` | TIMESTAMP | No | — | Pipeline execution timestamp |
| `_source_system` | STRING | No | — | Always `CDW_BORR_MSTR` |

**Dropped column:** `BORR_REC_TYP` — record type indicator not needed in the modern schema.

### `loan_warehouse.loan_products`

| Column | Type | Nullable | Source | Notes |
|--------|------|----------|--------|-------|
| `product_key` | BIGINT (identity) | No | — | Auto-generated surrogate key |
| `code` | STRING | No | `PROD_CD` | Legacy product code preserved |
| `name` | STRING | No | `PROD_DESC_TXT` | Product description |
| `type` | STRING | No | `PROD_TYP_CD` | FXD, ARM, FHA, VA |
| `term_months` | INT | No | `PROD_TERM_MOS` | Parsed string → integer |
| `rate_type` | STRING | No | `PROD_RT_TYP` | FIXED, VARIABLE |
| `min_amount` | DECIMAL(12,2) | Yes | `PROD_MIN_AMT` | Removed commas, parsed to decimal |
| `max_amount` | DECIMAL(12,2) | Yes | `PROD_MAX_AMT` | Removed commas, parsed to decimal |
| `is_active` | BOOLEAN | No | `PROD_STAT_CD` | ACT→true, INA→false |
| `effective_date` | DATE | Yes | `PROD_EFF_DT` | Parsed from MM/DD/YYYY |
| `expiration_date` | DATE | Yes | `PROD_EXP_DT` | Parsed from MM/DD/YYYY |
| `_migration_ts` | TIMESTAMP | No | — | Pipeline execution timestamp |
| `_source_system` | STRING | No | — | Always `CDW_LN_PROD` |

### `loan_warehouse.loan_accounts`

| Column | Type | Nullable | Source | Notes |
|--------|------|----------|--------|-------|
| `loan_account_key` | BIGINT (identity) | No | — | Auto-generated surrogate key |
| `account_number` | STRING | No | `LN_ACCT_NBR` | Legacy account number preserved |
| `borrower_key` | BIGINT | No | `BORR_ID` | FK → `borrowers.borrower_key` (resolved via `external_id` lookup) |
| `product_key` | BIGINT | No | `PROD_CD` | FK → `loan_products.product_key` (resolved via `code` lookup) |
| `original_amount` | DECIMAL(12,2) | No | `LN_ORIG_AMT` | Removed commas, parsed to decimal |
| `current_balance` | DECIMAL(12,2) | No | `LN_CURR_BAL` | Removed commas, parsed to decimal |
| `interest_rate` | DECIMAL(5,3) | No | `LN_INT_RT` | Parsed string → decimal |
| `term_months` | INT | No | `LN_TERM_MOS` | Parsed string → integer |
| `monthly_payment` | DECIMAL(10,2) | No | `LN_PMT_AMT` | Removed commas, parsed to decimal |
| `origination_date` | DATE | No | `LN_ORIG_DT` | Parsed from MM/DD/YYYY |
| `maturity_date` | DATE | No | `LN_MAT_DT` | Parsed from MM/DD/YYYY |
| `first_payment_date` | DATE | Yes | `LN_1ST_PMT_DT` | Parsed from MM/DD/YYYY |
| `next_payment_date` | DATE | Yes | `LN_NXT_PMT_DT` | Parsed from MM/DD/YYYY |
| `status` | STRING | No | `LN_STAT_CD` | Expanded (see mapping below) |
| `delinquency_days` | INT | Yes | `LN_DLQ_DAYS` | Parsed string → integer |
| `escrow_balance` | DECIMAL(10,2) | Yes | `LN_ESCROW_BAL` | Removed commas, parsed to decimal |
| `ltv_percent` | DECIMAL(5,2) | Yes | `LN_LTV_PCT` | Parsed string → decimal |
| `property_address` | STRING | Yes | `PROP_ADDR_LN1` | Direct copy |
| `property_city` | STRING | Yes | `PROP_CTY_NM` | Direct copy |
| `property_state` | STRING | Yes | `PROP_ST_CD` | Direct copy |
| `property_zip` | STRING | Yes | `PROP_ZIP_CD` | Direct copy |
| `property_type` | STRING | Yes | `PROP_TYP_CD` | Expanded (see mapping below) |
| `appraised_value` | DECIMAL(12,2) | Yes | `PROP_APRS_VAL` | Removed commas, parsed to decimal |
| `created_at` | TIMESTAMP | Yes | `LN_CRET_DT` | Parsed from MM/DD/YYYY |
| `updated_at` | TIMESTAMP | Yes | `LN_UPDT_DT` | Parsed from MM/DD/YYYY |
| `origination_year` | INT | No | Derived | `year(origination_date)` — partition column |
| `_migration_ts` | TIMESTAMP | No | — | Pipeline execution timestamp |
| `_source_system` | STRING | No | — | Always `CDW_LN_ACCT` |

**Dropped columns:** `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` — these were denormalized borrower fields embedded in the legacy loan account table. In the modern schema, borrower data is accessed via `borrower_key` FK.

### `loan_warehouse.payments`

| Column | Type | Nullable | Source | Notes |
|--------|------|----------|--------|-------|
| `payment_key` | BIGINT (identity) | No | — | Auto-generated surrogate key |
| `legacy_sequence_id` | STRING | Yes | `PMT_SEQ_NBR` | Preserved for audit traceability |
| `loan_account_key` | BIGINT | No | `LN_ACCT_NBR` | FK → `loan_accounts.loan_account_key` (resolved via `account_number` lookup) |
| `payment_date` | DATE | No | `PMT_DT` | Parsed from MM/DD/YYYY |
| `total_amount` | DECIMAL(10,2) | No | `PMT_AMT` | Removed commas, parsed to decimal |
| `principal_amount` | DECIMAL(10,2) | Yes | `PMT_PRIN_AMT` | Removed commas, parsed to decimal |
| `interest_amount` | DECIMAL(10,2) | Yes | `PMT_INT_AMT` | Removed commas, parsed to decimal |
| `escrow_amount` | DECIMAL(10,2) | Yes | `PMT_ESCROW_AMT` | Removed commas, parsed to decimal |
| `late_fee` | DECIMAL(10,2) | Yes | `PMT_LATE_FEE` | Removed commas, parsed to decimal |
| `type` | STRING | No | `PMT_TYP_CD` | Expanded (see mapping below) |
| `status` | STRING | No | `PMT_STAT_CD` | Expanded (see mapping below) |
| `received_date` | DATE | Yes | `PMT_RECV_DT` | Parsed from MM/DD/YYYY |
| `processed_date` | DATE | Yes | `PMT_PROC_DT` | Parsed from MM/DD/YYYY |
| `created_at` | TIMESTAMP | Yes | `PMT_CRET_DT` | Parsed from MM/DD/YYYY |
| `updated_at` | TIMESTAMP | Yes | `PMT_UPDT_DT` | Parsed from MM/DD/YYYY |
| `payment_year` | INT | No | Derived | `year(payment_date)` — partition column |
| `_migration_ts` | TIMESTAMP | No | — | Pipeline execution timestamp |
| `_source_system` | STRING | No | — | Always `CDW_PMT_HIST` |

---

## Column Mapping Reference

### Status Code Expansions

#### Borrower Status (`BORR_STAT_CD`)

| Legacy Code | Modern Value |
|-------------|-------------|
| `ACT` | `Active` |
| `INA` | `Inactive` |
| *(other)* | `Unknown` |

#### Loan Status (`LN_STAT_CD`)

| Legacy Code | Modern Value |
|-------------|-------------|
| `ACT` | `Active` |
| `CLO` | `Closed` |
| `DFT` | `Default` |
| `FRB` | `Forbearance` |
| *(other)* | `Unknown` |

#### Product Status (`PROD_STAT_CD`)

| Legacy Code | Modern Value |
|-------------|-------------|
| `ACT` | `true` (boolean) |
| `INA` | `false` (boolean) |
| *(other)* | `false` |

#### Payment Type (`PMT_TYP_CD`)

| Legacy Code | Modern Value |
|-------------|-------------|
| `REG` | `Regular` |
| `EXT` | `Extra` |
| `PRT` | `Partial` |
| `PRE` | `Prepayment` |
| *(other)* | `Unknown` |

#### Payment Status (`PMT_STAT_CD`)

| Legacy Code | Modern Value |
|-------------|-------------|
| `PST` | `Posted` |
| `REV` | `Reversed` |
| `NSF` | `NSF` |
| `PND` | `Pending` |
| *(other)* | `Unknown` |

#### Property Type (`PROP_TYP_CD`)

| Legacy Code | Modern Value |
|-------------|-------------|
| `SFR` | `Single Family` |
| `CND` | `Condominium` |
| `MFR` | `Multi-Family` |
| `TWN` | `Townhouse` |
| *(other)* | `Other` |

---

## Transformation Decisions

### 1. Date Conversion Strategy

**Decision:** Parse all `MM/DD/YYYY` strings using PySpark `to_date()` / `to_timestamp()` with format `"MM/dd/yyyy"`.

**Rationale:** The legacy system stores all dates as VARCHAR in `MM/DD/YYYY` format. Spark's built-in date parsing handles this natively. Dates map to `DATE`, while created/updated timestamps map to `TIMESTAMP` (midnight on the given day, since legacy has no time component).

**Edge cases:** If a date string is malformed or null, `to_date()` returns `null`. Records with null values in required date fields (e.g., `origination_date`) are routed to quarantine.

### 2. Amount Conversion Strategy

**Decision:** Strip commas using `regexp_replace(col, ",", "")` then cast to `DECIMAL(p,s)`.

**Rationale:** Legacy amounts like `"285,000"` and `"271,432.56"` use US-locale comma formatting. Removing commas and casting is the most reliable approach for this format.

**Precision choices:**
- `DECIMAL(12,2)` for large monetary values (loan amounts, balances, appraised values, income) — supports up to $9,999,999,999.99
- `DECIMAL(10,2)` for payment-level amounts — supports up to $99,999,999.99
- `DECIMAL(5,3)` for interest rates — supports rates up to 99.999%
- `DECIMAL(5,2)` for LTV percentages — supports up to 999.99%

### 3. Denormalization Removal

**Decision:** Drop `BORR_FST_NM`, `BORR_LST_NM`, and `BORR_SSN_LST4` from `CDW_LN_ACCT`. Replace with `borrower_key` FK referencing the `borrowers` table.

**Rationale:** The legacy schema embedded borrower fields directly in the loan accounts table, creating data redundancy and potential inconsistency. The modern schema normalizes this into a proper dimension table with FK lookup.

**Implementation:** During ingestion, `BORR_ID` from `CDW_LN_ACCT` is used to look up `borrower_key` via a left join on `borrowers.external_id`. If the lookup fails (orphan record), the loan account is quarantined.

### 4. Foreign Key Resolution

**Decision:** Use broadcast join lookups to resolve legacy natural keys to modern surrogate keys.

| FK | Source Column | Lookup Table | Lookup Column | Target Column |
|----|---------------|-------------|---------------|---------------|
| `loan_accounts.borrower_key` | `CDW_LN_ACCT.BORR_ID` | `borrowers` | `external_id` | `borrower_key` |
| `loan_accounts.product_key` | `CDW_LN_ACCT.PROD_CD` | `loan_products` | `code` | `product_key` |
| `payments.loan_account_key` | `CDW_PMT_HIST.LN_ACCT_NBR` | `loan_accounts` | `account_number` | `loan_account_key` |

**Failure handling:** If a FK lookup returns null (unresolved reference), the record is quarantined rather than silently dropped.

### 5. Status Code Expansion

**Decision:** Map abbreviated codes to human-readable values using PySpark `create_map()` lookups. Unknown codes map to a default value (`"Unknown"` for strings, `false` for booleans).

**Rationale:** Abbreviated codes like `ACT`, `CLO`, `DFT` are opaque to downstream consumers. Expanding them improves readability and reduces the need for reference table joins in analytics queries.

### 6. Surrogate Keys

**Decision:** Use `GENERATED ALWAYS AS IDENTITY` for all primary keys in Delta Lake tables.

**Rationale:** Legacy natural keys (e.g., `B-10001`, `LN-2019-00142`) are preserved as `external_id` / `account_number` columns but are not used as primary keys. Surrogate BIGINT keys provide better join performance and are standard in modern data warehouses.

### 7. Audit Columns

**Decision:** Add `_migration_ts` and `_source_system` to every target table.

**Rationale:** These columns provide traceability for migrated records — when they were loaded and from which source table. This is essential for debugging and audit compliance.

---

## Partitioning Strategy

| Table | Partition Column | Rationale |
|-------|-----------------|-----------|
| `borrowers` | `state` | Geographic partitioning supports regional queries and regulatory reporting by state. With ~50 distinct values, partition count stays manageable. |
| `loan_products` | *(none)* | Small reference table (~5–50 rows). Partitioning would create overhead with no benefit. |
| `loan_accounts` | `origination_year` | Time-based partitioning enables efficient portfolio-vintage analysis, year-over-year comparisons, and partition pruning for date-range queries. |
| `payments` | `payment_year` | Payment queries are overwhelmingly time-based (monthly reporting, year-end reconciliation). Year partitioning provides good partition pruning without excessive partition count. |

### Delta Lake Table Properties

All tables are configured with:
- `delta.enableChangeDataFeed = true` — enables downstream CDC consumers
- `delta.autoOptimize.optimizeWrite = true` — coalesces small files on write
- `delta.autoOptimize.autoCompact = true` — triggers automatic file compaction

---

## Execution Order

The pipeline must run in dependency order due to FK resolution:

```
Step 1: Run DDL scripts (create database and tables)
Step 2: Ingest borrowers     (no dependencies)
Step 3: Ingest loan_products  (no dependencies)
Step 4: Ingest loan_accounts  (depends on borrowers + loan_products)
Step 5: Ingest payments       (depends on loan_accounts)
Step 6: Run data quality checks
```

### Databricks Execution

#### Option A: Databricks Workflow (Recommended)

Create a multi-task job with the following DAG:

```
[create_database] → [ingest_borrowers] ──────┐
                  → [ingest_loan_products] ───┤
                                              ├→ [ingest_loan_accounts] → [ingest_payments] → [quality_checks]
```

Steps 2 and 3 can run in parallel. Steps 4 and 5 are sequential.

#### Option B: Single Notebook / Script

Run `databricks/ingestion/run_pipeline.py` which executes all steps sequentially in the correct order.

#### Option C: Manual Notebook Execution

1. Run `databricks/ddl/00_database.sql`
2. Run `databricks/ddl/01_borrowers.sql`
3. Run `databricks/ddl/02_loan_products.sql`
4. Run `databricks/ddl/03_loan_accounts.sql`
5. Run `databricks/ddl/04_payments.sql`
6. Run `databricks/ingestion/ingest_borrowers.py`
7. Run `databricks/ingestion/ingest_loan_products.py`
8. Run `databricks/ingestion/ingest_loan_accounts.py`
9. Run `databricks/ingestion/ingest_payments.py`
10. Run `databricks/quality/run_quality_checks.py`

---

## Data Quality Checks

The quality framework (`databricks/quality/`) runs four categories of checks after ingestion:

### 1. Row Count Reconciliation

Compares source record counts (from ingestion pipeline output) against target table counts. Any mismatch indicates lost or duplicated records.

### 2. Null Checks on Required Fields

Verifies that columns marked NOT NULL in the target schema contain no null values. Covers:
- `borrowers`: external_id, first_name, last_name, status
- `loan_products`: code, name, type, term_months, rate_type
- `loan_accounts`: account_number, borrower_key, product_key, all financial fields, dates, status
- `payments`: loan_account_key, payment_date, total_amount, type, status

### 3. Referential Integrity

Validates FK relationships using left-anti joins:
- `loan_accounts.borrower_key` → `borrowers.borrower_key`
- `loan_accounts.product_key` → `loan_products.product_key`
- `payments.loan_account_key` → `loan_accounts.loan_account_key`

### 4. Business Rule Validation

| Rule | Description |
|------|-------------|
| Active balance > 0 | Active loans must have `current_balance > 0` |
| Closed loan maturity | Closed loans must have `maturity_date <= today` |
| Payment amount > 0 | All payment `total_amount` must be positive |
| Delinquency >= 0 | `delinquency_days` must be non-negative |
| Interest rate range | `interest_rate` must be between 0 and 30% |
| Date ordering | `origination_date` must precede `maturity_date` |
| Active payment > 0 | Active loans must have `monthly_payment > 0` |

---

## Quarantine Strategy

Records that fail validation during ingestion are not silently dropped. Instead:

1. **Quarantine paths:** Failed records are written to Delta Lake tables at:
   - `dbfs:/mnt/quarantine/borrowers/`
   - `dbfs:/mnt/quarantine/loan_products/`
   - `dbfs:/mnt/quarantine/loan_accounts/`
   - `dbfs:/mnt/quarantine/payments/`

2. **Quarantine reasons include:**
   - Required fields are null after transformation
   - FK lookup failed (orphan records)
   - Date parsing produced null on a required date field

3. **Resolution:** Review quarantined records, fix source data or mapping logic, and re-run the ingestion for the affected table.

---

## Rollback Procedure

Delta Lake supports time travel, enabling safe rollback:

```sql
-- Check table history
DESCRIBE HISTORY loan_warehouse.borrowers;

-- Rollback to previous version
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF <version_number>;

-- Or rollback to a timestamp
RESTORE TABLE loan_warehouse.loan_accounts TO TIMESTAMP AS OF '2025-01-01T00:00:00';
```

For a full rollback, restore all four tables to the version before the migration run.

---

## Post-Migration Validation

After the pipeline completes and quality checks pass, perform these manual validations:

1. **Spot-check records:** Query a sample of borrowers, loans, and payments and compare against the legacy source
2. **Aggregate validation:** Compare sum of `current_balance` across all active loans between legacy and modern
3. **Date integrity:** Verify that no dates were shifted during parsing (compare a few records manually)
4. **FK chain:** Pick a payment, trace it to its loan account, then to the borrower — verify the chain is correct
5. **Status distribution:** Compare the count of records per status in legacy vs. modern to ensure code expansion was correct

### Sample Validation Queries

```sql
-- Compare borrower counts
SELECT status, COUNT(*) FROM loan_warehouse.borrowers GROUP BY status;

-- Verify loan-borrower FK chain
SELECT l.account_number, b.first_name, b.last_name, l.status, l.current_balance
FROM loan_warehouse.loan_accounts l
JOIN loan_warehouse.borrowers b ON l.borrower_key = b.borrower_key;

-- Sum of active loan balances
SELECT SUM(current_balance) FROM loan_warehouse.loan_accounts WHERE status = 'Active';

-- Payment reconciliation by loan
SELECT la.account_number, COUNT(p.payment_key) as pmt_count, SUM(p.total_amount) as total_paid
FROM loan_warehouse.payments p
JOIN loan_warehouse.loan_accounts la ON p.loan_account_key = la.loan_account_key
GROUP BY la.account_number;
```
