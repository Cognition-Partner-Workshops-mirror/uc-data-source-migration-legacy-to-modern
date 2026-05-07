# Databricks Migration Runbook

## Legacy CDW → Delta Lake (loan_warehouse)

**Last Updated:** 2026-05-07

---

## Table of Contents

1. [Overview](#1-overview)
2. [Source System Description](#2-source-system-description)
3. [Target Schema Design](#3-target-schema-design)
4. [Column Mapping Reference](#4-column-mapping-reference)
5. [Transformation Decisions](#5-transformation-decisions)
6. [Partitioning Strategy](#6-partitioning-strategy)
7. [Execution Order](#7-execution-order)
8. [Pre-Migration Checklist](#8-pre-migration-checklist)
9. [Running the Migration](#9-running-the-migration)
10. [Post-Migration Validation](#10-post-migration-validation)
11. [Rollback Procedure](#11-rollback-procedure)
12. [Known Issues and Edge Cases](#12-known-issues-and-edge-cases)

---

## 1. Overview

This runbook documents the migration of legacy Corporate Data Warehouse (CDW) loan data into a modern Delta Lake schema on Databricks. The legacy system stores **all data as VARCHAR strings** with cryptic abbreviated column names, no foreign key constraints, and denormalized structures.

### Migration Scope

| Legacy Table | Target Table | Record Type |
|---|---|---|
| `CDW_BORR_MSTR` | `loan_warehouse.borrowers` | Dimension |
| `CDW_LN_PROD` | `loan_warehouse.loan_products` | Dimension |
| `CDW_LN_ACCT` | `loan_warehouse.loan_accounts` | Fact |
| `CDW_PMT_HIST` | `loan_warehouse.payments` | Fact |

### Key Transformations

- **Type coercion:** All VARCHAR → proper types (DATE, DECIMAL, INT, BOOLEAN, TIMESTAMP)
- **Date parsing:** `MM/DD/YYYY` strings → DATE/TIMESTAMP
- **Amount parsing:** Comma-formatted strings (`"285,000"`) → DECIMAL
- **Status expansion:** Abbreviation codes → full readable values
- **Normalization:** Denormalized borrower fields in `CDW_LN_ACCT` removed; replaced with FK to `borrowers`
- **FK resolution:** Legacy string IDs → auto-increment BIGINT with proper FK constraints

---

## 2. Source System Description

### Legacy CDW Characteristics

| Characteristic | Description |
|---|---|
| **Database** | H2 (simulating mainframe DB2 extract) |
| **Data Types** | All columns VARCHAR — no numeric, date, or boolean types |
| **Column Names** | Cryptic abbreviations: `BORR_FST_NM`, `LN_CURR_BAL`, `PMT_ESCROW_AMT` |
| **Date Format** | `MM/DD/YYYY` stored as strings (e.g., `"02/15/2019"`) |
| **Amount Format** | Comma-formatted strings (e.g., `"285,000"`, `"1,487.02"`) |
| **FK Constraints** | None — referential integrity not enforced |
| **Denormalization** | Borrower name/SSN duplicated in loan account records |
| **Status Codes** | 3-letter abbreviations: `ACT`, `CLO`, `DFT`, `FRB`, etc. |

### Legacy Tables

**CDW_BORR_MSTR** (20 columns) — Borrower master
- Primary Key: `BORR_ID` (e.g., `"B-10001"`)
- Dates: `BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`
- Amounts: `BORR_ANN_INCM` (comma-formatted)
- Status: `BORR_STAT_CD` (`ACT`, `INA`, `DEC`, `SUS`)

**CDW_LN_PROD** (10 columns) — Loan product reference
- Primary Key: `PROD_CD` (e.g., `"FXD30"`)
- Amounts: `PROD_MIN_AMT`, `PROD_MAX_AMT` (comma-formatted)
- Status: `PROD_STAT_CD` (`ACT`, `INA`, `EXP`)

**CDW_LN_ACCT** (27 columns) — Loan accounts (denormalized)
- Primary Key: `LN_ACCT_NBR` (e.g., `"LN-2019-00142"`)
- Contains borrower fields: `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` (dropped in migration)
- 8 amount columns, 6 date columns, 2 status columns
- Status: `LN_STAT_CD` (`ACT`, `CLO`, `DFT`, `FRB`)

**CDW_PMT_HIST** (14 columns) — Payment history
- Primary Key: `PMT_SEQ_NBR` (e.g., `"PMT-2025120001"`)
- 5 amount columns, 4 date columns, 2 status columns
- Status: `PMT_TYP_CD` (`REG`, `EXT`, `PRT`, `PRE`), `PMT_STAT_CD` (`PST`, `REV`, `NSF`, `PND`)

---

## 3. Target Schema Design

### Entity Relationship

```
borrowers (1) ──────< (N) loan_accounts (1) ──────< (N) payments
                              |
                              └──> (N:1) loan_products
```

### Design Principles

1. **Proper typing:** Every column uses the correct Spark SQL type (DATE, DECIMAL, INT, etc.)
2. **Meaningful names:** Cryptic abbreviations replaced with readable names per `column_mappings.md`
3. **Normalization:** Borrower data lives only in `borrowers` table; `loan_accounts` holds FK reference
4. **Referential integrity:** FK constraints defined (enforced by Delta Lake in Unity Catalog)
5. **Constraints:** CHECK constraints for valid status values, credit score range (300–850), positive amounts
6. **Audit fields:** `created_at` and `updated_at` TIMESTAMP on all tables

---

## 4. Column Mapping Reference

### CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| `BORR_ID` | `external_id` | VARCHAR→STRING | Direct copy |
| `BORR_FST_NM` | `first_name` | VARCHAR→STRING | Trim |
| `BORR_LST_NM` | `last_name` | VARCHAR→STRING | Trim |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR→STRING | Trim |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR→STRING | Direct copy |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR→DATE | Parse MM/DD/YYYY |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR→STRING | Trim |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR→STRING | Trim |
| `BORR_CTY_NM` | `city` | VARCHAR→STRING | Trim |
| `BORR_ST_CD` | `state` | VARCHAR→STRING | Trim |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR→STRING | Trim |
| `BORR_PH_NBR` | `phone` | VARCHAR→STRING | Trim |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR→STRING | Trim |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR→INT | Parse integer, validate 300–850 range |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR→STRING | Trim |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR→DECIMAL(12,2) | Strip commas, parse |
| `BORR_STAT_CD` | `status` | VARCHAR→STRING | Expand: ACT→ACTIVE, INA→INACTIVE, DEC→DECEASED, SUS→SUSPENDED |
| `BORR_CRET_DT` | `created_at` | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY → midnight timestamp |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY → midnight timestamp |
| `BORR_REC_TYP` | *(dropped)* | — | Not needed in modern schema |

### CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| `PROD_CD` | `code` | VARCHAR→STRING | Trim |
| `PROD_DESC_TXT` | `name` | VARCHAR→STRING | Trim |
| `PROD_TYP_CD` | `type` | VARCHAR→STRING | Trim |
| `PROD_TERM_MOS` | `term_months` | VARCHAR→INT | Parse integer |
| `PROD_RT_TYP` | `rate_type` | VARCHAR→STRING | Trim |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR→DECIMAL(12,2) | Strip commas, parse |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR→DECIMAL(12,2) | Strip commas, parse |
| `PROD_STAT_CD` | `is_active` | VARCHAR→BOOLEAN | ACT→true, else→false |
| `PROD_EFF_DT` | `effective_date` | VARCHAR→DATE | Parse MM/DD/YYYY |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR→DATE | Parse MM/DD/YYYY |

### CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| `LN_ACCT_NBR` | `account_number` | VARCHAR→STRING | Direct copy |
| `BORR_ID` | `borrower_id` | VARCHAR→BIGINT | FK lookup: borrowers.id WHERE external_id = BORR_ID |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_id` | VARCHAR→BIGINT | FK lookup: loan_products.id WHERE code = PROD_CD |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR→DECIMAL(12,2) | Strip commas, parse |
| `LN_CURR_BAL` | `current_balance` | VARCHAR→DECIMAL(12,2) | Strip commas, parse |
| `LN_INT_RT` | `interest_rate` | VARCHAR→DECIMAL(5,3) | Parse decimal |
| `LN_TERM_MOS` | `term_months` | VARCHAR→INT | Parse integer |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR→DECIMAL(10,2) | Strip commas, parse |
| `LN_ORIG_DT` | `origination_date` | VARCHAR→DATE | Parse MM/DD/YYYY |
| `LN_MAT_DT` | `maturity_date` | VARCHAR→DATE | Parse MM/DD/YYYY |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR→DATE | Parse MM/DD/YYYY |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR→DATE | Parse MM/DD/YYYY |
| `LN_STAT_CD` | `status` | VARCHAR→STRING | Expand: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR→INT | Parse integer |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR→DECIMAL(10,2) | Strip commas, parse |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR→DECIMAL(5,2) | Parse decimal |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR→STRING | Trim |
| `PROP_CTY_NM` | `property_city` | VARCHAR→STRING | Trim |
| `PROP_ST_CD` | `property_state` | VARCHAR→STRING | Trim |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR→STRING | Trim |
| `PROP_TYP_CD` | `property_type` | VARCHAR→STRING | Expand: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR→DECIMAL(12,2) | Strip commas, parse |
| `LN_CRET_DT` | `created_at` | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY → midnight timestamp |
| `LN_UPDT_DT` | `updated_at` | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY → midnight timestamp |

### CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| `PMT_SEQ_NBR` | `legacy_payment_id` | VARCHAR→STRING | Preserved for traceability |
| `LN_ACCT_NBR` | `loan_account_id` | VARCHAR→BIGINT | FK lookup: loan_accounts.id WHERE account_number = LN_ACCT_NBR |
| `PMT_DT` | `payment_date` | VARCHAR→DATE | Parse MM/DD/YYYY |
| `PMT_AMT` | `total_amount` | VARCHAR→DECIMAL(10,2) | Strip commas, parse |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR→DECIMAL(10,2) | Strip commas, parse |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR→DECIMAL(10,2) | Strip commas, parse |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR→DECIMAL(10,2) | Strip commas, parse |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR→DECIMAL(10,2) | Strip commas, parse |
| `PMT_TYP_CD` | `type` | VARCHAR→STRING | Expand: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| `PMT_STAT_CD` | `status` | VARCHAR→STRING | Expand: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| `PMT_RECV_DT` | `received_date` | VARCHAR→DATE | Parse MM/DD/YYYY |
| `PMT_PROC_DT` | `processed_date` | VARCHAR→DATE | Parse MM/DD/YYYY |
| `PMT_CRET_DT` | `created_at` | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY → midnight timestamp |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY → midnight timestamp |

---

## 5. Transformation Decisions

### 5.1 Date Handling

**Decision:** Parse `MM/DD/YYYY` strings to `DATE` type; for audit fields (`created_at`, `updated_at`) parse to `TIMESTAMP` at midnight UTC.

**Rationale:** The legacy system stores all dates as strings in `MM/DD/YYYY` format. String-based date storage causes:
- Incorrect lexicographic sorting (`"9/01/2025"` sorts after `"12/01/2025"`)
- No date arithmetic support
- Format ambiguity

**Implementation:** Multi-format parser tries `MM/dd/yyyy`, `M/d/yyyy`, `yyyy-MM-dd` in sequence. Falls back to null if all formats fail — rows with unparseable dates are quarantined rather than silently dropped.

### 5.2 Amount Parsing

**Decision:** Strip commas and dollar signs, parse to `DECIMAL(12,2)` for amounts and `DECIMAL(5,3)` for rates.

**Rationale:** Legacy amounts include formatting characters (e.g., `"285,000"`, `"1,487.02"`). Direct numeric casting would fail. The regex `[$,]` removal handles `$285,000` and `285,000` uniformly.

**Precision choices:**
- `DECIMAL(12,2)` for loan amounts — supports up to $9,999,999,999.99 (sufficient for residential mortgages)
- `DECIMAL(10,2)` for payment amounts — supports up to $99,999,999.99
- `DECIMAL(5,3)` for interest rates — supports up to 99.999%
- `DECIMAL(5,2)` for LTV percentage — supports up to 999.99%

### 5.3 Status Code Expansion

**Decision:** Expand 3-letter abbreviation codes to full readable values.

**Mappings:**
| Domain | Code | Expanded |
|---|---|---|
| Loan Status | ACT | ACTIVE |
| Loan Status | CLO | CLOSED |
| Loan Status | DFT | DEFAULT |
| Loan Status | FRB | FORBEARANCE |
| Borrower Status | ACT | ACTIVE |
| Borrower Status | INA | INACTIVE |
| Borrower Status | DEC | DECEASED |
| Borrower Status | SUS | SUSPENDED |
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
| Product Status | INA/EXP | false (boolean) |

**Unmapped codes** are preserved as-is and flagged by the data quality framework. This prevents data loss while still surfacing issues.

### 5.4 Normalization

**Decision:** Remove denormalized borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) from `loan_accounts`, replace with `borrower_id` FK.

**Rationale:** The legacy `CDW_LN_ACCT` table embeds borrower name and partial SSN alongside the `BORR_ID` reference. This creates data drift risk (borrower name updated in `CDW_BORR_MSTR` but not in `CDW_LN_ACCT`). The modern schema enforces a single source of truth via FK.

### 5.5 FK Resolution

**Decision:** Replace legacy string IDs with auto-increment BIGINT IDs via lookup joins.

**Process:**
1. Ingest dimension tables first (borrowers, loan_products)
2. Build lookup DataFrames: `(modern_id, legacy_code)`
3. Left-join fact tables to resolve FKs
4. Route unresolved (orphaned) rows to quarantine tables

### 5.6 Credit Score Validation

**Decision:** Null out credit scores outside the FICO range (300–850).

**Rationale:** The legacy system stores credit scores as unconstrained VARCHAR strings. Values like `0`, `999`, or `N/A` would parse to invalid integers. Out-of-range scores are set to null rather than being silently loaded — downstream analytics should treat null as "score unavailable."

### 5.7 Quarantine Strategy

**Decision:** Rows that fail validation are written to `_quarantine_*` tables rather than being dropped.

**Rationale:** Silent data loss is unacceptable in financial data migration. Quarantined rows preserve:
- The original legacy data
- A `_quality_issues` array column listing specific problems
- A `_has_quality_issues` boolean flag

This allows operations teams to review, fix, and re-ingest quarantined records.

---

## 6. Partitioning Strategy

| Table | Partition Column | Rationale |
|---|---|---|
| `borrowers` | `status` | Most queries filter by active/inactive; small cardinality (4 values) |
| `loan_products` | *(none)* | Small reference table (~tens of rows); no benefit from partitioning |
| `loan_accounts` | `status` | Primary query pattern is active loans; 4 distinct statuses |
| `payments` | `payment_year_month` | Time-series data; queries typically bounded by date range; generated column `yyyy-MM` format |

### Rationale Details

**`borrowers` by `status`:** Customer-facing and operational queries almost always filter by active borrowers. Partitioning by status creates ~4 partitions, each with roughly balanced row counts in a healthy portfolio.

**`loan_accounts` by `status`:** Loan servicing queries focus on active/delinquent loans. The 4-partition structure (ACTIVE, CLOSED, DEFAULT, FORBEARANCE) allows efficient partition pruning. Status changes are infrequent enough that partition rebalancing is minimal.

**`payments` by `payment_year_month`:** Payment data is time-series and append-heavy. Month-level partitioning gives ~12 partitions per year, well-suited for monthly reporting queries and regulatory audits that span date ranges. The `payment_year_month` column is generated automatically from `payment_date`.

---

## 7. Execution Order

The ingestion notebooks must be run in dependency order. Dimension tables load first, then fact tables that reference them.

```
Step 1: Create database and tables (DDL)
  └── 01_borrowers.sql
  └── 02_loan_products.sql
  └── 03_loan_accounts.sql
  └── 04_payments.sql

Step 2: Ingest dimension tables (no FK dependencies)
  └── 01_ingest_borrowers.py    ← no dependencies
  └── 02_ingest_loan_products.py ← no dependencies
  (these two can run in parallel)

Step 3: Ingest loan accounts (depends on borrowers + loan_products)
  └── 03_ingest_loan_accounts.py ← requires borrowers.id and loan_products.id

Step 4: Ingest payments (depends on loan_accounts)
  └── 04_ingest_payments.py ← requires loan_accounts.id

Step 5: Data quality validation
  └── data_quality_checks.py ← reads all 4 target tables
```

### Databricks Workflow Configuration

```json
{
  "name": "CDW_Legacy_Migration",
  "tasks": [
    {
      "task_key": "create_schema",
      "notebook_task": { "notebook_path": "databricks/ddl/run_all_ddl" }
    },
    {
      "task_key": "ingest_borrowers",
      "depends_on": [{ "task_key": "create_schema" }],
      "notebook_task": { "notebook_path": "databricks/ingestion/01_ingest_borrowers" }
    },
    {
      "task_key": "ingest_loan_products",
      "depends_on": [{ "task_key": "create_schema" }],
      "notebook_task": { "notebook_path": "databricks/ingestion/02_ingest_loan_products" }
    },
    {
      "task_key": "ingest_loan_accounts",
      "depends_on": [
        { "task_key": "ingest_borrowers" },
        { "task_key": "ingest_loan_products" }
      ],
      "notebook_task": { "notebook_path": "databricks/ingestion/03_ingest_loan_accounts" }
    },
    {
      "task_key": "ingest_payments",
      "depends_on": [{ "task_key": "ingest_loan_accounts" }],
      "notebook_task": { "notebook_path": "databricks/ingestion/04_ingest_payments" }
    },
    {
      "task_key": "quality_checks",
      "depends_on": [{ "task_key": "ingest_payments" }],
      "notebook_task": { "notebook_path": "databricks/quality/data_quality_checks" }
    }
  ]
}
```

---

## 8. Pre-Migration Checklist

- [ ] **Source files extracted** from legacy CDW and placed in `dbfs:/mnt/legacy-cdw/` (one folder per table)
- [ ] **Databricks workspace** configured with Unity Catalog
- [ ] **Database created:** `CREATE DATABASE IF NOT EXISTS loan_warehouse`
- [ ] **Storage location** configured for the `loan_warehouse` database
- [ ] **Cluster configuration:** At least Standard_DS3_v2 (or equivalent) with Spark 3.4+
- [ ] **Source file format verified:** CSV with headers (or Parquet) — update `SOURCE_FORMAT` in each notebook if needed
- [ ] **Permissions:** Service principal has `CREATE TABLE`, `INSERT`, `SELECT` on `loan_warehouse`
- [ ] **Reports directory:** `dbfs:/mnt/reports/` exists and is writable
- [ ] **Dry run completed** on a subset of data in a dev/staging environment

---

## 9. Running the Migration

### Option A: Databricks Workflow (Recommended)

1. Import the workflow JSON from Section 7 into Databricks Workflows
2. Configure the cluster policy
3. Click **Run Now**
4. Monitor progress in the Workflows UI — each task shows PASS/FAIL with logs

### Option B: Manual Notebook Execution

Run notebooks in order from the Databricks workspace:

```
1. Execute DDL scripts (create tables)
2. Run 01_ingest_borrowers.py
3. Run 02_ingest_loan_products.py (can run parallel with step 2)
4. Run 03_ingest_loan_accounts.py (wait for steps 2+3)
5. Run 04_ingest_payments.py (wait for step 4)
6. Run data_quality_checks.py (wait for step 5)
```

### Monitoring

Each ingestion notebook prints reconciliation logs:
```
[INGEST] Read 5 rows from dbfs:/mnt/legacy-cdw/CDW_BORR_MSTR/
[QUARANTINE] No rows quarantined
[TRANSFORM] 5 rows after transformation
[WRITE] Wrote 5 rows to loan_warehouse.borrowers
[RECONCILE] Source: 5, Quarantined: 0, Target: 5
```

If `Source != Quarantined + Target`, investigate lost rows immediately.

---

## 10. Post-Migration Validation

### Automated Checks (data_quality_checks.py)

The quality framework runs 30+ checks across 6 categories:

| Category | Checks |
|---|---|
| **Row Count** | Source vs target reconciliation for all 4 tables |
| **Null Checks** | Required fields have no nulls (13 field checks) |
| **Referential Integrity** | loan_accounts→borrowers, loan_accounts→loan_products, payments→loan_accounts |
| **Business Rules** | Active loans have positive balance, origination < maturity, delinquency consistency |
| **Value Range** | Credit score 300–850, interest rate 0–30%, valid status codes |
| **Uniqueness** | External IDs, account numbers, product codes are unique |

### Manual Spot Checks

After automated checks pass, verify a sample of records end-to-end:

```sql
-- Compare a specific borrower across source and target
SELECT * FROM loan_warehouse.borrowers WHERE external_id = 'B-10001';

-- Verify loan amount transformation
SELECT account_number, original_amount, current_balance, interest_rate
FROM loan_warehouse.loan_accounts
WHERE account_number = 'LN-2019-00142';
-- Expected: original_amount=285000.00, current_balance=271432.56, interest_rate=4.750

-- Verify FK integrity
SELECT la.account_number, b.first_name, b.last_name, lp.name
FROM loan_warehouse.loan_accounts la
JOIN loan_warehouse.borrowers b ON la.borrower_id = b.id
JOIN loan_warehouse.loan_products lp ON la.product_id = lp.id;

-- Verify payment date ordering (should be true DATE sort, not string sort)
SELECT legacy_payment_id, payment_date, total_amount
FROM loan_warehouse.payments
WHERE loan_account_id = (
    SELECT id FROM loan_warehouse.loan_accounts WHERE account_number = 'LN-2019-00142'
)
ORDER BY payment_date DESC;
```

### Review Quarantine Tables

```sql
-- Check if any rows were quarantined
SELECT '_quarantine_borrowers' AS tbl, count(*) FROM loan_warehouse._quarantine_borrowers
UNION ALL
SELECT '_quarantine_loan_products', count(*) FROM loan_warehouse._quarantine_loan_products
UNION ALL
SELECT '_quarantine_loan_accounts', count(*) FROM loan_warehouse._quarantine_loan_accounts
UNION ALL
SELECT '_quarantine_payments', count(*) FROM loan_warehouse._quarantine_payments;
```

---

## 11. Rollback Procedure

Delta Lake supports time travel, making rollback straightforward:

```sql
-- View table history
DESCRIBE HISTORY loan_warehouse.borrowers;

-- Restore to pre-migration state (version 0 = before any writes)
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.loan_products TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.payments TO VERSION AS OF 0;
```

For a full reset:

```sql
DROP TABLE IF EXISTS loan_warehouse.payments;
DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
DROP TABLE IF EXISTS loan_warehouse.loan_products;
DROP TABLE IF EXISTS loan_warehouse.borrowers;

-- Also drop quarantine tables
DROP TABLE IF EXISTS loan_warehouse._quarantine_borrowers;
DROP TABLE IF EXISTS loan_warehouse._quarantine_loan_products;
DROP TABLE IF EXISTS loan_warehouse._quarantine_loan_accounts;
DROP TABLE IF EXISTS loan_warehouse._quarantine_payments;
```

---

## 12. Known Issues and Edge Cases

### 12.1 Payment Component Imbalance

Some legacy payments have `principal + interest + escrow + late_fee ≠ total_amount`. Example:

| PMT_SEQ_NBR | Total | Principal | Interest | Escrow | Late Fee | Sum |
|---|---|---|---|---|---|---|
| PMT-2025120001 | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 |

**Decision:** Load as-is and flag via data quality checks. The imbalance is in the source data and should be investigated with the business team. The quality framework logs this but does not block ingestion.

### 12.2 Delinquency vs Status Inconsistency

Loan `LN-2018-00089` has `LN_STAT_CD = 'ACT'` but `LN_DLQ_DAYS = '15'`. Active loans should have 0 delinquency days. The quality framework flags this with a business rule check.

### 12.3 Credit Scores Outside FICO Range

If a legacy borrower has a credit score of `0`, `999`, or a non-numeric value like `N/A`, it will be set to null in the target. The original value is visible in the quarantine table if the row had other issues, or in Delta Lake time travel on the raw staging layer.

### 12.4 Denormalized Borrower Data Drift

The legacy system stores borrower name in both `CDW_BORR_MSTR` and `CDW_LN_ACCT`. These may differ if a borrower's name changed after loan origination. The migration trusts `CDW_BORR_MSTR` as the authoritative source and drops the denormalized copies from `CDW_LN_ACCT`.

### 12.5 Single-Digit Month Dates

Some legacy date fields may use `M/D/YYYY` format (e.g., `"2/5/2019"` instead of `"02/05/2019"`). The date parser handles both zero-padded and non-zero-padded formats via fallback parsing (`MM/dd/yyyy` then `M/d/yyyy`).
