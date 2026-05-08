# Databricks Migration Runbook

## Legacy CDW to Delta Lake — Loan Management System

This runbook documents every transformation decision, column mapping, type conversion,
partitioning rationale, and the recommended execution order for migrating the legacy
Corporate Data Warehouse (CDW) to a modern Delta Lake schema on Databricks.

---

## Table of Contents

1. [Overview](#overview)
2. [Source System Summary](#source-system-summary)
3. [Target Schema Summary](#target-schema-summary)
4. [Column Mapping Reference](#column-mapping-reference)
5. [Transformation Decisions](#transformation-decisions)
6. [Partitioning Rationale](#partitioning-rationale)
7. [Execution Order](#execution-order)
8. [Data Quality Checks](#data-quality-checks)
9. [Known Data Anomalies](#known-data-anomalies)
10. [Rollback Procedure](#rollback-procedure)

---

## Overview

| Item | Detail |
|------|--------|
| **Source** | Legacy CDW — 4 H2 tables, all-VARCHAR columns, no FK constraints |
| **Target** | Databricks Delta Lake — `loan_warehouse` database, proper types, FK relationships |
| **Tables** | `borrowers`, `loan_products`, `loan_accounts`, `payments` |
| **Record volume** | 5 borrowers, 5 products, 5 loan accounts, 10 payments (seed data) |
| **Pipeline** | PySpark ingestion scripts with quarantine pattern |
| **Quality framework** | Automated checks: row counts, nulls, referential integrity, business rules |

---

## Source System Summary

The legacy CDW uses four tables with the following characteristics:

### CDW_BORR_MSTR (Borrower Master)
- **Rows:** 5
- **Key issues:** All columns VARCHAR, dates as `MM/DD/YYYY` strings, income as comma-formatted
  string (`"92,500"`), credit score as string, no NOT NULL constraints
- **Primary key:** `BORR_ID` (e.g., `B-10001`)

### CDW_LN_PROD (Loan Products)
- **Rows:** 5
- **Key issues:** Amounts as comma-formatted strings, status as abbreviation (`ACT`/`INA`),
  term as string
- **Primary key:** `PROD_CD` (e.g., `FXD30`, `ARM51`)

### CDW_LN_ACCT (Loan Accounts)
- **Rows:** 5
- **Key issues:** Denormalized borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`),
  all amounts and rates as strings, status codes (`ACT`, `CLO`, `DFT`, `FRB`), property type
  codes (`SFR`, `CND`, `MFR`, `TWN`), no FK constraints to borrower/product tables
- **Primary key:** `LN_ACCT_NBR` (e.g., `LN-2019-00142`)
- **Known anomaly:** Loan `LN-2018-00089` has `LN_STAT_CD = 'ACT'` but `LN_DLQ_DAYS = '15'`

### CDW_PMT_HIST (Payment History)
- **Rows:** 10
- **Key issues:** All amounts as comma-formatted strings, dates as `MM/DD/YYYY` strings,
  type/status codes abbreviated, no FK constraint to loan accounts
- **Known anomaly:** Several payments have component sums (principal + interest + escrow +
  late fee) that do not equal the stated total amount

---

## Target Schema Summary

All target tables are created in the `loan_warehouse` database using Delta Lake format.

| Target Table | Source Table | Partitioned By | Key Changes |
|--------------|-------------|----------------|-------------|
| `borrowers` | CDW_BORR_MSTR | — | `BORR_REC_TYP` dropped, dates to DATE/TIMESTAMP, amounts to DECIMAL, status expanded |
| `loan_products` | CDW_LN_PROD | — | Status to BOOLEAN (`is_active`), amounts to DECIMAL, dates to DATE |
| `loan_accounts` | CDW_LN_ACCT | `status` | Denormalized borrower cols dropped, FKs to borrowers/products resolved, status/property codes expanded |
| `payments` | CDW_PMT_HIST | `payment_year` | FK to loan_accounts resolved, type/status codes expanded, `payment_year` derived |

All tables include ingestion metadata columns:
- `_legacy_source` — Source table name for lineage tracking
- `_ingested_at` — Pipeline execution timestamp

---

## Column Mapping Reference

### CDW_BORR_MSTR → `borrowers`

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `BORR_ID` | `external_id` | VARCHAR → STRING | Direct copy; legacy ID preserved for lineage |
| `BORR_FST_NM` | `first_name` | VARCHAR → STRING (NOT NULL) | Trimmed; null → quarantine |
| `BORR_LST_NM` | `last_name` | VARCHAR → STRING (NOT NULL) | Trimmed; null → quarantine |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR → STRING | Nullable; trimmed |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR → STRING (NOT NULL) | Re-encryption recommended post-migration |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR → DATE | `MM/dd/yyyy` → `to_date()` |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR → STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR → STRING | Nullable |
| `BORR_CTY_NM` | `city` | VARCHAR → STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR → STRING | Direct copy |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR → STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR → STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR → STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR → INT (NOT NULL) | Validated range 300–850; out-of-range → quarantine |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR → STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR → DECIMAL(12,2) (NOT NULL) | Commas stripped via `regexp_replace("[,$]", "")` |
| `BORR_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | `MM/dd/yyyy` → `to_timestamp()` (midnight) |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | `MM/dd/yyyy` → `to_timestamp()` (midnight) |
| `BORR_STAT_CD` | `status` | VARCHAR → STRING (NOT NULL) | `ACT` → `ACTIVE`, `INA` → `INACTIVE` |
| `BORR_REC_TYP` | *(dropped)* | — | No business value in modern schema |

### CDW_LN_PROD → `loan_products`

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `PROD_CD` | `code` | VARCHAR → STRING (NOT NULL) | Natural key preserved |
| `PROD_DESC_TXT` | `name` | VARCHAR → STRING (NOT NULL) | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR → STRING (NOT NULL) | `FXD`, `ARM`, `FHA`, `VA` kept as-is |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT (NOT NULL) | `cast(IntegerType())` |
| `PROD_RT_TYP` | `rate_type` | VARCHAR → STRING (NOT NULL) | `FIXED` or `VARIABLE` |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) (NOT NULL) | Commas stripped |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) (NOT NULL) | Commas stripped |
| `PROD_STAT_CD` | `is_active` | VARCHAR → BOOLEAN (NOT NULL) | `ACT` → `true`, anything else → `false` |
| `PROD_EFF_DT` | `effective_date` | VARCHAR → DATE (NOT NULL) | `MM/dd/yyyy` → `to_date()` |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR → DATE (NOT NULL) | `MM/dd/yyyy` → `to_date()` |

### CDW_LN_ACCT → `loan_accounts`

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `LN_ACCT_NBR` | `account_number` | VARCHAR → STRING (NOT NULL) | Natural key preserved |
| `BORR_ID` | `borrower_id` | VARCHAR → BIGINT (NOT NULL) | Resolved via join to `borrowers.external_id`; orphans get `-1` → quarantine |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK instead |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK instead |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK instead |
| `PROD_CD` | `product_id` | VARCHAR → BIGINT (NOT NULL) | Resolved via join to `loan_products.code`; orphans get `-1` → quarantine |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) (NOT NULL) | Commas stripped |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) (NOT NULL) | Commas stripped |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) (NOT NULL) | Parsed directly (e.g., `"5.250"` → `5.250`) |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT (NOT NULL) | `cast(IntegerType())` |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) (NOT NULL) | Commas stripped |
| `LN_ORIG_DT` | `origination_date` | VARCHAR → DATE (NOT NULL) | `MM/dd/yyyy` → `to_date()` |
| `LN_MAT_DT` | `maturity_date` | VARCHAR → DATE (NOT NULL) | `MM/dd/yyyy` → `to_date()` |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR → DATE (NOT NULL) | `MM/dd/yyyy` → `to_date()` |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR → DATE (NOT NULL) | `MM/dd/yyyy` → `to_date()` |
| `LN_STAT_CD` | `status` | VARCHAR → STRING (NOT NULL) | `ACT`→`ACTIVE`, `CLO`→`CLOSED`, `DFT`→`DEFAULT`, `FRB`→`FORBEARANCE` |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT (NOT NULL) | Defaults to `0` if null |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Commas stripped |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | Parsed directly |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR → STRING | `SFR`→`Single Family`, `CND`→`Condominium`, `MFR`→`Multi-Family`, `TWN`→`Townhouse` |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Commas stripped |
| `LN_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP (NOT NULL) | `MM/dd/yyyy` → `to_timestamp()` |
| `LN_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP (NOT NULL) | `MM/dd/yyyy` → `to_timestamp()` |

### CDW_PMT_HIST → `payments`

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `PMT_SEQ_NBR` | `legacy_payment_id` | VARCHAR → STRING (NOT NULL) | Preserved for lineage; surrogate `id` auto-generated |
| `LN_ACCT_NBR` | `loan_account_id` | VARCHAR → BIGINT (NOT NULL) | Resolved via join to `loan_accounts.account_number`; orphans → quarantine |
| `PMT_DT` | `payment_date` | VARCHAR → DATE (NOT NULL) | `MM/dd/yyyy` → `to_date()` |
| `PMT_AMT` | `total_amount` | VARCHAR → DECIMAL(10,2) (NOT NULL) | Commas stripped |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR → DECIMAL(10,2) (NOT NULL) | Commas stripped |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR → DECIMAL(10,2) (NOT NULL) | Commas stripped |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR → DECIMAL(10,2) (NOT NULL) | Commas stripped |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR → DECIMAL(10,2) (NOT NULL) | Defaults to `0` if null; commas stripped |
| `PMT_TYP_CD` | `type` | VARCHAR → STRING (NOT NULL) | `REG`→`REGULAR`, `EXT`→`EXTRA`, `PRT`→`PARTIAL`, `PRE`→`PREPAYMENT` |
| `PMT_STAT_CD` | `status` | VARCHAR → STRING (NOT NULL) | `PST`→`POSTED`, `REV`→`REVERSED`, `NSF`→`NSF`, `PND`→`PENDING` |
| `PMT_RECV_DT` | `received_date` | VARCHAR → DATE | `MM/dd/yyyy` → `to_date()` |
| `PMT_PROC_DT` | `processed_date` | VARCHAR → DATE | `MM/dd/yyyy` → `to_date()` |
| `PMT_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP (NOT NULL) | `MM/dd/yyyy` → `to_timestamp()` |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP (NOT NULL) | `MM/dd/yyyy` → `to_timestamp()` |
| *(derived)* | `payment_year` | — → INT (NOT NULL) | Extracted from `payment_date` for partitioning |

---

## Transformation Decisions

### 1. Date Parsing Strategy

**Decision:** Use PySpark's `to_date(col, "MM/dd/yyyy")` and `to_timestamp(col, "MM/dd/yyyy")`.

**Rationale:** All legacy date columns use the `MM/DD/YYYY` format consistently. Spark's
built-in date parser handles this format natively. Timestamps default to midnight (`00:00:00`)
since the legacy system only stores dates, not times.

**Edge case:** Invalid dates (e.g., `02/29/2023` in a non-leap year) will produce `NULL`
via Spark's default ANSI mode. These records will be caught by the null-check quality
validation and quarantined.

### 2. Amount Parsing Strategy

**Decision:** Use `regexp_replace(col, "[,$]", "")` followed by `.cast(DecimalType(p, s))`.

**Rationale:** Legacy amounts are stored as comma-formatted strings (e.g., `"285,000"`,
`"1,487.02"`). Some may include dollar signs. The regex strips both commas and dollar signs
before casting to `DecimalType` for exact decimal arithmetic (no floating-point errors).

**Precision choices:**
- `DECIMAL(12,2)` for loan amounts and appraised values (up to $9,999,999,999.99)
- `DECIMAL(10,2)` for payment amounts and escrow balances
- `DECIMAL(5,3)` for interest rates (e.g., `5.250`)
- `DECIMAL(5,2)` for LTV percentages (e.g., `82.50`)

### 3. Status Code Expansion

**Decision:** Expand abbreviated codes to human-readable strings using hardcoded mappings.

**Rationale:** The legacy system uses terse codes that are unintelligible to business users.
Expanding them improves readability and reduces the need for code-table lookups in downstream
analytics.

| Context | Code | Expanded Value |
|---------|------|---------------|
| Loan status | `ACT` | `ACTIVE` |
| Loan status | `CLO` | `CLOSED` |
| Loan status | `DFT` | `DEFAULT` |
| Loan status | `FRB` | `FORBEARANCE` |
| Borrower status | `ACT` | `ACTIVE` |
| Borrower status | `INA` | `INACTIVE` |
| Product status | `ACT` | `true` (boolean) |
| Product status | `INA` | `false` (boolean) |
| Property type | `SFR` | `Single Family` |
| Property type | `CND` | `Condominium` |
| Property type | `MFR` | `Multi-Family` |
| Property type | `TWN` | `Townhouse` |
| Payment type | `REG` | `REGULAR` |
| Payment type | `EXT` | `EXTRA` |
| Payment type | `PRT` | `PARTIAL` |
| Payment type | `PRE` | `PREPAYMENT` |
| Payment status | `PST` | `POSTED` |
| Payment status | `REV` | `REVERSED` |
| Payment status | `NSF` | `NSF` |
| Payment status | `PND` | `PENDING` |

**Unknown codes:** Preserved as-is (not silently dropped) so they surface in quality checks.

### 4. Denormalization Removal

**Decision:** Drop `BORR_FST_NM`, `BORR_LST_NM`, and `BORR_SSN_LST4` from `loan_accounts`.

**Rationale:** The legacy `CDW_LN_ACCT` table embeds borrower data that is redundant with
`CDW_BORR_MSTR`. In the modern schema, `loan_accounts.borrower_id` is a proper foreign key
to the `borrowers` dimension table. This eliminates data drift risk (where the embedded copy
diverges from the master record).

**Risk:** If the `BORR_ID` in a loan account doesn't match any `borrowers.external_id`, the
FK resolution sets `borrower_id = -1`, which triggers quarantine. This is safer than silently
dropping the loan record.

### 5. Foreign Key Resolution

**Decision:** Resolve legacy string IDs to surrogate BIGINT keys via lookup joins during ingestion.

**Resolution chain:**
1. `CDW_LN_ACCT.BORR_ID` → `borrowers.id` (via `borrowers.external_id`)
2. `CDW_LN_ACCT.PROD_CD` → `loan_products.id` (via `loan_products.code`)
3. `CDW_PMT_HIST.LN_ACCT_NBR` → `loan_accounts.id` (via `loan_accounts.account_number`)

**Orphan handling:** Records with unresolvable FKs are assigned `-1` and routed to quarantine
tables for manual review rather than being silently dropped.

### 6. Quarantine Pattern

**Decision:** Bad records (null required fields, invalid FKs, out-of-range values) are written
to `_quarantine_*` tables instead of being dropped.

**Tables:**
- `loan_warehouse._quarantine_borrowers`
- `loan_warehouse._quarantine_loan_products`
- `loan_warehouse._quarantine_loan_accounts`
- `loan_warehouse._quarantine_payments`

**Rationale:** In a regulated financial context, silently dropping records is unacceptable.
Quarantine tables preserve all original data for audit and manual remediation.

---

## Partitioning Rationale

### `loan_accounts` — Partitioned by `status`

**Rationale:** Most analytical queries segment loans by lifecycle stage:
- "Show all active loans" (portfolio monitoring)
- "List defaulted loans" (risk reporting)
- "Count closed loans this quarter" (performance metrics)

With only 4 distinct status values (`ACTIVE`, `CLOSED`, `DEFAULT`, `FORBEARANCE`), the
partition cardinality is low, which is ideal for Delta Lake. Partition pruning eliminates
scanning irrelevant partitions for status-filtered queries.

**Alternative considered:** Partitioning by origination year was considered but rejected
because most operational queries filter by status rather than origination date.

### `payments` — Partitioned by `payment_year`

**Rationale:** Payment queries are overwhelmingly time-range scans:
- "Show payments for Q4 2025" (period-end reconciliation)
- "List all payments for loan X in 2025" (account history)

Partitioning by year provides good partition pruning for these patterns while keeping
cardinality manageable. The `payment_year` column is derived from `payment_date` during
ingestion using `F.year(F.col("payment_date"))`.

### `borrowers` and `loan_products` — Not partitioned

**Rationale:** These are small dimension tables (5 rows each in seed data, typically < 100K
in production). Partitioning would add overhead without meaningful query performance benefit.

---

## Execution Order

The ingestion scripts **must** be executed in the following order due to FK resolution
dependencies:

```
Step 1: Create database and tables (DDL)
Step 2: Ingest borrowers       (no FK dependencies)
Step 3: Ingest loan_products   (no FK dependencies)
Step 4: Ingest loan_accounts   (depends on borrowers + loan_products)
Step 5: Ingest payments        (depends on loan_accounts)
Step 6: Run data quality checks
Step 7: Generate quality report
```

### Databricks Workflow Jobs Configuration

```
Job: legacy_cdw_migration
├── Task 1: create_schema
│   ├── Type: SQL
│   ├── Script: databricks/ddl/borrowers.sql
│   │           databricks/ddl/loan_products.sql
│   │           databricks/ddl/loan_accounts.sql
│   │           databricks/ddl/payments.sql
│   └── Depends on: (none)
│
├── Task 2a: ingest_borrowers
│   ├── Type: Python
│   ├── Script: databricks/ingestion/ingest_borrowers.py
│   └── Depends on: create_schema
│
├── Task 2b: ingest_loan_products
│   ├── Type: Python
│   ├── Script: databricks/ingestion/ingest_loan_products.py
│   └── Depends on: create_schema
│
├── Task 3: ingest_loan_accounts
│   ├── Type: Python
│   ├── Script: databricks/ingestion/ingest_loan_accounts.py
│   └── Depends on: ingest_borrowers, ingest_loan_products
│
├── Task 4: ingest_payments
│   ├── Type: Python
│   ├── Script: databricks/ingestion/ingest_payments.py
│   └── Depends on: ingest_loan_accounts
│
└── Task 5: data_quality_checks
    ├── Type: Python
    ├── Script: databricks/quality/data_quality_checks.py
    │           databricks/quality/report_generator.py
    └── Depends on: ingest_payments
```

> **Note:** Tasks 2a and 2b (borrowers and loan_products) can run in **parallel** since
> neither depends on the other. Task 3 waits for both to complete before resolving FKs.

---

## Data Quality Checks

After ingestion, the quality framework (`databricks/quality/data_quality_checks.py`) runs
four categories of validation:

### 1. Row Count Reconciliation
Compares source row counts to target table counts. Target may be lower than source if records
were quarantined. Target should **never** be higher than source.

### 2. Null Checks on Required Fields
Verifies that all NOT NULL columns in the modern schema contain no nulls. Fields checked:

| Table | Required Columns |
|-------|-----------------|
| `borrowers` | `external_id`, `first_name`, `last_name`, `ssn_hash`, `date_of_birth`, `credit_score`, `annual_income`, `created_at`, `updated_at`, `status` |
| `loan_products` | `code`, `name`, `type`, `term_months`, `min_amount`, `max_amount`, `is_active`, `effective_date`, `expiration_date` |
| `loan_accounts` | `account_number`, `borrower_id`, `product_id`, `original_amount`, `current_balance`, `interest_rate`, `origination_date`, `maturity_date`, `status`, `created_at`, `updated_at` |
| `payments` | `legacy_payment_id`, `loan_account_id`, `payment_date`, `total_amount`, `type`, `status`, `created_at`, `updated_at` |

### 3. Referential Integrity
Verifies FK relationships using left anti joins:
- `loan_accounts.borrower_id` → `borrowers.id`
- `loan_accounts.product_id` → `loan_products.id`
- `payments.loan_account_id` → `loan_accounts.id`

### 4. Business Rule Validation
- Active loans must have `current_balance > 0`
- Active loans should have `delinquency_days = 0`
- Credit scores must be in FICO range 300–850
- Payment component sum (principal + interest + escrow + late fee) must match total within $1.00
- `origination_date` must precede `maturity_date`

---

## Known Data Anomalies

These anomalies exist in the legacy seed data and will be detected by the quality checks:

| ID | Severity | Description | Affected Record |
|----|----------|-------------|----------------|
| ANO-001 | Critical | Payment component sums don't equal total amount | Multiple PMT_SEQ_NBR records |
| ANO-002 | Critical | Malformed numeric strings risk NumberFormatException | Edge case in production data |
| ANO-003 | High | Loan LN-2018-00089 has `ACT` status with 15 delinquency days | LN-2018-00089 |
| ANO-004 | High | No NOT NULL constraints in legacy schema | All tables |
| ANO-005 | High | Denormalized borrower data may drift from master | CDW_LN_ACCT |
| ANO-006 | High | No foreign key constraints in legacy schema | All cross-table references |

For full details, see [`docs/DATA_ANOMALY_REPORT.md`](DATA_ANOMALY_REPORT.md).

---

## Rollback Procedure

Delta Lake supports time travel, making rollback straightforward:

```sql
-- View table history to find the version before migration
DESCRIBE HISTORY loan_warehouse.borrowers;

-- Restore to a specific version
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF <version_number>;
RESTORE TABLE loan_warehouse.loan_products TO VERSION AS OF <version_number>;
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF <version_number>;
RESTORE TABLE loan_warehouse.payments TO VERSION AS OF <version_number>;
```

For a full reset (drop and recreate):

```sql
DROP TABLE IF EXISTS loan_warehouse.payments;
DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
DROP TABLE IF EXISTS loan_warehouse.loan_products;
DROP TABLE IF EXISTS loan_warehouse.borrowers;
-- Then re-run the DDL scripts
```

> **Important:** Drop tables in reverse dependency order (payments first, borrowers last).

---

## Pre-Flight Checklist

Before executing the migration:

- [ ] Verify Databricks cluster has sufficient resources (recommend at least 4 cores for parallel ingestion)
- [ ] Verify source data files are mounted at `/mnt/legacy-data/` (or update `LEGACY_SOURCE_PATH` in each ingestion script)
- [ ] Verify `loan_warehouse` database exists (`CREATE DATABASE IF NOT EXISTS loan_warehouse`)
- [ ] Review quarantine table contents after migration to address any bad records
- [ ] Review `DATA_QUALITY_REPORT.md` output for any FAIL results
- [ ] Confirm downstream consumers can handle the new column types and expanded status values

---

*Last updated: Generated by the Legacy CDW Migration Pipeline.*
