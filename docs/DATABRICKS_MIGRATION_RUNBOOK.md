# Databricks Migration Runbook

## Overview

This document describes the complete migration pipeline from the legacy CDW (Corporate Data Warehouse) schema to a modern Delta Lake architecture on Databricks. The legacy loan management application uses all-VARCHAR columns, cryptic abbreviated names, and denormalized structures. The target is a normalized, strongly-typed Delta Lake warehouse.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Column Mapping Reference](#column-mapping-reference)
3. [Transformation Decisions](#transformation-decisions)
4. [Type Conversion Details](#type-conversion-details)
5. [Partitioning Strategy](#partitioning-strategy)
6. [Execution Order](#execution-order)
7. [Pre-Migration Checklist](#pre-migration-checklist)
8. [Running the Pipeline](#running-the-pipeline)
9. [Post-Migration Validation](#post-migration-validation)
10. [Rollback Procedure](#rollback-procedure)
11. [Troubleshooting](#troubleshooting)

---

## Architecture

```
┌─────────────────────────────┐     ┌─────────────────────────────┐
│  Legacy CDW (Source)        │     │  Delta Lake (Target)        │
│                             │     │                             │
│  CDW_BORR_MSTR             │────►│  loan_warehouse.borrowers   │
│  CDW_LN_PROD               │────►│  loan_warehouse.loan_products│
│  CDW_LN_ACCT               │────►│  loan_warehouse.loan_accounts│
│  CDW_PMT_HIST              │────►│  loan_warehouse.payments    │
│                             │     │                             │
│  (All VARCHAR, no FKs,      │     │  (Typed, normalized, FKs,   │
│   denormalized)             │     │   partitioned Delta Lake)   │
└─────────────────────────────┘     └─────────────────────────────┘
```

**Source Format:** Legacy data exported as CSV or Parquet files (one directory per table).

**Target:** Databricks Unity Catalog with Delta Lake tables in the `loan_warehouse` database.

---

## Column Mapping Reference

### CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| BORR_ID | external_id | VARCHAR→STRING | Direct copy |
| BORR_FST_NM | first_name | VARCHAR→STRING | Direct copy |
| BORR_LST_NM | last_name | VARCHAR→STRING | Direct copy |
| BORR_MID_INIT | middle_initial | VARCHAR→STRING | Direct copy |
| BORR_SSN_ENCR | ssn_hash | VARCHAR→STRING | Direct copy |
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
| BORR_STAT_CD | status | VARCHAR→STRING | ACT→ACTIVE, INA→INACTIVE |
| BORR_REC_TYP | *(dropped)* | — | Not needed in modern schema |

### CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| PROD_CD | code | VARCHAR→STRING | Direct copy |
| PROD_DESC_TXT | name | VARCHAR→STRING | Direct copy |
| PROD_TYP_CD | type | VARCHAR→STRING | Direct copy |
| PROD_TERM_MOS | term_months | VARCHAR→INT | Parse string |
| PROD_RT_TYP | rate_type | VARCHAR→STRING | Direct copy |
| PROD_MIN_AMT | min_amount | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| PROD_MAX_AMT | max_amount | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| PROD_STAT_CD | is_active | VARCHAR→BOOLEAN | ACT→true, INA→false |
| PROD_EFF_DT | effective_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| PROD_EXP_DT | expiration_date | VARCHAR→DATE | Parse MM/DD/YYYY |

### CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| LN_ACCT_NBR | account_number | VARCHAR→STRING | Direct copy |
| BORR_ID | borrower_id | VARCHAR→BIGINT | FK lookup by external_id |
| BORR_FST_NM | *(dropped)* | — | Denormalized; use borrower FK |
| BORR_LST_NM | *(dropped)* | — | Denormalized; use borrower FK |
| BORR_SSN_LST4 | *(dropped)* | — | Denormalized; use borrower FK |
| PROD_CD | product_id | VARCHAR→BIGINT | FK lookup by code |
| LN_ORIG_AMT | original_amount | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| LN_CURR_BAL | current_balance | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| LN_INT_RT | interest_rate | VARCHAR→DECIMAL(5,3) | Parse string |
| LN_TERM_MOS | term_months | VARCHAR→INT | Parse string |
| LN_PMT_AMT | monthly_payment | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| LN_ORIG_DT | origination_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_MAT_DT | maturity_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_1ST_PMT_DT | first_payment_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_NXT_PMT_DT | next_payment_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_STAT_CD | status | VARCHAR→STRING | ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| LN_DLQ_DAYS | delinquency_days | VARCHAR→INT | Parse string |
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
| *(derived)* | origination_year | INT | Extracted from origination_date |

### CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| PMT_SEQ_NBR | legacy_payment_id | VARCHAR→STRING | Preserved for traceability |
| LN_ACCT_NBR | loan_account_id | VARCHAR→BIGINT | FK lookup by account_number |
| PMT_DT | payment_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| PMT_AMT | total_amount | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_PRIN_AMT | principal_amount | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_INT_AMT | interest_amount | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_ESCROW_AMT | escrow_amount | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_LATE_FEE | late_fee | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_TYP_CD | type | VARCHAR→STRING | REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| PMT_STAT_CD | status | VARCHAR→STRING | PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| PMT_RECV_DT | received_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| PMT_PROC_DT | processed_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| PMT_CRET_DT | created_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |
| PMT_UPDT_DT | updated_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |
| *(derived)* | payment_year | INT | Extracted from payment_date |
| *(derived)* | payment_month | INT | Extracted from payment_date |

---

## Transformation Decisions

### 1. Denormalization Removal

**Decision:** Drop redundant borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) from `loan_accounts` and replace with a `borrower_id` foreign key.

**Rationale:** The legacy `CDW_LN_ACCT` table embeds borrower data directly, creating data consistency risks. The modern schema normalizes this into a proper FK relationship, ensuring a single source of truth for borrower information.

### 2. Status Code Expansion

**Decision:** Expand all abbreviated status codes to human-readable strings.

| Context | Legacy | Modern |
|---------|--------|--------|
| Loan Status | ACT, CLO, DFT, FRB | ACTIVE, CLOSED, DEFAULT, FORBEARANCE |
| Borrower Status | ACT, INA | ACTIVE, INACTIVE |
| Payment Type | REG, EXT, PRT, PRE | REGULAR, EXTRA, PARTIAL, PREPAYMENT |
| Payment Status | PST, REV, NSF, PND | POSTED, REVERSED, NSF, PENDING |
| Property Type | SFR, CND, MFR, TWN | Single Family, Condominium, Multi-Family, Townhouse |
| Product Status | ACT, INA | true, false (BOOLEAN) |

**Rationale:** Readable values improve query clarity and reduce the need for lookup documentation. The product status is converted to boolean since it represents a simple active/inactive flag.

### 3. ID Strategy

**Decision:** Use auto-generated BIGINT identity columns for primary keys. Legacy string IDs are preserved in `external_id` or `legacy_*_id` columns for traceability.

**Rationale:** BIGINT PKs are more storage-efficient, join-friendly, and align with modern data warehouse patterns. Legacy IDs are preserved for audit/lineage.

### 4. Date/Timestamp Handling

**Decision:** Parse all `MM/DD/YYYY` strings using Spark's `to_date`/`to_timestamp` with explicit format. Audit dates (`created_at`, `updated_at`) become TIMESTAMP (midnight). Business dates (`origination_date`, `payment_date`) become DATE.

**Rationale:** DATE is appropriate for business events (no time component), while TIMESTAMP preserves the option for future time-of-day tracking on audit fields.

### 5. Amount Parsing

**Decision:** Strip commas from formatted strings (e.g., "285,000") before casting to DECIMAL. Use appropriate precision: DECIMAL(12,2) for large amounts (loan balances), DECIMAL(10,2) for payments, DECIMAL(5,3) for rates.

**Rationale:** Comma-formatted strings are common in legacy DW exports. The precision choices accommodate realistic loan amounts (up to $9.99 billion) while keeping storage efficient.

### 6. Error Handling Strategy

**Decision:** Never silently drop records. Malformed values produce NULL in the target column with an error message logged. Records with any parse errors are quarantined in `_quarantine_*` tables for review.

**Rationale:** Data loss is unacceptable in financial systems. Quarantining ensures no records are silently lost while allowing the main pipeline to proceed.

### 7. Lineage Tracking

**Decision:** Each target table includes `_migration_source` (source table name) and `_migrated_at` (timestamp) columns.

**Rationale:** Enables audit trail and helps identify which records came from which migration run.

---

## Type Conversion Details

| Source Pattern | Target Type | Conversion Method |
|----------------|-------------|-------------------|
| `MM/DD/YYYY` string | DATE | `to_date(col, "MM/dd/yyyy")` |
| `MM/DD/YYYY` string | TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| Comma-formatted number (`"285,000"`) | DECIMAL(p,s) | `regexp_replace(col, ",", "").cast(DecimalType(p,s))` |
| Plain numeric string (`"745"`) | INT | `col.cast(IntegerType())` |
| Rate string (`"5.250"`) | DECIMAL(5,3) | `col.cast(DecimalType(5,3))` |
| Status code (`"ACT"`) | STRING/BOOLEAN | Map lookup via `create_map` |

---

## Partitioning Strategy

| Table | Partition Columns | Rationale |
|-------|-------------------|-----------|
| `borrowers` | `state` | Geographic queries are common (compliance, marketing) |
| `loan_products` | *(none)* | Small reference table (~10-100 rows) |
| `loan_accounts` | `status`, `origination_year` | Most queries filter by active/closed status; origination year enables time-based analysis |
| `payments` | `payment_year`, `payment_month` | Time-series data naturally queried by period |

**Delta Lake optimizations enabled:**
- `autoOptimize.optimizeWrite`: Coalesces small files during write
- `autoOptimize.autoCompact`: Triggers compaction after writes

---

## Execution Order

The pipeline must run in this order due to FK dependencies:

```
Step 1: borrowers        (no dependencies)
Step 2: loan_products    (no dependencies)
         ↓ (Steps 1 & 2 can run in parallel)
Step 3: loan_accounts    (depends on borrowers + loan_products)
         ↓
Step 4: payments         (depends on loan_accounts)
         ↓
Step 5: quality checks   (depends on all tables)
```

### Databricks Workflow Configuration

```json
{
  "name": "loan_warehouse_migration",
  "tasks": [
    {
      "task_key": "ingest_borrowers",
      "notebook_task": {"notebook_path": "/Repos/migration/databricks/ingestion/ingest_borrowers"}
    },
    {
      "task_key": "ingest_loan_products",
      "notebook_task": {"notebook_path": "/Repos/migration/databricks/ingestion/ingest_loan_products"}
    },
    {
      "task_key": "ingest_loan_accounts",
      "depends_on": [{"task_key": "ingest_borrowers"}, {"task_key": "ingest_loan_products"}],
      "notebook_task": {"notebook_path": "/Repos/migration/databricks/ingestion/ingest_loan_accounts"}
    },
    {
      "task_key": "ingest_payments",
      "depends_on": [{"task_key": "ingest_loan_accounts"}],
      "notebook_task": {"notebook_path": "/Repos/migration/databricks/ingestion/ingest_payments"}
    },
    {
      "task_key": "quality_checks",
      "depends_on": [{"task_key": "ingest_payments"}],
      "notebook_task": {"notebook_path": "/Repos/migration/databricks/quality/runner"}
    }
  ]
}
```

---

## Pre-Migration Checklist

- [ ] Export legacy CDW tables to CSV/Parquet in the expected directory structure:
  ```
  /mnt/legacy-export/
  ├── CDW_BORR_MSTR/
  ├── CDW_LN_PROD/
  ├── CDW_LN_ACCT/
  └── CDW_PMT_HIST/
  ```
- [ ] Create the `loan_warehouse` database: `CREATE DATABASE IF NOT EXISTS loan_warehouse`
- [ ] Verify Databricks cluster has Delta Lake extensions enabled
- [ ] Confirm access to source and target storage locations
- [ ] Run DDL scripts in order: `01_borrowers.sql`, `02_loan_products.sql`, `03_loan_accounts.sql`, `04_payments.sql`
- [ ] Validate sample source files have expected headers matching legacy column names

---

## Running the Pipeline

### Option A: Full Pipeline (Recommended)

```bash
spark-submit --packages io.delta:delta-core_2.12:2.4.0 \
  databricks/ingestion/run_pipeline.py \
  /mnt/legacy-export/ \
  csv
```

### Option B: Individual Table Ingestion

```bash
# Step 1 & 2 (parallel)
spark-submit databricks/ingestion/ingest_borrowers.py /mnt/legacy-export/CDW_BORR_MSTR/ csv
spark-submit databricks/ingestion/ingest_loan_products.py /mnt/legacy-export/CDW_LN_PROD/ csv

# Step 3
spark-submit databricks/ingestion/ingest_loan_accounts.py /mnt/legacy-export/CDW_LN_ACCT/ csv

# Step 4
spark-submit databricks/ingestion/ingest_payments.py /mnt/legacy-export/CDW_PMT_HIST/ csv
```

### Option C: Databricks Notebook

Import the scripts as notebooks and configure a Databricks Workflow with the task DAG shown above.

---

## Post-Migration Validation

After the pipeline completes:

1. **Run quality checks:**
   ```bash
   spark-submit databricks/quality/runner.py /mnt/legacy-export/ csv /dbfs/reports/DATA_QUALITY_REPORT.md
   ```

2. **Review the quality report** at `/dbfs/reports/DATA_QUALITY_REPORT.md`

3. **Check quarantine tables** for any records that failed parsing:
   ```sql
   SELECT COUNT(*) FROM loan_warehouse._quarantine_borrowers;
   SELECT COUNT(*) FROM loan_warehouse._quarantine_loan_accounts;
   SELECT COUNT(*) FROM loan_warehouse._quarantine_payments;
   ```

4. **Verify row counts match:**
   ```sql
   SELECT 'borrowers' as tbl, COUNT(*) as cnt FROM loan_warehouse.borrowers
   UNION ALL
   SELECT 'loan_products', COUNT(*) FROM loan_warehouse.loan_products
   UNION ALL
   SELECT 'loan_accounts', COUNT(*) FROM loan_warehouse.loan_accounts
   UNION ALL
   SELECT 'payments', COUNT(*) FROM loan_warehouse.payments;
   ```

5. **Spot-check sample records** to confirm transformations applied correctly:
   ```sql
   SELECT external_id, first_name, last_name, credit_score, annual_income, status
   FROM loan_warehouse.borrowers
   LIMIT 5;
   ```

---

## Rollback Procedure

Delta Lake supports time travel, enabling easy rollback:

```sql
-- View table history
DESCRIBE HISTORY loan_warehouse.borrowers;

-- Restore to previous version
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.loan_products TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.payments TO VERSION AS OF 0;
```

For a full rollback, drop all tables:
```sql
DROP TABLE IF EXISTS loan_warehouse.payments;
DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
DROP TABLE IF EXISTS loan_warehouse.loan_products;
DROP TABLE IF EXISTS loan_warehouse.borrowers;
DROP TABLE IF EXISTS loan_warehouse._quarantine_borrowers;
DROP TABLE IF EXISTS loan_warehouse._quarantine_loan_products;
DROP TABLE IF EXISTS loan_warehouse._quarantine_loan_accounts;
DROP TABLE IF EXISTS loan_warehouse._quarantine_payments;
```

---

## Troubleshooting

| Issue | Cause | Resolution |
|-------|-------|------------|
| "Table not found" during loan_accounts ingestion | borrowers/loan_products not loaded yet | Run steps in correct dependency order |
| High quarantine rate (>5%) | Source data quality issues | Inspect quarantine tables; may need source-level fixes |
| Date parse failures | Unexpected date formats in source | Check for formats other than MM/DD/YYYY; update `to_date` format |
| FK resolution failures (NULL borrower_id) | BORR_ID in CDW_LN_ACCT not found in CDW_BORR_MSTR | Verify source data completeness; check for truncated exports |
| Amount parse failures | Non-numeric characters beyond commas | Check for currency symbols ($), spaces, or other formatting |
| OOM on large datasets | Insufficient cluster resources | Increase driver/executor memory; consider processing in partitions |

---

*Last updated: Generated by migration pipeline tooling*
