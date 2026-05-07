# Databricks Migration Runbook

## Overview

This runbook documents the complete migration of the legacy CDW (Corporate Data Warehouse) loan management tables to a modern Delta Lake schema on Databricks. It covers every transformation decision, column mapping, type conversion, partitioning rationale, and the recommended execution order.

---

## Table of Contents

1. [Source System Summary](#1-source-system-summary)
2. [Target Schema Design](#2-target-schema-design)
3. [Column Mapping Reference](#3-column-mapping-reference)
4. [Type Conversion Rules](#4-type-conversion-rules)
5. [Status Code Expansion](#5-status-code-expansion)
6. [Denormalization Removal](#6-denormalization-removal)
7. [Partitioning Strategy](#7-partitioning-strategy)
8. [Execution Order](#8-execution-order)
9. [Data Quality Validation](#9-data-quality-validation)
10. [Rollback Procedure](#10-rollback-procedure)
11. [Operational Notes](#11-operational-notes)

---

## 1. Source System Summary

The legacy CDW contains four tables used by the loan management application:

| Legacy Table | Description | Row Count (seed) | Key Issues |
|-------------|-------------|-------------------|------------|
| `CDW_BORR_MSTR` | Borrower master | 5 | All VARCHAR, dates as MM/DD/YYYY strings |
| `CDW_LN_PROD` | Loan products | 5 | Amounts as comma-separated strings |
| `CDW_LN_ACCT` | Loan accounts | 5 | Denormalized borrower fields embedded, no FKs |
| `CDW_PMT_HIST` | Payment history | 10 | Status/type codes as cryptic abbreviations |

**Common legacy patterns:**
- Every column is `VARCHAR` regardless of actual data type
- Dates stored as `MM/DD/YYYY` strings
- Monetary amounts stored with commas (e.g., `"285,000"`, `"1,487.02"`)
- Status fields use 3-letter abbreviations (ACT, CLO, DFT, FRB)
- No foreign key constraints between tables
- `CDW_LN_ACCT` duplicates borrower name and SSN last-4 from `CDW_BORR_MSTR`

---

## 2. Target Schema Design

The modern Delta Lake schema lives in the `loan_warehouse` database with four tables:

| Target Table | Source | Key Improvements |
|-------------|--------|-----------------|
| `loan_warehouse.borrowers` | CDW_BORR_MSTR | Proper DATE/DECIMAL/INT types, partitioned by state |
| `loan_warehouse.loan_products` | CDW_LN_PROD | Boolean `is_active`, proper DECIMAL amounts |
| `loan_warehouse.loan_accounts` | CDW_LN_ACCT | Denormalized fields dropped, FK references via business keys, partitioned by status |
| `loan_warehouse.payments` | CDW_PMT_HIST | Partitioned by payment_year/payment_month, expanded type/status codes |

All tables include audit columns:
- `_load_timestamp` — when the record was loaded into Delta
- `_source_system` — which legacy table the record originated from

### DDL Files (execute in order)

| File | Purpose |
|------|---------|
| `databricks/ddl/00_create_database.sql` | Creates the `loan_warehouse` database |
| `databricks/ddl/01_borrowers.sql` | Borrower dimension table |
| `databricks/ddl/02_loan_products.sql` | Loan product reference table |
| `databricks/ddl/03_loan_accounts.sql` | Loan accounts fact table |
| `databricks/ddl/04_payments.sql` | Payment history fact table |

---

## 3. Column Mapping Reference

### CDW_BORR_MSTR -> borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|--------------|--------------|-------------|----------------|
| BORR_ID | external_id | VARCHAR(20) -> STRING | Direct copy (trimmed) |
| BORR_FST_NM | first_name | VARCHAR(50) -> STRING | Direct copy (trimmed) |
| BORR_LST_NM | last_name | VARCHAR(50) -> STRING | Direct copy (trimmed) |
| BORR_MID_INIT | middle_initial | VARCHAR(1) -> STRING | Direct copy |
| BORR_SSN_ENCR | ssn_hash | VARCHAR(100) -> STRING | Direct copy (re-encrypt recommended) |
| BORR_DOB_DT | date_of_birth | VARCHAR(10) -> DATE | Parse MM/DD/YYYY |
| BORR_ADDR_LN1 | address_line1 | VARCHAR(100) -> STRING | Direct copy |
| BORR_ADDR_LN2 | address_line2 | VARCHAR(100) -> STRING | Direct copy |
| BORR_CTY_NM | city | VARCHAR(50) -> STRING | Direct copy |
| BORR_ST_CD | state | VARCHAR(2) -> STRING | Direct copy |
| BORR_ZIP_CD | zip_code | VARCHAR(10) -> STRING | Direct copy |
| BORR_PH_NBR | phone | VARCHAR(15) -> STRING | Direct copy |
| BORR_EMAIL_ADDR | email | VARCHAR(100) -> STRING | Direct copy |
| BORR_CRDT_SCR | credit_score | VARCHAR(5) -> INT | Parse string to integer |
| BORR_EMP_STAT | employment_status | VARCHAR(20) -> STRING | Direct copy |
| BORR_ANN_INCM | annual_income | VARCHAR(15) -> DECIMAL(12,2) | Remove commas, parse |
| BORR_CRET_DT | created_at | VARCHAR(10) -> TIMESTAMP | Parse MM/DD/YYYY |
| BORR_UPDT_DT | updated_at | VARCHAR(10) -> TIMESTAMP | Parse MM/DD/YYYY |
| BORR_STAT_CD | status | VARCHAR(5) -> STRING | Expand: ACT->ACTIVE, INA->INACTIVE |
| BORR_REC_TYP | *(dropped)* | — | Not needed in modern schema |

### CDW_LN_PROD -> loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|--------------|--------------|-------------|----------------|
| PROD_CD | code | VARCHAR(10) -> STRING | Direct copy |
| PROD_DESC_TXT | name | VARCHAR(200) -> STRING | Direct copy |
| PROD_TYP_CD | type | VARCHAR(5) -> STRING | Direct copy |
| PROD_TERM_MOS | term_months | VARCHAR(5) -> INT | Parse string to integer |
| PROD_RT_TYP | rate_type | VARCHAR(10) -> STRING | Direct copy |
| PROD_MIN_AMT | min_amount | VARCHAR(15) -> DECIMAL(12,2) | Remove commas, parse |
| PROD_MAX_AMT | max_amount | VARCHAR(15) -> DECIMAL(12,2) | Remove commas, parse |
| PROD_STAT_CD | is_active | VARCHAR(5) -> BOOLEAN | ACT->true, INA->false |
| PROD_EFF_DT | effective_date | VARCHAR(10) -> DATE | Parse MM/DD/YYYY |
| PROD_EXP_DT | expiration_date | VARCHAR(10) -> DATE | Parse MM/DD/YYYY |

### CDW_LN_ACCT -> loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|--------------|--------------|-------------|----------------|
| LN_ACCT_NBR | account_number | VARCHAR(20) -> STRING | Direct copy |
| BORR_ID | borrower_external_id | VARCHAR(20) -> STRING | FK reference to borrowers.external_id |
| BORR_FST_NM | *(dropped)* | — | Denormalized; use borrower FK |
| BORR_LST_NM | *(dropped)* | — | Denormalized; use borrower FK |
| BORR_SSN_LST4 | *(dropped)* | — | Denormalized; use borrower FK |
| PROD_CD | product_code | VARCHAR(10) -> STRING | FK reference to loan_products.code |
| LN_ORIG_AMT | original_amount | VARCHAR(15) -> DECIMAL(12,2) | Remove commas, parse |
| LN_CURR_BAL | current_balance | VARCHAR(15) -> DECIMAL(12,2) | Remove commas, parse |
| LN_INT_RT | interest_rate | VARCHAR(8) -> DECIMAL(5,3) | Parse string to decimal |
| LN_TERM_MOS | term_months | VARCHAR(5) -> INT | Parse string to integer |
| LN_PMT_AMT | monthly_payment | VARCHAR(15) -> DECIMAL(10,2) | Remove commas, parse |
| LN_ORIG_DT | origination_date | VARCHAR(10) -> DATE | Parse MM/DD/YYYY |
| LN_MAT_DT | maturity_date | VARCHAR(10) -> DATE | Parse MM/DD/YYYY |
| LN_1ST_PMT_DT | first_payment_date | VARCHAR(10) -> DATE | Parse MM/DD/YYYY |
| LN_NXT_PMT_DT | next_payment_date | VARCHAR(10) -> DATE | Parse MM/DD/YYYY |
| LN_STAT_CD | status | VARCHAR(5) -> STRING | Expand: ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE |
| LN_DLQ_DAYS | delinquency_days | VARCHAR(5) -> INT | Parse string to integer |
| LN_ESCROW_BAL | escrow_balance | VARCHAR(15) -> DECIMAL(10,2) | Remove commas, parse |
| LN_LTV_PCT | ltv_percent | VARCHAR(8) -> DECIMAL(5,2) | Parse string to decimal |
| PROP_ADDR_LN1 | property_address | VARCHAR(100) -> STRING | Direct copy |
| PROP_CTY_NM | property_city | VARCHAR(50) -> STRING | Direct copy |
| PROP_ST_CD | property_state | VARCHAR(2) -> STRING | Direct copy |
| PROP_ZIP_CD | property_zip | VARCHAR(10) -> STRING | Direct copy |
| PROP_TYP_CD | property_type | VARCHAR(10) -> STRING | Expand: SFR->Single Family, CND->Condominium, MFR->Multi-Family, TWN->Townhouse |
| PROP_APRS_VAL | appraised_value | VARCHAR(15) -> DECIMAL(12,2) | Remove commas, parse |
| *(derived)* | origination_year | — -> INT | Extracted from origination_date for partitioning |
| LN_CRET_DT | created_at | VARCHAR(10) -> TIMESTAMP | Parse MM/DD/YYYY |
| LN_UPDT_DT | updated_at | VARCHAR(10) -> TIMESTAMP | Parse MM/DD/YYYY |

### CDW_PMT_HIST -> payments

| Legacy Column | Modern Column | Type Change | Transformation |
|--------------|--------------|-------------|----------------|
| PMT_SEQ_NBR | legacy_payment_id | VARCHAR(20) -> STRING | Preserved for traceability |
| LN_ACCT_NBR | loan_account_number | VARCHAR(20) -> STRING | FK reference to loan_accounts.account_number |
| PMT_DT | payment_date | VARCHAR(10) -> DATE | Parse MM/DD/YYYY |
| PMT_AMT | total_amount | VARCHAR(15) -> DECIMAL(10,2) | Remove commas, parse |
| PMT_PRIN_AMT | principal_amount | VARCHAR(15) -> DECIMAL(10,2) | Remove commas, parse |
| PMT_INT_AMT | interest_amount | VARCHAR(15) -> DECIMAL(10,2) | Remove commas, parse |
| PMT_ESCROW_AMT | escrow_amount | VARCHAR(15) -> DECIMAL(10,2) | Remove commas, parse |
| PMT_LATE_FEE | late_fee | VARCHAR(15) -> DECIMAL(10,2) | Remove commas, parse |
| PMT_TYP_CD | type | VARCHAR(5) -> STRING | Expand: REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT |
| PMT_STAT_CD | status | VARCHAR(5) -> STRING | Expand: PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING |
| PMT_RECV_DT | received_date | VARCHAR(10) -> DATE | Parse MM/DD/YYYY |
| PMT_PROC_DT | processed_date | VARCHAR(10) -> DATE | Parse MM/DD/YYYY |
| *(derived)* | payment_year | — -> INT | Extracted from payment_date for partitioning |
| *(derived)* | payment_month | — -> INT | Extracted from payment_date for partitioning |
| PMT_CRET_DT | created_at | VARCHAR(10) -> TIMESTAMP | Parse MM/DD/YYYY |
| PMT_UPDT_DT | updated_at | VARCHAR(10) -> TIMESTAMP | Parse MM/DD/YYYY |

---

## 4. Type Conversion Rules

### Date Parsing
- **Source format:** `MM/DD/YYYY` (e.g., `"03/15/1978"`)
- **Target type:** `DATE` or `TIMESTAMP`
- **PySpark:** `F.to_date(col, "MM/dd/yyyy")` or `F.to_timestamp(col, "MM/dd/yyyy")`
- **Null handling:** Malformed dates return `null`; these are logged but not dropped

### Amount Parsing
- **Source format:** Strings with commas (e.g., `"285,000"`, `"1,487.02"`)
- **Target type:** `DECIMAL(precision, scale)`
- **PySpark:** `F.regexp_replace(col, ",", "").cast(DecimalType(p, s))`
- **Null handling:** Empty strings or non-numeric values return `null`

### Integer Parsing
- **Source format:** Numeric strings (e.g., `"360"`, `"745"`)
- **Target type:** `INT`
- **PySpark:** `col.cast(IntegerType())`

### Boolean Conversion
- **Source:** Status codes `ACT` / `INA`
- **Target:** `BOOLEAN` (`true` / `false`)
- **Applied to:** `loan_products.is_active` only

---

## 5. Status Code Expansion

All abbreviated status codes are expanded to human-readable values. Unrecognized codes default to `"UNKNOWN"`.

### Loan Status (CDW_LN_ACCT.LN_STAT_CD)
| Code | Expanded |
|------|----------|
| ACT | ACTIVE |
| CLO | CLOSED |
| DFT | DEFAULT |
| FRB | FORBEARANCE |

### Borrower Status (CDW_BORR_MSTR.BORR_STAT_CD)
| Code | Expanded |
|------|----------|
| ACT | ACTIVE |
| INA | INACTIVE |

### Payment Type (CDW_PMT_HIST.PMT_TYP_CD)
| Code | Expanded |
|------|----------|
| REG | REGULAR |
| EXT | EXTRA |
| PRT | PARTIAL |
| PRE | PREPAYMENT |

### Payment Status (CDW_PMT_HIST.PMT_STAT_CD)
| Code | Expanded |
|------|----------|
| PST | POSTED |
| REV | REVERSED |
| NSF | NSF |
| PND | PENDING |

### Property Type (CDW_LN_ACCT.PROP_TYP_CD)
| Code | Expanded |
|------|----------|
| SFR | Single Family |
| CND | Condominium |
| MFR | Multi-Family |
| TWN | Townhouse |

### Product Status (CDW_LN_PROD.PROD_STAT_CD)
| Code | Expanded |
|------|----------|
| ACT | true (boolean) |
| INA | false (boolean) |

---

## 6. Denormalization Removal

The legacy `CDW_LN_ACCT` table embeds three borrower fields that duplicate data from `CDW_BORR_MSTR`:

| Dropped Column | Reason |
|----------------|--------|
| `BORR_FST_NM` | Redundant with `CDW_BORR_MSTR.BORR_FST_NM`; join via `borrower_external_id` |
| `BORR_LST_NM` | Redundant with `CDW_BORR_MSTR.BORR_LST_NM` |
| `BORR_SSN_LST4` | Redundant with `CDW_BORR_MSTR.BORR_SSN_ENCR` |

In the modern schema, `loan_accounts.borrower_external_id` references `borrowers.external_id` to retrieve borrower details via a join.

**Decision rationale:** Eliminating duplicated borrower data reduces storage, eliminates update anomalies, and ensures a single source of truth for borrower identity.

---

## 7. Partitioning Strategy

| Table | Partition Column(s) | Rationale |
|-------|-------------------|-----------|
| `borrowers` | `state` | Geographic queries are common in loan servicing; state-level partitioning supports regulatory reporting by jurisdiction |
| `loan_products` | *(none)* | Small reference table (~10s of rows); partitioning would add overhead without benefit |
| `loan_accounts` | `status` | Most queries filter by loan status (active vs closed vs default); high selectivity on a low-cardinality column |
| `payments` | `payment_year`, `payment_month` | Payment queries are almost always time-bounded (monthly statements, year-end reporting); two-level partitioning balances partition count vs query pruning |

All tables use Delta Lake with auto-optimize enabled (`optimizeWrite` + `autoCompact`) to manage small file problems automatically.

---

## 8. Execution Order

Run the following steps in sequence on a Databricks cluster.

### Step 1: Create Database
```sql
-- Run: databricks/ddl/00_create_database.sql
CREATE DATABASE IF NOT EXISTS loan_warehouse ...
```

### Step 2: Create Tables (in order)
```sql
-- Run: databricks/ddl/01_borrowers.sql
-- Run: databricks/ddl/02_loan_products.sql
-- Run: databricks/ddl/03_loan_accounts.sql
-- Run: databricks/ddl/04_payments.sql
```

### Step 3: Stage Legacy Data
Upload legacy CSV/Parquet extracts to the landing zone:
```
dbfs:/mnt/landing/legacy/CDW_BORR_MSTR/
dbfs:/mnt/landing/legacy/CDW_LN_PROD/
dbfs:/mnt/landing/legacy/CDW_LN_ACCT/
dbfs:/mnt/landing/legacy/CDW_PMT_HIST/
```

### Step 4: Run Ingestion Pipeline
```python
# In a Databricks notebook:
from databricks.ingestion.run_pipeline import run_full_pipeline
from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()
results = run_full_pipeline(spark)
```

The pipeline executes in this order (respecting dependencies):
1. **borrowers** — no dependencies
2. **loan_products** — no dependencies
3. **loan_accounts** — depends on borrowers + loan_products (for RI validation)
4. **payments** — depends on loan_accounts (for RI validation)

Each step uses MERGE INTO (upsert) semantics, so the pipeline is **idempotent** and safe to re-run.

### Step 5: Run Data Quality Checks
```python
from databricks.quality.generate_report import run_quality_suite_and_report

source_counts = {
    "borrowers": 5,
    "loan_products": 5,
    "loan_accounts": 5,
    "payments": 10,
}

report = run_quality_suite_and_report(
    spark,
    source_counts,
    output_path="/dbfs/mnt/reports/DATA_QUALITY_REPORT.md"
)
```

### Step 6: Review Quality Report
Check `DATA_QUALITY_REPORT.md` for pass/fail results across:
- Row count reconciliation
- Null checks on required fields
- Referential integrity
- Business rule validation

---

## 9. Data Quality Validation

The quality framework (`databricks/quality/`) checks four categories:

### Row Count Reconciliation
Compares expected source row counts against actual target table counts. A mismatch indicates records were lost or duplicated during ingestion.

### Null Checks
Verifies that required columns (NOT NULL in the logical model) contain no null values. The full list of required fields is defined in `data_quality_checks.py`.

### Referential Integrity
Validates FK-like relationships:
- `loan_accounts.borrower_external_id` must exist in `borrowers.external_id`
- `loan_accounts.product_code` must exist in `loan_products.code`
- `payments.loan_account_number` must exist in `loan_accounts.account_number`

### Business Rules
- Active loans (`status = 'ACTIVE'`) must have `current_balance > 0`
- Delinquency days must be `>= 0`
- Closed loans should not have future maturity dates
- Payment component amounts (`principal + interest + escrow + late_fee`) must equal `total_amount`
- Credit scores must be in the range 300-850 (when present)

---

## 10. Rollback Procedure

Because all tables use Delta Lake, rollback is straightforward:

```sql
-- Roll back to a previous version
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF <version_number>;
RESTORE TABLE loan_warehouse.loan_products TO VERSION AS OF <version_number>;
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF <version_number>;
RESTORE TABLE loan_warehouse.payments TO VERSION AS OF <version_number>;
```

To find the pre-migration version:
```sql
DESCRIBE HISTORY loan_warehouse.borrowers;
```

For a full reset:
```sql
DROP TABLE IF EXISTS loan_warehouse.payments;
DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
DROP TABLE IF EXISTS loan_warehouse.loan_products;
DROP TABLE IF EXISTS loan_warehouse.borrowers;
-- Then re-run DDL scripts
```

---

## 11. Operational Notes

### Error Handling
- Records failing validation (null required fields) are written to quarantine paths under `dbfs:/mnt/landing/quarantine/<TABLE_NAME>/`
- Quarantined records are preserved in Delta format for investigation
- Referential integrity violations are **logged but not dropped** to avoid silent data loss
- All ingestion steps print detailed counts: source, quarantined, loaded

### Idempotency
All ingestion scripts use `MERGE INTO` with business keys (external_id, code, account_number, legacy_payment_id), making them safe to re-run without creating duplicates.

### Monitoring
- Each ingestion step returns a metrics dict: `{source_count, clean_count, target_count}`
- The pipeline orchestrator prints a summary table at the end
- The data quality report provides a permanent audit trail

### Future Enhancements
- Add Delta Live Tables (DLT) pipeline for continuous incremental ingestion
- Implement Change Data Capture (CDC) from the legacy source
- Add data lineage tracking via Unity Catalog
- Schedule quality checks as a recurring Databricks job
- Add email/Slack alerting on quality check failures
