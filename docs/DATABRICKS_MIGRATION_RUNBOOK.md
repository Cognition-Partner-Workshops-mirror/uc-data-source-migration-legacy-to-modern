# Databricks Migration Runbook

## Legacy CDW → Delta Lake Migration Pipeline

**Document Version:** 1.0
**Last Updated:** 2026-05-26
**Source System:** Legacy Corporate Data Warehouse (CDW) — H2/SQL-based loan management tables
**Target System:** Databricks Delta Lake (`loan_warehouse` database)

---

## Table of Contents

1. [Migration Overview](#1-migration-overview)
2. [Source Schema Analysis](#2-source-schema-analysis)
3. [Target Schema Design](#3-target-schema-design)
4. [Column Mapping Reference](#4-column-mapping-reference)
5. [Transformation Decisions](#5-transformation-decisions)
6. [Type Conversion Details](#6-type-conversion-details)
7. [Partitioning Strategy](#7-partitioning-strategy)
8. [Execution Order](#8-execution-order)
9. [Pre-Migration Checklist](#9-pre-migration-checklist)
10. [Running the Pipeline](#10-running-the-pipeline)
11. [Post-Migration Validation](#11-post-migration-validation)
12. [Troubleshooting](#12-troubleshooting)
13. [Rollback Procedure](#13-rollback-procedure)

---

## 1. Migration Overview

### Problem Statement

The legacy loan management application reads from a Corporate Data Warehouse (CDW) with significant technical debt:

- **All-VARCHAR columns**: Every field is stored as VARCHAR, including dates, amounts, and numeric codes
- **Cryptic column names**: Abbreviated names like `BORR_FST_NM`, `LN_CURR_BAL`, `PMT_ESCROW_AMT`
- **No foreign keys**: No referential integrity constraints between related tables
- **Status code abbreviations**: Cryptic codes like `ACT`, `CLO`, `DFT`, `FRB` instead of readable values
- **Denormalized structure**: Borrower data duplicated inside the loan accounts table
- **String-encoded dates**: Dates stored as MM/DD/YYYY strings instead of DATE types
- **Comma-formatted amounts**: Monetary values stored as strings with commas ("285,000")

### Migration Goal

Migrate all legacy CDW data into a properly modeled Delta Lake warehouse on Databricks with:

- Proper Spark SQL types (DATE, DECIMAL, INT, BOOLEAN, TIMESTAMP)
- Meaningful, human-readable column names
- Normalized table structure with FK relationships
- Expanded status codes for readability
- Partitioning for query performance
- Full data quality validation

### Scope

| Legacy Table | Record Count | Target Table | Status |
|-------------|-------------|-------------|--------|
| CDW_BORR_MSTR | 5 borrowers | loan_warehouse.borrowers | In scope |
| CDW_LN_PROD | 5 products | loan_warehouse.loan_products | In scope |
| CDW_LN_ACCT | 5 accounts | loan_warehouse.loan_accounts | In scope |
| CDW_PMT_HIST | 10 payments | loan_warehouse.payments | In scope |

---

## 2. Source Schema Analysis

### CDW_BORR_MSTR (Borrower Master)

| Column | Type | Description | Issues |
|--------|------|-------------|--------|
| BORR_ID | VARCHAR(20) | Borrower identifier | PK, but no FK references from other tables |
| BORR_FST_NM | VARCHAR(50) | First name | |
| BORR_LST_NM | VARCHAR(50) | Last name | |
| BORR_MID_INIT | VARCHAR(1) | Middle initial | Nullable |
| BORR_SSN_ENCR | VARCHAR(100) | Encrypted SSN | Encryption method unknown |
| BORR_DOB_DT | VARCHAR(10) | Date of birth | Stored as MM/DD/YYYY string |
| BORR_ADDR_LN1 | VARCHAR(100) | Address line 1 | |
| BORR_ADDR_LN2 | VARCHAR(100) | Address line 2 | Often NULL |
| BORR_CTY_NM | VARCHAR(50) | City | |
| BORR_ST_CD | VARCHAR(2) | State code | |
| BORR_ZIP_CD | VARCHAR(10) | ZIP code | |
| BORR_PH_NBR | VARCHAR(15) | Phone number | |
| BORR_EMAIL_ADDR | VARCHAR(100) | Email | |
| BORR_CRDT_SCR | VARCHAR(5) | Credit score | Numeric stored as string |
| BORR_EMP_STAT | VARCHAR(20) | Employment status | Free text (EMPLOYED, SELF-EMP, RETIRED) |
| BORR_ANN_INCM | VARCHAR(15) | Annual income | Comma-formatted string |
| BORR_CRET_DT | VARCHAR(10) | Created date | MM/DD/YYYY string |
| BORR_UPDT_DT | VARCHAR(10) | Updated date | MM/DD/YYYY string |
| BORR_STAT_CD | VARCHAR(5) | Status code | ACT, INA |
| BORR_REC_TYP | VARCHAR(10) | Record type | Dropped in migration (not needed) |

### CDW_LN_PROD (Loan Products)

| Column | Type | Description | Issues |
|--------|------|-------------|--------|
| PROD_CD | VARCHAR(10) | Product code | PK (e.g., FXD30, ARM51) |
| PROD_DESC_TXT | VARCHAR(200) | Description | |
| PROD_TYP_CD | VARCHAR(5) | Type code | FXD, ARM, FHA, VA |
| PROD_TERM_MOS | VARCHAR(5) | Term in months | Numeric as string |
| PROD_RT_TYP | VARCHAR(10) | Rate type | FIXED, VARIABLE |
| PROD_MIN_AMT | VARCHAR(15) | Min amount | Comma-formatted string |
| PROD_MAX_AMT | VARCHAR(15) | Max amount | Comma-formatted string |
| PROD_STAT_CD | VARCHAR(5) | Status code | ACT, INA → boolean |
| PROD_EFF_DT | VARCHAR(10) | Effective date | MM/DD/YYYY string |
| PROD_EXP_DT | VARCHAR(10) | Expiration date | MM/DD/YYYY string |

### CDW_LN_ACCT (Loan Accounts — Denormalized)

| Column | Type | Description | Issues |
|--------|------|-------------|--------|
| LN_ACCT_NBR | VARCHAR(20) | Account number | PK |
| BORR_ID | VARCHAR(20) | Borrower ID | No FK constraint |
| BORR_FST_NM | VARCHAR(50) | Borrower first name | **Denormalized** — dropped |
| BORR_LST_NM | VARCHAR(50) | Borrower last name | **Denormalized** — dropped |
| BORR_SSN_LST4 | VARCHAR(4) | Last 4 of SSN | **Denormalized** — dropped |
| PROD_CD | VARCHAR(10) | Product code | No FK constraint |
| LN_ORIG_AMT | VARCHAR(15) | Original amount | Comma-formatted string |
| LN_CURR_BAL | VARCHAR(15) | Current balance | Comma-formatted string |
| LN_INT_RT | VARCHAR(8) | Interest rate | e.g., "5.250" |
| LN_TERM_MOS | VARCHAR(5) | Term months | Numeric as string |
| LN_PMT_AMT | VARCHAR(15) | Monthly payment | Comma-formatted string |
| LN_ORIG_DT | VARCHAR(10) | Origination date | MM/DD/YYYY |
| LN_MAT_DT | VARCHAR(10) | Maturity date | MM/DD/YYYY |
| LN_1ST_PMT_DT | VARCHAR(10) | First payment date | MM/DD/YYYY |
| LN_NXT_PMT_DT | VARCHAR(10) | Next payment date | MM/DD/YYYY |
| LN_STAT_CD | VARCHAR(5) | Loan status | ACT, CLO, DFT, FRB |
| LN_DLQ_DAYS | VARCHAR(5) | Delinquency days | Numeric as string |
| LN_ESCROW_BAL | VARCHAR(15) | Escrow balance | Comma-formatted string |
| LN_LTV_PCT | VARCHAR(8) | LTV percentage | e.g., "82.5" |
| PROP_ADDR_LN1 | VARCHAR(100) | Property address | |
| PROP_CTY_NM | VARCHAR(50) | Property city | |
| PROP_ST_CD | VARCHAR(2) | Property state | |
| PROP_ZIP_CD | VARCHAR(10) | Property ZIP | |
| PROP_TYP_CD | VARCHAR(10) | Property type | SFR, CND, MFR, TWN |
| PROP_APRS_VAL | VARCHAR(15) | Appraised value | Comma-formatted string |
| LN_CRET_DT | VARCHAR(10) | Created date | MM/DD/YYYY |
| LN_UPDT_DT | VARCHAR(10) | Updated date | MM/DD/YYYY |

### CDW_PMT_HIST (Payment History)

| Column | Type | Description | Issues |
|--------|------|-------------|--------|
| PMT_SEQ_NBR | VARCHAR(20) | Payment sequence | PK |
| LN_ACCT_NBR | VARCHAR(20) | Loan account | No FK constraint |
| PMT_DT | VARCHAR(10) | Payment date | MM/DD/YYYY |
| PMT_AMT | VARCHAR(15) | Total amount | Comma-formatted |
| PMT_PRIN_AMT | VARCHAR(15) | Principal portion | Comma-formatted |
| PMT_INT_AMT | VARCHAR(15) | Interest portion | Comma-formatted |
| PMT_ESCROW_AMT | VARCHAR(15) | Escrow portion | Comma-formatted |
| PMT_LATE_FEE | VARCHAR(15) | Late fee | Comma-formatted |
| PMT_TYP_CD | VARCHAR(5) | Payment type | REG, EXT, PRT, PRE |
| PMT_STAT_CD | VARCHAR(5) | Payment status | PST, REV, NSF, PND |
| PMT_RECV_DT | VARCHAR(10) | Received date | MM/DD/YYYY |
| PMT_PROC_DT | VARCHAR(10) | Processed date | MM/DD/YYYY |
| PMT_CRET_DT | VARCHAR(10) | Created date | MM/DD/YYYY |
| PMT_UPDT_DT | VARCHAR(10) | Updated date | MM/DD/YYYY |

---

## 3. Target Schema Design

### Design Principles

1. **Proper typing**: DATE for dates, DECIMAL for monetary amounts, INT for counts, BOOLEAN for flags
2. **Meaningful names**: `first_name` instead of `BORR_FST_NM`, `current_balance` instead of `LN_CURR_BAL`
3. **Normalized structure**: Borrower fields removed from loan_accounts; use FK to borrowers table
4. **Referential integrity**: FK relationships enforced logically (validated by quality checks)
5. **ETL metadata**: Every table includes `_ingestion_ts` and `_source_system` columns
6. **Surrogate keys**: Auto-generated BIGINT IDs for each table; legacy natural keys preserved

### Target Tables

```
loan_warehouse
├── borrowers          (dimension — borrower demographics & financial profile)
├── loan_products      (dimension — mortgage product definitions)
├── loan_accounts      (fact — loan accounts, partitioned by status)
└── payments           (fact — payment history, partitioned by payment_year)
```

### Entity Relationship

```
borrowers (1) ──────< (N) loan_accounts (1) ──────< (N) payments
                              │
                              └── (N) >────── (1) loan_products
```

---

## 4. Column Mapping Reference

The full column mapping is documented in `data/mappings/column_mappings.md`. Below is a summary of non-trivial mappings:

### Dropped Columns (Denormalization Removal)

| Legacy Table | Dropped Column | Reason |
|-------------|----------------|--------|
| CDW_LN_ACCT | BORR_FST_NM | Denormalized — use borrower_id FK |
| CDW_LN_ACCT | BORR_LST_NM | Denormalized — use borrower_id FK |
| CDW_LN_ACCT | BORR_SSN_LST4 | Denormalized — use borrower_id FK |
| CDW_BORR_MSTR | BORR_REC_TYP | Not needed in modern schema |

### Renamed Columns (Key Examples)

| Legacy | Modern | Rationale |
|--------|--------|-----------|
| BORR_FST_NM | first_name | Human-readable |
| BORR_LST_NM | last_name | Human-readable |
| LN_CURR_BAL | current_balance | Self-documenting |
| PMT_ESCROW_AMT | escrow_amount | Clear and consistent |
| BORR_CRDT_SCR | credit_score | Remove abbreviation |
| LN_LTV_PCT | ltv_percent | Explicit unit |

### Added Columns

| Table | Column | Purpose |
|-------|--------|---------|
| All tables | `_ingestion_ts` | ETL audit: when record was ingested |
| All tables | `_source_system` | ETL audit: which legacy table it came from |
| payments | `legacy_payment_id` | Preserves PMT_SEQ_NBR for traceability |
| payments | `payment_year` | Partition column derived from payment_date |

---

## 5. Transformation Decisions

### Decision 1: Status Code Expansion

**Choice:** Expand all status abbreviations to full readable values.

**Rationale:** Abbreviated codes (ACT, CLO, DFT, FRB) are legacy artifacts that harm readability and require a lookup table to interpret. Full values (ACTIVE, CLOSED, DEFAULT, FORBEARANCE) are self-documenting and eliminate the need for code-to-description joins.

**Mappings:**

| Context | Code | Expanded Value |
|---------|------|---------------|
| Borrower status | ACT | ACTIVE |
| Borrower status | INA | INACTIVE |
| Loan status | ACT | ACTIVE |
| Loan status | CLO | CLOSED |
| Loan status | DFT | DEFAULT |
| Loan status | FRB | FORBEARANCE |
| Product status | ACT | true (BOOLEAN) |
| Product status | INA | false (BOOLEAN) |
| Payment type | REG | REGULAR |
| Payment type | EXT | EXTRA |
| Payment type | PRT | PARTIAL |
| Payment type | PRE | PREPAYMENT |
| Payment status | PST | POSTED |
| Payment status | REV | REVERSED |
| Payment status | NSF | NSF |
| Payment status | PND | PENDING |
| Property type | SFR | Single Family |
| Property type | CND | Condominium |
| Property type | MFR | Multi-Family |
| Property type | TWN | Townhouse |

**Unknown codes:** Preserved with `UNKNOWN:` prefix (e.g., `UNKNOWN:XYZ`) rather than dropped, enabling downstream investigation.

### Decision 2: Denormalization Removal

**Choice:** Drop `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` from loan_accounts; use `borrower_id` FK instead.

**Rationale:** The legacy schema duplicates borrower data in every loan record. This causes data consistency issues (name changes only reflected in borrower master, not in loan accounts). The modern schema uses a normalized FK reference.

### Decision 3: FK Resolution Strategy

**Choice:** Use left joins against already-populated dimension tables to resolve string IDs to surrogate keys.

**Rationale:** Legacy tables use string identifiers (BORR_ID = "B-10001", PROD_CD = "FXD30") with no FK constraints. The ingestion pipeline resolves these to BIGINT surrogate keys via lookup joins. Unresolvable FKs are logged as warnings but not dropped.

### Decision 4: Null/Malformed Value Handling

**Choice:** Tag bad records with quality flags; never silently drop records.

**Rationale:** Data loss during migration is unacceptable for auditing. The `tag_malformed_rows` utility adds a `_quality_flags` column listing any issues (e.g., `NULL_BORR_ID`, `MALFORMED_DOB`). The data quality framework then reports on these flags.

### Decision 5: Date Interpretation

**Choice:** Parse MM/DD/YYYY strings using Spark's `to_date` with format `MM/dd/yyyy`.

**Rationale:** All legacy date fields consistently use the MM/DD/YYYY format (verified in seed data). For `created_at`/`updated_at` fields, the date is parsed as a TIMESTAMP at midnight (00:00:00) since the legacy system only stored date precision.

### Decision 6: Amount Parsing

**Choice:** Strip commas from amount strings, then cast to DECIMAL with specified precision.

**Rationale:** Legacy amounts are stored as comma-formatted strings (e.g., "285,000", "1,487.02"). The pipeline removes commas with `regexp_replace` before casting to maintain numeric precision.

---

## 6. Type Conversion Details

| Conversion Pattern | Legacy Example | Modern Type | Spark Expression |
|-------------------|----------------|-------------|-----------------|
| Date string → DATE | "03/15/1978" | DATE | `to_date(col, "MM/dd/yyyy")` |
| Date string → TIMESTAMP | "01/15/2019" | TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| Comma amount → DECIMAL | "285,000" | DECIMAL(12,2) | `regexp_replace(col, ",", "").cast(DecimalType(12,2))` |
| Rate string → DECIMAL | "5.250" | DECIMAL(5,3) | `trim(col).cast(DecimalType(5,3))` |
| Percent string → DECIMAL | "82.5" | DECIMAL(5,2) | `trim(col).cast(DecimalType(5,2))` |
| Integer string → INT | "360" | INT | `trim(col).cast(IntegerType())` |
| Status code → STRING | "ACT" | STRING | CASE WHEN expression with mapping |
| Status code → BOOLEAN | "ACT" | BOOLEAN | CASE WHEN ACT→true, INA→false |

---

## 7. Partitioning Strategy

### loan_accounts — Partitioned by `status`

**Rationale:**
- Most queries filter loans by status (e.g., "show all active loans", "find defaulted loans")
- Status has low cardinality (4 values: ACTIVE, CLOSED, DEFAULT, FORBEARANCE)
- Enables partition pruning for the most common access patterns
- Avoids excessive small files (unlike partitioning by date for a small dataset)

**Impact:** Queries like `SELECT * FROM loan_accounts WHERE status = 'ACTIVE'` only scan the ACTIVE partition.

### payments — Partitioned by `payment_year`

**Rationale:**
- Payment history queries are almost always time-bounded (e.g., "payments in 2025")
- Year-level granularity provides good partition sizes without excessive fragmentation
- Supports efficient time-range scans for financial reporting
- Month-level partitioning would create too many small partitions for the current data volume

**Impact:** Queries like `SELECT * FROM payments WHERE payment_year = 2025` skip all other years.

### borrowers / loan_products — Not Partitioned

**Rationale:**
- Both are small dimension tables (low cardinality, infrequently updated)
- Partitioning adds overhead without query performance benefit for small tables
- Full table scans are cheap for dimension lookups

---

## 8. Execution Order

The pipeline MUST execute in this order due to FK dependencies:

```
Step 1: Create Database
  └─ databricks/ddl/create_database.sql

Step 2: Create Tables (can run in parallel)
  ├─ databricks/ddl/create_borrowers.sql
  ├─ databricks/ddl/create_loan_products.sql
  ├─ databricks/ddl/create_loan_accounts.sql
  └─ databricks/ddl/create_payments.sql

Step 3: Ingest Dimension Tables (can run in parallel)
  ├─ databricks/ingestion/ingest_borrowers.py        ← no dependencies
  └─ databricks/ingestion/ingest_loan_products.py    ← no dependencies

Step 4: Ingest Fact Tables (sequential — depends on Step 3)
  ├─ databricks/ingestion/ingest_loan_accounts.py    ← depends on borrowers + loan_products
  └─ databricks/ingestion/ingest_payments.py         ← depends on loan_accounts

Step 5: Data Quality Validation
  └─ databricks/quality/data_quality_checks.py       ← depends on all tables
```

**Alternative:** Use `databricks/ingestion/run_full_ingestion.py` to run steps 3-4 automatically in the correct order.

---

## 9. Pre-Migration Checklist

Before running the pipeline, verify:

- [ ] **Databricks workspace access**: Confirm you have write access to the target catalog/schema
- [ ] **Source data available**: Legacy CSV/Parquet files are in the expected landing zone paths
- [ ] **Mount points configured**: `dbfs:/mnt/landing/legacy/` and `dbfs:/mnt/delta/loan_warehouse` are mounted
- [ ] **Cluster configuration**: Spark cluster with Delta Lake support is running
- [ ] **Python dependencies**: PySpark is available (standard in Databricks Runtime)
- [ ] **Source data exported**: Legacy CDW tables have been exported to CSV/Parquet format:
  - `dbfs:/mnt/landing/legacy/cdw_borr_mstr/` — CDW_BORR_MSTR data
  - `dbfs:/mnt/landing/legacy/cdw_ln_prod/` — CDW_LN_PROD data
  - `dbfs:/mnt/landing/legacy/cdw_ln_acct/` — CDW_LN_ACCT data
  - `dbfs:/mnt/landing/legacy/cdw_pmt_hist/` — CDW_PMT_HIST data
- [ ] **CSV format verified**: Header row present, fields match the legacy schema column order
- [ ] **Backup**: Existing Delta tables (if any) have been backed up

---

## 10. Running the Pipeline

### Option A: Full Pipeline (Recommended)

Run the orchestrator script which handles execution order and error handling:

```python
# In a Databricks notebook:
%run ./databricks/ingestion/run_full_ingestion
```

Or via spark-submit:

```bash
spark-submit databricks/ingestion/run_full_ingestion.py
```

### Option B: Step-by-Step Execution

#### Step 1: Create Database and Tables

```sql
-- Run in Databricks SQL editor or notebook:
%sql
-- Source: databricks/ddl/create_database.sql
CREATE DATABASE IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan warehouse migrated from legacy CDW schema'
LOCATION 'dbfs:/mnt/delta/loan_warehouse';
```

Then run each DDL file:
```sql
%sql
-- Source: databricks/ddl/create_borrowers.sql
-- (paste contents)

-- Source: databricks/ddl/create_loan_products.sql
-- (paste contents)

-- Source: databricks/ddl/create_loan_accounts.sql
-- (paste contents)

-- Source: databricks/ddl/create_payments.sql
-- (paste contents)
```

#### Step 2: Run Ingestion Scripts

```python
# In separate notebook cells (or sequential spark-submit calls):

# Dimension tables first (can run in parallel):
%run ./databricks/ingestion/ingest_borrowers
%run ./databricks/ingestion/ingest_loan_products

# Fact tables after dimensions are loaded:
%run ./databricks/ingestion/ingest_loan_accounts
%run ./databricks/ingestion/ingest_payments
```

#### Step 3: Run Quality Checks

```python
%run ./databricks/quality/data_quality_checks
```

### Configuration Overrides

Each ingestion script has configuration variables at the top that can be overridden:

| Variable | Default | Description |
|----------|---------|-------------|
| `SOURCE_PATH` | `dbfs:/mnt/landing/legacy/<table>/` | Path to source CSV/Parquet files |
| `SOURCE_FORMAT` | `csv` | Source file format (`csv` or `parquet`) |
| `TARGET_TABLE` | `loan_warehouse.<table>` | Target Delta table name |
| `WRITE_MODE` | `overwrite` | Write mode (`overwrite` or `append`) |

---

## 11. Post-Migration Validation

### Automated Validation

Run `databricks/quality/data_quality_checks.py` which performs 25+ checks across 4 categories:

1. **Row Count Reconciliation** (4 checks): Source vs. target counts for all 4 tables
2. **Null Checks** (15+ checks): Required fields must not be null
3. **Referential Integrity** (3 checks): FK relationships between all tables
4. **Business Rules** (7 checks): Domain-specific validation

The script generates `DATA_QUALITY_REPORT.md` with pass/fail results.

### Manual Spot Checks

```sql
-- Verify borrower data
SELECT * FROM loan_warehouse.borrowers LIMIT 10;

-- Verify loan products
SELECT * FROM loan_warehouse.loan_products;

-- Verify loan accounts with resolved FKs
SELECT
    la.account_number,
    b.first_name || ' ' || b.last_name AS borrower_name,
    lp.name AS product_name,
    la.original_amount,
    la.current_balance,
    la.status
FROM loan_warehouse.loan_accounts la
JOIN loan_warehouse.borrowers b ON la.borrower_id = b.borrower_id
JOIN loan_warehouse.loan_products lp ON la.product_id = lp.product_id;

-- Verify payment history
SELECT
    p.legacy_payment_id,
    la.account_number,
    p.payment_date,
    p.total_amount,
    p.type,
    p.status
FROM loan_warehouse.payments p
JOIN loan_warehouse.loan_accounts la ON p.loan_account_id = la.loan_account_id
ORDER BY p.payment_date DESC;

-- Verify status code expansion
SELECT DISTINCT status FROM loan_warehouse.loan_accounts;
-- Expected: ACTIVE, CLOSED, DEFAULT, FORBEARANCE

SELECT DISTINCT type, status FROM loan_warehouse.payments;
-- Expected types: REGULAR, EXTRA, PARTIAL, PREPAYMENT
-- Expected statuses: POSTED, REVERSED, NSF, PENDING

-- Verify date parsing
SELECT account_number, origination_date, maturity_date
FROM loan_warehouse.loan_accounts
WHERE origination_date IS NULL OR maturity_date IS NULL;
-- Expected: 0 rows (all dates should parse successfully)

-- Verify amount parsing
SELECT account_number, original_amount, current_balance, monthly_payment
FROM loan_warehouse.loan_accounts
WHERE original_amount IS NULL OR current_balance IS NULL;
-- Expected: 0 rows
```

---

## 12. Troubleshooting

### Common Issues

| Issue | Symptom | Resolution |
|-------|---------|------------|
| Source files not found | `AnalysisException: Path does not exist` | Verify mount points and source file paths in configuration |
| Schema mismatch | `AnalysisException: cannot resolve column` | Verify CSV headers match the LEGACY_SCHEMA definition |
| FK resolution failures | Warning: "N loan accounts have unresolvable BORR_ID" | Ensure dimension tables (borrowers, loan_products) are loaded before fact tables |
| Date parse failures | Null values in date columns | Check source data for non-MM/DD/YYYY formats |
| Amount parse failures | Null values in amount columns | Check for unexpected characters beyond commas |
| Permission errors | `Access denied` on Delta table write | Verify Databricks workspace permissions on target schema |
| Partition errors | Schema evolution conflicts | Use `mergeSchema` option (already configured in scripts) |

### Logging

All ingestion scripts use Python's `logging` module. In Databricks notebooks, logs appear in the cell output. For spark-submit jobs, check the Spark application logs.

Key log messages to look for:
- `Read N records from legacy <TABLE>` — confirms source data was loaded
- `Found N records with quality issues` — flags but does not drop bad records
- `N loan accounts have unresolvable BORR_ID` — FK resolution warnings
- `Transformation complete. Output row count: N` — confirms transformation output
- `Successfully wrote data to <TABLE>` — confirms write success

---

## 13. Rollback Procedure

Delta Lake supports time travel, making rollback straightforward:

```sql
-- View table history to find the version before migration
DESCRIBE HISTORY loan_warehouse.borrowers;
DESCRIBE HISTORY loan_warehouse.loan_accounts;

-- Restore to a specific version (before migration)
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF <version_number>;
RESTORE TABLE loan_warehouse.loan_products TO VERSION AS OF <version_number>;
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF <version_number>;
RESTORE TABLE loan_warehouse.payments TO VERSION AS OF <version_number>;

-- Or restore to a timestamp
RESTORE TABLE loan_warehouse.borrowers TO TIMESTAMP AS OF '2026-05-25 00:00:00';
```

For a complete rollback (drop all migrated data):

```sql
DROP TABLE IF EXISTS loan_warehouse.payments;
DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
DROP TABLE IF EXISTS loan_warehouse.loan_products;
DROP TABLE IF EXISTS loan_warehouse.borrowers;
DROP DATABASE IF EXISTS loan_warehouse;
```

---

*This runbook was generated as part of the legacy CDW → Databricks migration pipeline. See `data/mappings/column_mappings.md` for the authoritative column mapping reference.*
