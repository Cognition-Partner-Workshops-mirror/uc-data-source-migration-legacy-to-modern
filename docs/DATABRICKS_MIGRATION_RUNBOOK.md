# Databricks Migration Runbook

## CDW Legacy Schema → Modern Delta Lake Loan Management

This runbook documents the complete migration pipeline from the legacy CDW (Corporate Data Warehouse) loan management tables to the modern normalized Delta Lake schema on Databricks. It covers every transformation decision, the column mapping rationale, type conversion choices, partitioning strategy, and the recommended execution order.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Source Schema Analysis](#2-source-schema-analysis)
3. [Target Schema Design](#3-target-schema-design)
4. [Column Mapping Reference](#4-column-mapping-reference)
5. [Transformation Decisions](#5-transformation-decisions)
6. [Partitioning Strategy](#6-partitioning-strategy)
7. [Execution Order](#7-execution-order)
8. [Data Quality Validation](#8-data-quality-validation)
9. [Rollback Procedure](#9-rollback-procedure)
10. [Post-Migration Verification](#10-post-migration-verification)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Overview

### Problem Statement

The legacy loan management application reads from CDW-style tables that exhibit several data quality anti-patterns:

- **All-VARCHAR columns**: Every field is stored as `VARCHAR`, even dates, amounts, and integers.
- **Cryptic column names**: Abbreviated names like `BORR_FST_NM`, `LN_CURR_BAL`, `PMT_ESCROW_AMT`.
- **No foreign keys**: Tables reference each other by string IDs with no enforced constraints.
- **Denormalized structure**: `CDW_LN_ACCT` embeds borrower fields (first name, last name, SSN last 4) redundantly.
- **Status code abbreviations**: `ACT`, `CLO`, `DFT`, `FRB` instead of readable values.
- **String-encoded dates**: Dates stored as `MM/DD/YYYY` strings.
- **Comma-formatted amounts**: Monetary values stored as `"285,000"` or `"271,432.56"` strings.

### Migration Goal

Migrate to a modern, normalized Delta Lake schema with:

- Proper Spark SQL data types (DATE, DECIMAL, INT, BOOLEAN, TIMESTAMP)
- Readable column names mapped from legacy cryptic names
- Normalized structure with FK relationships
- Expanded status/type codes for readability
- Partitioning for query performance
- Data quality validation framework

### Migration Artifacts

| Artifact | Location | Purpose |
|----------|----------|---------|
| Delta Lake DDL | `databricks/ddl/` | CREATE TABLE statements for all 4 modern tables |
| PySpark Ingestion | `databricks/ingestion/` | ETL scripts for each table + orchestrator |
| Data Quality | `databricks/quality/` | Post-ingestion validation framework |
| This Runbook | `docs/DATABRICKS_MIGRATION_RUNBOOK.md` | Complete migration documentation |

---

## 2. Source Schema Analysis

### Legacy Tables

| Table | Description | Row Count (Seed) | Key Issues |
|-------|-------------|------------------|------------|
| `CDW_BORR_MSTR` | Borrower master | 5 | All VARCHAR, dates as strings, income as comma string |
| `CDW_LN_PROD` | Loan products | 5 | Amounts as comma strings, status as abbreviation |
| `CDW_LN_ACCT` | Loan accounts | 5 | Denormalized (embeds borrower fields), all amounts/dates as strings |
| `CDW_PMT_HIST` | Payment history | 10 | Amounts as comma strings, dates as strings, type/status codes |

### Legacy Data Patterns

```
-- Date format:     '03/15/1978' (MM/DD/YYYY as VARCHAR)
-- Amount format:   '285,000' or '271,432.56' (comma-separated as VARCHAR)
-- Rate format:     '4.750' (as VARCHAR)
-- Status codes:    'ACT', 'CLO', 'DFT', 'FRB' (abbreviated)
-- Boolean values:  'ACT'/'INA' for active/inactive (as VARCHAR)
-- Integer values:  '745', '360', '0' (as VARCHAR)
```

---

## 3. Target Schema Design

### Modern Tables

| Table | Description | Primary Key | Partitioning | Notes |
|-------|-------------|-------------|--------------|-------|
| `loan_management.borrowers` | Borrower dimension | `id` (BIGINT IDENTITY) | `status` | Normalized from CDW_BORR_MSTR |
| `loan_management.loan_products` | Product catalog | `id` (BIGINT IDENTITY) | None | Small reference table |
| `loan_management.loan_accounts` | Loan fact | `id` (BIGINT IDENTITY) | `origination_year` | Normalized; dropped denormalized borrower fields |
| `loan_management.payments` | Payment fact | `id` (BIGINT IDENTITY) | `payment_year` | FK to loan_accounts |

### Key Design Decisions

1. **Surrogate keys**: All tables use `BIGINT GENERATED ALWAYS AS IDENTITY` instead of legacy string IDs. Legacy IDs are preserved as natural keys (`external_id`, `code`, `account_number`, `legacy_payment_id`) for traceability.

2. **Normalization**: Denormalized borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) in `CDW_LN_ACCT` are dropped in favor of a `borrower_id` FK to the `borrowers` table.

3. **Delta Lake properties**: All tables use `delta.autoOptimize` for automatic file compaction and `delta.columnMapping.mode = 'name'` for schema evolution flexibility.

---

## 4. Column Mapping Reference

### CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `BORR_ID` | `external_id` | VARCHAR → STRING | Direct copy |
| `BORR_FST_NM` | `first_name` | VARCHAR → STRING | Direct copy |
| `BORR_LST_NM` | `last_name` | VARCHAR → STRING | Direct copy |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR → STRING | Direct copy |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR → STRING | Direct copy (re-encryption recommended) |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR → STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR → STRING | Direct copy |
| `BORR_CTY_NM` | `city` | VARCHAR → STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR → STRING | Direct copy |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR → STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR → STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR → STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR → INT | Parse string to integer |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR → STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `BORR_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |
| `BORR_STAT_CD` | `status` | VARCHAR → STRING | ACT→ACTIVE, INA→INACTIVE |
| `BORR_REC_TYP` | *(dropped)* | — | Not needed in modern schema |

### CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PROD_CD` | `code` | VARCHAR → STRING | Direct copy |
| `PROD_DESC_TXT` | `name` | VARCHAR → STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR → STRING | Direct copy |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | Parse string to integer |
| `PROD_RT_TYP` | `rate_type` | VARCHAR → STRING | Direct copy |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `PROD_STAT_CD` | `is_active` | VARCHAR → BOOLEAN | ACT→true, INA→false |
| `PROD_EFF_DT` | `effective_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR → DATE | Parse MM/DD/YYYY |

### CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `LN_ACCT_NBR` | `account_number` | VARCHAR → STRING | Direct copy |
| `BORR_ID` | `borrower_id` | VARCHAR → BIGINT | FK lookup via borrowers.external_id |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_id` | VARCHAR → BIGINT | FK lookup via loan_products.code |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | Parse string |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | Parse string |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `LN_ORIG_DT` | `origination_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `LN_MAT_DT` | `maturity_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `LN_STAT_CD` | `status` | VARCHAR → STRING | ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | Parse string |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | Parse string |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR → STRING | SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |
| `LN_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |
| *(derived)* | `origination_year` | — | Extracted year from origination_date (partition column) |

### CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PMT_SEQ_NBR` | `legacy_payment_id` | VARCHAR → STRING | Preserved for audit trail |
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
| *(derived)* | `payment_year` | — | Extracted year from payment_date (partition column) |

---

## 5. Transformation Decisions

### 5.1 Date Parsing

**Decision**: Use `to_date(col, 'MM/dd/yyyy')` for DATE columns and `to_timestamp(col, 'MM/dd/yyyy')` for TIMESTAMP columns.

**Rationale**: The legacy system consistently uses `MM/DD/YYYY` format across all date fields. PySpark's `to_date` with the Java SimpleDateFormat pattern handles this reliably. Nulls and empty strings naturally produce null output without failing the pipeline.

**Edge cases handled**:
- Null source values → null output (valid)
- Empty strings → null output (valid)
- Malformed dates (e.g., `13/32/2020`) → null output, logged by validation flags

### 5.2 Amount Parsing

**Decision**: Strip commas with `regexp_replace(col, ',', '')` then cast to `DecimalType`.

**Rationale**: Legacy amounts use US-format comma separators (e.g., `"285,000"`, `"271,432.56"`). A simple regex remove + cast handles all observed patterns. We use `DECIMAL(12,2)` for loan amounts (up to $9.999 billion with cents) and `DECIMAL(10,2)` for payment amounts (up to $99 million with cents).

**Edge cases handled**:
- Values with no commas (e.g., `"0.00"`) → parsed correctly
- Values with commas in cents (not observed but would parse as string → caught by validation)
- Null/empty values → null output

### 5.3 Status Code Expansion

**Decision**: Expand all abbreviation codes to full readable values using static mapping dictionaries.

**Mappings**:
| Context | Legacy Code | Modern Value |
|---------|-------------|--------------|
| Loan Status | `ACT` | `ACTIVE` |
| Loan Status | `CLO` | `CLOSED` |
| Loan Status | `DFT` | `DEFAULT` |
| Loan Status | `FRB` | `FORBEARANCE` |
| Borrower Status | `ACT` | `ACTIVE` |
| Borrower Status | `INA` | `INACTIVE` |
| Payment Type | `REG` | `REGULAR` |
| Payment Type | `EXT` | `EXTRA` |
| Payment Type | `PRT` | `PARTIAL` |
| Payment Type | `PRE` | `PREPAYMENT` |
| Payment Status | `PST` | `POSTED` |
| Payment Status | `REV` | `REVERSED` |
| Payment Status | `NSF` | `NSF` |
| Payment Status | `PND` | `PENDING` |
| Property Type | `SFR` | `Single Family` |
| Property Type | `CND` | `Condominium` |
| Property Type | `MFR` | `Multi-Family` |
| Property Type | `TWN` | `Townhouse` |
| Product Status | `ACT` | `true` (BOOLEAN) |
| Product Status | `INA` | `false` (BOOLEAN) |

**Unknown codes**: If a code is not in the mapping, it is preserved with a `_UNKNOWN` suffix for downstream investigation rather than being silently dropped.

### 5.4 Denormalization Removal

**Decision**: Drop `BORR_FST_NM`, `BORR_LST_NM`, and `BORR_SSN_LST4` from the loan accounts table. Use `borrower_id` FK to the `borrowers` table instead.

**Rationale**: The denormalized borrower fields in `CDW_LN_ACCT` are redundant with `CDW_BORR_MSTR` and create data inconsistency risk. The modern schema normalizes this by maintaining a single source of truth in the `borrowers` table.

### 5.5 Foreign Key Resolution

**Decision**: Resolve legacy string IDs to modern surrogate keys via left joins during ingestion.

- `CDW_LN_ACCT.BORR_ID` → lookup `borrowers.id` WHERE `borrowers.external_id = BORR_ID`
- `CDW_LN_ACCT.PROD_CD` → lookup `loan_products.id` WHERE `loan_products.code = PROD_CD`
- `CDW_PMT_HIST.LN_ACCT_NBR` → lookup `loan_accounts.id` WHERE `loan_accounts.account_number = LN_ACCT_NBR`

**Unresolvable references**: Left join ensures rows are not dropped. Unresolvable FKs result in null values, which are caught by the data quality null checks and referential integrity checks.

### 5.6 Null Handling

**Decision**: Never silently drop records. All null/malformed values are:
1. Preserved as null in the target
2. Logged with warnings during ingestion
3. Flagged by the data quality framework post-ingestion

This approach ensures complete data lineage and allows the migration team to investigate issues without data loss.

---

## 6. Partitioning Strategy

### Rationale

| Table | Partition Column | Reasoning |
|-------|-----------------|-----------|
| `borrowers` | `status` | Low cardinality (ACTIVE/INACTIVE). Most queries filter by status. Efficient for segmenting active customer base from inactive records. |
| `loan_products` | *(none)* | Small reference table (typically <100 rows). Partitioning would create more overhead than benefit. |
| `loan_accounts` | `origination_year` | Natural time dimension for loan portfolios. Enables efficient time-range queries (e.g., "all loans originated in 2021"). Moderate cardinality (one partition per year). |
| `payments` | `payment_year` | High-volume transaction table. Year partitioning enables efficient historical queries and partition pruning for recent payment lookups. |

### Delta Lake Optimizations

All tables include these properties:
- `delta.autoOptimize.optimizeWrite = true`: Automatically coalesces small files during writes.
- `delta.autoOptimize.autoCompact = true`: Background compaction of small files.
- `delta.columnMapping.mode = 'name'`: Enables column rename/drop without full rewrite.

---

## 7. Execution Order

### Prerequisites

1. Databricks workspace with Unity Catalog enabled
2. Source data files staged in a cloud storage location (e.g., `/mnt/landing/`)
3. Cluster with Delta Lake runtime (DBR 12.0+)
4. Sufficient permissions to create schemas and tables

### Step-by-Step Execution

Execute the following steps in order. **Do not skip or reorder** — later steps depend on tables created in earlier steps.

```
Step 1: Create Schema
─────────────────────
File: databricks/ddl/00_create_schema.sql
Action: Run in a Databricks SQL notebook or via spark.sql()
Creates: loan_management schema

Step 2: Create Delta Tables (DDL)
─────────────────────────────────
Files: databricks/ddl/01_borrowers.sql
       databricks/ddl/02_loan_products.sql
       databricks/ddl/03_loan_accounts.sql
       databricks/ddl/04_payments.sql
Action: Run each DDL file in numeric order
Creates: Empty Delta tables with proper schema

Step 3: Ingest Dimension Tables (no FK dependencies)
────────────────────────────────────────────────────
Files: databricks/ingestion/ingest_borrowers.py
       databricks/ingestion/ingest_loan_products.py
Action: Can run in parallel (no dependencies between them)
Command:
  spark-submit ingest_borrowers.py --source /mnt/landing/cdw_borr_mstr.csv
  spark-submit ingest_loan_products.py --source /mnt/landing/cdw_ln_prod.csv

Step 4: Ingest Loan Accounts (depends on Step 3)
─────────────────────────────────────────────────
File: databricks/ingestion/ingest_loan_accounts.py
Action: Must run AFTER borrowers and loan_products are populated
Command:
  spark-submit ingest_loan_accounts.py --source /mnt/landing/cdw_ln_acct.csv

Step 5: Ingest Payments (depends on Step 4)
───────────────────────────────────────────
File: databricks/ingestion/ingest_payments.py
Action: Must run AFTER loan_accounts is populated
Command:
  spark-submit ingest_payments.py --source /mnt/landing/cdw_pmt_hist.csv

Step 6: Run Data Quality Checks
────────────────────────────────
File: databricks/quality/data_quality_checks.py
Action: Run AFTER all ingestion steps complete
Command:
  spark-submit data_quality_checks.py \
    --borrowers-source /mnt/landing/cdw_borr_mstr.csv \
    --products-source /mnt/landing/cdw_ln_prod.csv \
    --accounts-source /mnt/landing/cdw_ln_acct.csv \
    --payments-source /mnt/landing/cdw_pmt_hist.csv \
    --output-dir /mnt/reports
Output: DATA_QUALITY_REPORT.md
```

### Automated Orchestrator

For convenience, `databricks/ingestion/run_full_ingestion.py` orchestrates Steps 3-5 in a single execution:

```bash
spark-submit run_full_ingestion.py \
    --borrowers-source /mnt/landing/cdw_borr_mstr.csv \
    --products-source /mnt/landing/cdw_ln_prod.csv \
    --accounts-source /mnt/landing/cdw_ln_acct.csv \
    --payments-source /mnt/landing/cdw_pmt_hist.csv
```

---

## 8. Data Quality Validation

### Check Categories

The data quality framework (`databricks/quality/data_quality_checks.py`) runs four categories of checks:

#### 8.1 Row Count Reconciliation

Compares source file row counts against target Delta table row counts. Any mismatch indicates records were dropped or duplicated during ingestion.

| Source Table | Target Table | Expected Rows (Seed) |
|-------------|-------------|---------------------|
| CDW_BORR_MSTR | borrowers | 5 |
| CDW_LN_PROD | loan_products | 5 |
| CDW_LN_ACCT | loan_accounts | 5 |
| CDW_PMT_HIST | payments | 10 |

#### 8.2 Null Checks on Required Fields

Verifies that columns marked as NOT NULL in the DDL contain no null values:

- `borrowers`: external_id, first_name, last_name
- `loan_products`: code, name, type, term_months, rate_type
- `loan_accounts`: account_number, borrower_id, product_id, original_amount, current_balance, interest_rate, term_months, monthly_payment, origination_date, maturity_date
- `payments`: loan_account_id, payment_date, total_amount, type, status

#### 8.3 Referential Integrity

Checks for orphan records (FK values that don't match a parent table):

- `loan_accounts.borrower_id` → `borrowers.id`
- `loan_accounts.product_id` → `loan_products.id`
- `payments.loan_account_id` → `loan_accounts.id`

#### 8.4 Business Rules

| Rule | Table | Condition |
|------|-------|-----------|
| Active loans have balance > 0 | loan_accounts | `status = 'ACTIVE' → current_balance > 0` |
| Closed loans have maturity date | loan_accounts | `status = 'CLOSED' → maturity_date IS NOT NULL` |
| Origination before maturity | loan_accounts | `origination_date < maturity_date` |
| Non-negative payments | payments | `total_amount >= 0` |
| Valid credit scores | borrowers | `credit_score BETWEEN 300 AND 850` |
| Reasonable interest rates | loan_accounts | `interest_rate BETWEEN 0 AND 30` |
| Non-negative escrow | loan_accounts | `escrow_balance >= 0` |
| Active loans have positive payment | loan_accounts | `status = 'ACTIVE' → monthly_payment > 0` |

### Report Output

The quality framework generates `DATA_QUALITY_REPORT.md` with:
- Executive summary (total/passed/failed counts, pass rate)
- Detailed results table per check category
- Recommendations for any failed checks

---

## 9. Rollback Procedure

Delta Lake's time-travel capability provides built-in rollback:

```sql
-- View table history to find the version before migration
DESCRIBE HISTORY loan_management.borrowers;

-- Rollback to a specific version
RESTORE TABLE loan_management.borrowers TO VERSION AS OF <version_number>;

-- Or rollback to a specific timestamp
RESTORE TABLE loan_management.loan_accounts TO TIMESTAMP AS OF '2025-01-15T00:00:00';
```

For a complete rollback, drop all tables and re-run the DDL:

```sql
DROP TABLE IF EXISTS loan_management.payments;
DROP TABLE IF EXISTS loan_management.loan_accounts;
DROP TABLE IF EXISTS loan_management.loan_products;
DROP TABLE IF EXISTS loan_management.borrowers;
DROP SCHEMA IF EXISTS loan_management CASCADE;
```

---

## 10. Post-Migration Verification

After running data quality checks, perform these manual verifications:

### 10.1 Spot-Check Sample Records

```sql
-- Verify a known borrower was migrated correctly
SELECT * FROM loan_management.borrowers WHERE external_id = 'B-10001';
-- Expected: first_name='James', last_name='Mitchell', credit_score=745,
--           annual_income=92500.00, status='ACTIVE'

-- Verify loan account FK resolution
SELECT la.account_number, b.first_name, b.last_name, lp.name as product_name
FROM loan_management.loan_accounts la
JOIN loan_management.borrowers b ON la.borrower_id = b.id
JOIN loan_management.loan_products lp ON la.product_id = lp.id
WHERE la.account_number = 'LN-2019-00142';
-- Expected: James Mitchell, 30-Year Fixed Rate Mortgage

-- Verify payment FK resolution and amount parsing
SELECT p.payment_date, p.total_amount, p.type, p.status
FROM loan_management.payments p
JOIN loan_management.loan_accounts la ON p.loan_account_id = la.id
WHERE la.account_number = 'LN-2019-00142'
ORDER BY p.payment_date DESC;
-- Expected: 2 payments, REGULAR type, POSTED status, amounts as decimals
```

### 10.2 Aggregate Validation

```sql
-- Verify total loan portfolio balance
SELECT COUNT(*) as total_loans,
       SUM(current_balance) as total_portfolio_balance,
       AVG(interest_rate) as avg_rate
FROM loan_management.loan_accounts;

-- Verify payment totals per loan
SELECT la.account_number,
       COUNT(p.id) as payment_count,
       SUM(p.total_amount) as total_paid
FROM loan_management.loan_accounts la
JOIN loan_management.payments p ON la.id = p.loan_account_id
GROUP BY la.account_number;
```

---

## 11. Troubleshooting

### Common Issues

| Issue | Cause | Resolution |
|-------|-------|------------|
| `ParseException: cannot resolve column` | Source file column names don't match expected legacy names | Verify CSV headers match `CDW_BORR_MSTR`, `CDW_LN_ACCT`, etc. |
| Null FK after ingestion | Dimension table not populated before fact table | Run ingestion in correct order (borrowers/products before accounts) |
| Date parse returns all nulls | Source uses different date format than MM/DD/YYYY | Inspect source data; update `parse_date_col` format pattern |
| Row count mismatch | Duplicate records in source or write mode issue | Check source for duplicates; verify write mode is `overwrite` for initial load |
| `_UNKNOWN` suffix in status fields | Source contains status codes not in mapping dictionary | Add new codes to the mapping dictionaries in `transformations.py` |
| `AnalysisException: Table not found` | DDL not run or schema not created | Run `00_create_schema.sql` and DDL files before ingestion |

### Logging

All ingestion scripts log to stdout with `[INFO]` and `[WARNING]` levels. Key log messages:
- Source row counts
- Null counts on required fields
- Unresolvable FK references
- Validation flag failures
- Write completion with row counts

---

*This runbook was generated as part of the CDW-to-Delta-Lake migration pipeline. For questions or updates, refer to the source files in `databricks/` or the column mappings in `data/mappings/column_mappings.md`.*
