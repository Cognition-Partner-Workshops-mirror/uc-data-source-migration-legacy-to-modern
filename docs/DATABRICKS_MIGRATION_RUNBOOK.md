# Databricks Migration Runbook

## CDW Legacy System → Delta Lake Modern Warehouse

This runbook documents the complete migration pipeline from the legacy CDW (Corporate Data Warehouse) loan management system to a modern Delta Lake warehouse on Databricks. It covers every transformation decision, column mapping, type conversion, partitioning rationale, and the recommended execution order.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Source System Analysis](#2-source-system-analysis)
3. [Target Schema Design](#3-target-schema-design)
4. [Column Mapping Reference](#4-column-mapping-reference)
5. [Transformation Rules](#5-transformation-rules)
6. [Partitioning Strategy](#6-partitioning-strategy)
7. [Execution Order](#7-execution-order)
8. [Data Quality Framework](#8-data-quality-framework)
9. [Operational Procedures](#9-operational-procedures)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Overview

### Migration Scope

| Aspect | Detail |
|--------|--------|
| **Source** | Legacy CDW (H2/relational DB with all-VARCHAR columns) |
| **Target** | Databricks Delta Lake (`loan_warehouse` database) |
| **Tables** | 4 source tables → 4 Delta tables |
| **Records** | 5 borrowers, 5 products, 5 loan accounts, 10 payments (seed data) |
| **Pipeline** | PySpark ingestion scripts with built-in error handling |
| **Validation** | Post-ingestion data quality framework with 20+ checks |

### Key Migration Goals

1. **Type Safety**: Replace all-VARCHAR storage with proper Spark SQL types (DATE, DECIMAL, INT, BOOLEAN, TIMESTAMP)
2. **Normalization**: Remove denormalized borrower fields from loan accounts; use foreign key references
3. **Readability**: Map cryptic legacy column names (e.g., `BORR_FST_NM`) to clear modern names (`first_name`)
4. **Code Expansion**: Replace abbreviations (`ACT`, `CLO`, `DFT`) with full readable values (`Active`, `Closed`, `Default`)
5. **Data Quality**: Validate every transformation with automated checks and generate audit reports

---

## 2. Source System Analysis

### Legacy Tables

| Legacy Table | Description | Rows (seed) | Key Issues |
|-------------|-------------|-------------|------------|
| `CDW_BORR_MSTR` | Borrower master | 5 | All VARCHAR, dates as MM/DD/YYYY strings, income as comma-formatted string |
| `CDW_LN_PROD` | Loan products | 5 | Amounts as comma strings, status codes, term as string |
| `CDW_LN_ACCT` | Loan accounts | 5 | Denormalized (embeds borrower name/SSN), 30 VARCHAR columns |
| `CDW_PMT_HIST` | Payment history | 10 | All amounts as comma strings, 4 date fields as strings |

### Legacy Schema Characteristics

- **All columns are VARCHAR**: No type enforcement at the database level
- **Dates stored as strings**: Format `MM/DD/YYYY` (e.g., `"03/15/1978"`)
- **Amounts stored as comma-formatted strings**: e.g., `"285,000"`, `"271,432.56"`
- **Cryptic abbreviations**: Column names use abbreviated conventions (`BORR_FST_NM`, `LN_CURR_BAL`)
- **Status codes**: Short codes like `ACT`, `CLO`, `DFT`, `FRB`, `PST`, `REG`
- **No foreign keys**: No referential integrity constraints
- **Denormalization**: `CDW_LN_ACCT` duplicates borrower first name, last name, and last-4 SSN

---

## 3. Target Schema Design

### Database

```sql
CREATE DATABASE IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse migrated from legacy CDW system'
LOCATION '/mnt/delta/loan_warehouse';
```

### Target Tables

| Target Table | Source | Format | Partition Key | Rationale |
|-------------|--------|--------|---------------|-----------|
| `loan_warehouse.borrowers` | CDW_BORR_MSTR | Delta | `status` | Most queries filter by active/inactive borrowers |
| `loan_warehouse.loan_products` | CDW_LN_PROD | Delta | *(none)* | Small reference table (~10s of rows); partitioning adds overhead |
| `loan_warehouse.loan_accounts` | CDW_LN_ACCT | Delta | `origination_year` | Enables vintage analysis and efficient time-range pruning |
| `loan_warehouse.payments` | CDW_PMT_HIST | Delta | `payment_year_month` | Natural time-series partitioning for incremental loads |

### Delta Table Properties

All tables use:
- `delta.autoOptimize.optimizeWrite = true` — Automatically coalesces small files
- `delta.autoOptimize.autoCompact = true` — Runs auto-compaction
- `delta.deletedFileRetentionDuration = interval 30 days` — Retention for time travel (fact tables)
- `delta.logRetentionDuration = interval 90 days` — Transaction log retention (fact tables)

### Lineage Metadata Columns

Every target table includes:
- `_migration_source` (STRING): Name of the source legacy table
- `_migrated_at` (TIMESTAMP): Timestamp of the migration run

---

## 4. Column Mapping Reference

### CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|--------------|---------------|-------------|----------------|
| BORR_ID | external_id | VARCHAR→STRING | Direct copy |
| BORR_FST_NM | first_name | VARCHAR→STRING | Direct copy |
| BORR_LST_NM | last_name | VARCHAR→STRING | Direct copy |
| BORR_MID_INIT | middle_initial | VARCHAR→STRING | Direct copy |
| BORR_SSN_ENCR | ssn_hash | VARCHAR→STRING | Direct copy (re-encrypt recommended) |
| BORR_DOB_DT | date_of_birth | VARCHAR→DATE | Parse MM/DD/YYYY |
| BORR_ADDR_LN1 | address_line1 | VARCHAR→STRING | Direct copy |
| BORR_ADDR_LN2 | address_line2 | VARCHAR→STRING | Direct copy |
| BORR_CTY_NM | city | VARCHAR→STRING | Direct copy |
| BORR_ST_CD | state | VARCHAR→STRING | Direct copy |
| BORR_ZIP_CD | zip_code | VARCHAR→STRING | Direct copy |
| BORR_PH_NBR | phone | VARCHAR→STRING | Direct copy |
| BORR_EMAIL_ADDR | email | VARCHAR→STRING | Direct copy |
| BORR_CRDT_SCR | credit_score | VARCHAR→INT | Parse string to integer |
| BORR_EMP_STAT | employment_status | VARCHAR→STRING | Direct copy |
| BORR_ANN_INCM | annual_income | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| BORR_CRET_DT | created_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |
| BORR_UPDT_DT | updated_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |
| BORR_STAT_CD | status | VARCHAR→STRING | ACT→Active, INA→Inactive |
| BORR_REC_TYP | *(dropped)* | — | Not needed in modern schema |

### CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|--------------|---------------|-------------|----------------|
| PROD_CD | code | VARCHAR→STRING | Direct copy |
| PROD_DESC_TXT | name | VARCHAR→STRING | Direct copy |
| PROD_TYP_CD | type | VARCHAR→STRING | Direct copy |
| PROD_TERM_MOS | term_months | VARCHAR→INT | Parse string to integer |
| PROD_RT_TYP | rate_type | VARCHAR→STRING | Direct copy |
| PROD_MIN_AMT | min_amount | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| PROD_MAX_AMT | max_amount | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| PROD_STAT_CD | is_active | VARCHAR→BOOLEAN | ACT→true, INA→false |
| PROD_EFF_DT | effective_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| PROD_EXP_DT | expiration_date | VARCHAR→DATE | Parse MM/DD/YYYY |

### CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|--------------|---------------|-------------|----------------|
| LN_ACCT_NBR | account_number | VARCHAR→STRING | Direct copy |
| BORR_ID | borrower_external_id | VARCHAR→STRING | FK to borrowers.external_id |
| BORR_FST_NM | *(dropped)* | — | Denormalized; use borrower FK |
| BORR_LST_NM | *(dropped)* | — | Denormalized; use borrower FK |
| BORR_SSN_LST4 | *(dropped)* | — | Denormalized; use borrower FK |
| PROD_CD | product_code | VARCHAR→STRING | FK to loan_products.code |
| LN_ORIG_AMT | original_amount | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| LN_CURR_BAL | current_balance | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| LN_INT_RT | interest_rate | VARCHAR→DECIMAL(5,3) | Parse string |
| LN_TERM_MOS | term_months | VARCHAR→INT | Parse string to integer |
| LN_PMT_AMT | monthly_payment | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| LN_ORIG_DT | origination_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_MAT_DT | maturity_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_1ST_PMT_DT | first_payment_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_NXT_PMT_DT | next_payment_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_STAT_CD | status | VARCHAR→STRING | ACT→Active, CLO→Closed, DFT→Default, FRB→Forbearance |
| LN_DLQ_DAYS | delinquency_days | VARCHAR→INT | Parse string to integer |
| LN_ESCROW_BAL | escrow_balance | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| LN_LTV_PCT | ltv_percent | VARCHAR→DECIMAL(5,2) | Parse string |
| PROP_ADDR_LN1 | property_address | VARCHAR→STRING | Direct copy |
| PROP_CTY_NM | property_city | VARCHAR→STRING | Direct copy |
| PROP_ST_CD | property_state | VARCHAR→STRING | Direct copy |
| PROP_ZIP_CD | property_zip | VARCHAR→STRING | Direct copy |
| PROP_TYP_CD | property_type | VARCHAR→STRING | SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| PROP_APRS_VAL | appraised_value | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| LN_CRET_DT | created_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |
| LN_UPDT_DT | updated_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |
| *(derived)* | origination_year | —→INT | `year(origination_date)` partition key |

### CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Change | Transformation |
|--------------|---------------|-------------|----------------|
| PMT_SEQ_NBR | legacy_payment_id | VARCHAR→STRING | Preserved for traceability |
| LN_ACCT_NBR | loan_account_number | VARCHAR→STRING | FK to loan_accounts.account_number |
| PMT_DT | payment_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| PMT_AMT | total_amount | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_PRIN_AMT | principal_amount | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_INT_AMT | interest_amount | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_ESCROW_AMT | escrow_amount | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_LATE_FEE | late_fee | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_TYP_CD | type | VARCHAR→STRING | REG→Regular, EXT→Extra, PRT→Partial, PRE→Prepayment |
| PMT_STAT_CD | status | VARCHAR→STRING | PST→Posted, REV→Reversed, NSF→NSF, PND→Pending |
| PMT_RECV_DT | received_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| PMT_PROC_DT | processed_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| PMT_CRET_DT | created_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |
| PMT_UPDT_DT | updated_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |
| *(derived)* | payment_year_month | —→STRING | `date_format(payment_date, 'yyyy-MM')` partition key |

---

## 5. Transformation Rules

### 5.1 Date Conversion

**Pattern**: `MM/DD/YYYY` VARCHAR → `DATE` or `TIMESTAMP`

```python
# DATE conversion
F.to_date(F.col("BORR_DOB_DT"), "MM/dd/yyyy")

# TIMESTAMP conversion (midnight of the given date)
F.to_timestamp(F.col("BORR_CRET_DT"), "MM/dd/yyyy")
```

**Decision**: Legacy system stored only dates (no time component). For `created_at`/`updated_at` fields, we convert to TIMESTAMP at midnight (00:00:00) since the source has no time precision. New records created post-migration will have full timestamp precision.

**Error handling**: Malformed date strings result in NULL with a boolean error flag column (`_<col>_parse_error = true`) for audit. Records are NOT dropped.

### 5.2 Amount Conversion

**Pattern**: Comma-formatted VARCHAR → `DECIMAL(p, s)`

```python
# Remove commas, then cast
F.regexp_replace(F.col("LN_ORIG_AMT"), ",", "").cast(DecimalType(12, 2))
```

**Precision choices**:
- `DECIMAL(12, 2)` for large amounts (loan amounts, income, appraised values) — supports up to $9,999,999,999.99
- `DECIMAL(10, 2)` for payment amounts and balances — supports up to $99,999,999.99
- `DECIMAL(5, 3)` for interest rates — supports up to 99.999%
- `DECIMAL(5, 2)` for LTV percent — supports up to 999.99%

### 5.3 Status Code Expansion

All status code mappings are defined in `databricks/ingestion/transform_utils.py`:

| Context | Code → Expanded Value |
|---------|----------------------|
| Borrower status | ACT → Active, INA → Inactive |
| Loan status | ACT → Active, CLO → Closed, DFT → Default, FRB → Forbearance |
| Product status | ACT → true (boolean), INA → false (boolean) |
| Payment type | REG → Regular, EXT → Extra, PRT → Partial, PRE → Prepayment |
| Payment status | PST → Posted, REV → Reversed, NSF → NSF, PND → Pending |
| Property type | SFR → Single Family, CND → Condominium, MFR → Multi-Family, TWN → Townhouse |

**Decision**: Unknown/unmapped codes are preserved as-is (not dropped) and flagged with `_<col>_unmapped = true` for investigation.

### 5.4 Denormalization Removal

The legacy `CDW_LN_ACCT` table contains redundant borrower fields:
- `BORR_FST_NM` (borrower first name)
- `BORR_LST_NM` (borrower last name)
- `BORR_SSN_LST4` (last 4 of SSN)

**Decision**: These columns are **dropped** during ingestion. The modern schema uses `borrower_external_id` as a foreign key to `borrowers.external_id`. To retrieve borrower details, join:

```sql
SELECT l.*, b.first_name, b.last_name
FROM loan_warehouse.loan_accounts l
JOIN loan_warehouse.borrowers b ON l.borrower_external_id = b.external_id
```

### 5.5 Null and Edge Case Handling

- **Null source values**: Preserved as NULL in the target (not converted to defaults)
- **Malformed values**: Set to NULL with a parse-error flag column for auditing
- **Empty strings**: Treated as NULL during type conversion (Spark default behavior)
- **Records are never silently dropped**: All source records appear in the target; errors are flagged, not filtered

---

## 6. Partitioning Strategy

### Rationale

| Table | Partition Column | Type | Why |
|-------|-----------------|------|-----|
| `borrowers` | `status` | STRING | Low cardinality (Active/Inactive). Most queries filter by active borrowers. Efficient for portfolio reporting. |
| `loan_products` | *(none)* | — | Reference table with ~5-50 rows. Partitioning would create excessive small files with no query benefit. |
| `loan_accounts` | `origination_year` | INT | Supports vintage analysis (a core loan analytics pattern). Enables efficient pruning for time-range portfolio queries. Moderate cardinality (~5-30 partitions). |
| `payments` | `payment_year_month` | STRING (YYYY-MM) | Natural time-series dimension. Supports incremental loading (append new months). Optimizes date-range payment queries. |

### Partition Sizing Guidelines

- Target **128 MB–1 GB** per partition file for optimal Delta Lake performance
- `loan_accounts` by `origination_year`: At scale, expect ~10K-100K loans per year → well-sized partitions
- `payments` by `payment_year_month`: At scale, expect ~50K-500K payments per month → good partition sizing
- `borrowers` by `status`: Only 2 partitions (Active/Inactive) — simple and effective

---

## 7. Execution Order

### Prerequisites

1. Databricks workspace with Unity Catalog or Hive metastore access
2. Source files extracted from legacy CDW and placed in landing zone (`/mnt/landing/`)
3. Python environment with PySpark available (Databricks Runtime 13.x+ recommended)

### Step-by-Step Execution

```
Step 1: Create Database
────────────────────────
Run: databricks/ddl/create_database.sql
Creates: loan_warehouse database

Step 2: Create Tables (in order)
────────────────────────────────
Run: databricks/ddl/borrowers.sql
Run: databricks/ddl/loan_products.sql
Run: databricks/ddl/loan_accounts.sql    (references borrowers, loan_products)
Run: databricks/ddl/payments.sql          (references loan_accounts)

Step 3: Extract Source Data
───────────────────────────
Export legacy CDW tables to CSV or Parquet files:
  /mnt/landing/cdw_borr_mstr/     (CSV with header)
  /mnt/landing/cdw_ln_prod/       (CSV with header)
  /mnt/landing/cdw_ln_acct/       (CSV with header)
  /mnt/landing/cdw_pmt_hist/      (CSV with header)

Step 4: Run Ingestion Pipeline
──────────────────────────────
Option A — Full pipeline (recommended):
  spark-submit databricks/ingestion/run_full_ingestion.py \
    --landing-dir /mnt/landing \
    --format csv

Option B — Individual tables:
  spark-submit databricks/ingestion/ingest_borrowers.py /mnt/landing/cdw_borr_mstr csv
  spark-submit databricks/ingestion/ingest_loan_products.py /mnt/landing/cdw_ln_prod csv
  spark-submit databricks/ingestion/ingest_loan_accounts.py /mnt/landing/cdw_ln_acct csv
  spark-submit databricks/ingestion/ingest_payments.py /mnt/landing/cdw_pmt_hist csv

Step 5: Run Data Quality Checks
────────────────────────────────
  spark-submit databricks/quality/data_quality_checks.py \
    --landing-dir /mnt/landing \
    --format csv \
    --output-path /dbfs/mnt/reports/DATA_QUALITY_REPORT.md

Step 6: Review Quality Report
─────────────────────────────
  Review the generated DATA_QUALITY_REPORT.md
  Address any FAIL items before marking migration complete
```

### Dependency Graph

```
borrowers ──────────┐
                     ├──→ loan_accounts ──→ payments
loan_products ──────┘
```

`borrowers` and `loan_products` can run in parallel. `loan_accounts` depends on both. `payments` depends on `loan_accounts`.

---

## 8. Data Quality Framework

### Check Categories

| Category | Checks | Purpose |
|----------|--------|---------|
| Row Count Reconciliation | 4 | Source count == target count for each table |
| Null Checks | 17 | Required fields (NOT NULL) contain no nulls |
| Referential Integrity | 3 | FK relationships are valid across tables |
| Business Rules | 8 | Domain-specific invariants hold true |

### Business Rule Details

| Rule | Table | Condition | Severity |
|------|-------|-----------|----------|
| Active loans have positive balance | loan_accounts | `status='Active' → current_balance > 0` | FAIL |
| Closed loans have maturity date | loan_accounts | `status='Closed' → maturity_date IS NOT NULL` | FAIL |
| Origination before maturity | loan_accounts | `origination_date < maturity_date` | FAIL |
| Interest rate in range | loan_accounts | `0 ≤ interest_rate ≤ 100` | FAIL |
| LTV in range | loan_accounts | `0 ≤ ltv_percent ≤ 200` (if present) | FAIL |
| Payment components sum | payments | `principal + interest + escrow + late_fee ≈ total` | WARN |
| Non-negative delinquency | loan_accounts | `delinquency_days ≥ 0` | FAIL |
| Valid loan statuses | loan_accounts | `status IN (Active, Closed, Default, Forbearance)` | FAIL |

### Report Output

The quality framework generates `DATA_QUALITY_REPORT.md` with:
- Summary table (total/pass/fail/warn counts)
- Detailed results per check
- Category descriptions for audit trail

---

## 9. Operational Procedures

### Initial Migration (Full Load)

1. Run DDL scripts to create database and tables
2. Extract full legacy data to landing zone
3. Run `run_full_ingestion.py` with `--format csv`
4. Run `data_quality_checks.py`
5. Review report; remediate any failures
6. Sign off on migration

### Incremental Loads (Post-Migration)

For ongoing synchronization until legacy system is decommissioned:

1. Extract delta/changed records from legacy CDW
2. Place in landing zone with appropriate naming
3. Run individual ingestion scripts with `mode="append"` (modify write mode)
4. Run quality checks on the incremental batch
5. Consider using Delta Lake MERGE for upsert patterns:

```python
from delta.tables import DeltaTable

target = DeltaTable.forName(spark, "loan_warehouse.loan_accounts")
target.alias("t").merge(
    source_df.alias("s"),
    "t.account_number = s.account_number"
).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()
```

### Rollback Procedure

Delta Lake supports time travel for rollback:

```sql
-- View table history
DESCRIBE HISTORY loan_warehouse.loan_accounts;

-- Restore to a previous version
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF <version_number>;

-- Or restore to a timestamp
RESTORE TABLE loan_warehouse.loan_accounts TO TIMESTAMP AS OF '2025-01-15 00:00:00';
```

---

## 10. Troubleshooting

### Common Issues

| Issue | Cause | Resolution |
|-------|-------|------------|
| Date parse returns NULL | Source date not in MM/DD/YYYY format | Check `_*_parse_error` flag columns; inspect raw source data |
| Amount parse returns NULL | Unexpected characters (e.g., `$`, spaces) | Extend `regexp_replace` pattern to strip additional characters |
| Unmapped status code | New code not in mapping dictionary | Add to the appropriate map in `transform_utils.py`; check `_*_unmapped` flags |
| Row count mismatch | Duplicate source records or header issues | Check CSV for duplicate headers or malformed rows |
| FK integrity failure | Orphan references in source data | Review source data quality; add missing parent records |
| Small file problem | Too many partitions for data volume | Adjust partition strategy or run `OPTIMIZE` on the Delta table |

### Monitoring Queries

```sql
-- Check row counts
SELECT 'borrowers' AS tbl, COUNT(*) AS cnt FROM loan_warehouse.borrowers
UNION ALL
SELECT 'loan_products', COUNT(*) FROM loan_warehouse.loan_products
UNION ALL
SELECT 'loan_accounts', COUNT(*) FROM loan_warehouse.loan_accounts
UNION ALL
SELECT 'payments', COUNT(*) FROM loan_warehouse.payments;

-- Check partition distribution
SELECT origination_year, COUNT(*) FROM loan_warehouse.loan_accounts GROUP BY 1 ORDER BY 1;
SELECT payment_year_month, COUNT(*) FROM loan_warehouse.payments GROUP BY 1 ORDER BY 1;

-- Check for parse errors (if error columns retained in staging)
SELECT * FROM loan_warehouse.loan_accounts WHERE _origination_date_parse_error = true;
```

---

## Appendix: File Inventory

| Path | Description |
|------|-------------|
| `databricks/ddl/create_database.sql` | Database creation DDL |
| `databricks/ddl/borrowers.sql` | Borrowers Delta table DDL |
| `databricks/ddl/loan_products.sql` | Loan products Delta table DDL |
| `databricks/ddl/loan_accounts.sql` | Loan accounts Delta table DDL |
| `databricks/ddl/payments.sql` | Payments Delta table DDL |
| `databricks/ingestion/__init__.py` | Ingestion package init |
| `databricks/ingestion/transform_utils.py` | Shared transformation utilities and UDFs |
| `databricks/ingestion/ingest_borrowers.py` | Borrower ingestion script |
| `databricks/ingestion/ingest_loan_products.py` | Loan product ingestion script |
| `databricks/ingestion/ingest_loan_accounts.py` | Loan account ingestion script |
| `databricks/ingestion/ingest_payments.py` | Payment ingestion script |
| `databricks/ingestion/run_full_ingestion.py` | Full pipeline orchestrator |
| `databricks/quality/__init__.py` | Quality framework package init |
| `databricks/quality/data_quality_checks.py` | Data quality validation module |
| `docs/DATABRICKS_MIGRATION_RUNBOOK.md` | This document |

---

*Document generated as part of the CDW-to-Delta-Lake migration pipeline.*
