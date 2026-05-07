# Databricks Migration Runbook

## CDW Legacy-to-Modern Data Migration

This runbook documents the complete migration pipeline from the legacy CDW (Corporate Data Warehouse) schema to a modern Delta Lake schema on Databricks. It covers transformation decisions, column mappings, type conversions, partitioning strategy, and execution order.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Execution Order](#execution-order)
4. [Column Mappings](#column-mappings)
5. [Type Conversion Decisions](#type-conversion-decisions)
6. [Status Code Expansions](#status-code-expansions)
7. [Partitioning Strategy](#partitioning-strategy)
8. [Data Quality Framework](#data-quality-framework)
9. [Error Handling](#error-handling)
10. [Operational Procedures](#operational-procedures)

---

## Overview

### Source System
- **System:** CDW (Corporate Data Warehouse)
- **Database:** H2 (legacy application), extracted as CSV/Parquet files
- **Characteristics:**
  - All columns are VARCHAR (loose typing)
  - Cryptic abbreviated column names
  - Denormalized structure (borrower data duplicated in loan accounts)
  - No foreign key constraints
  - Date strings stored as `MM/DD/YYYY`
  - Amounts stored as strings with commas (e.g., `"285,000"`)
  - Status codes abbreviated (ACT, CLO, DFT, FRB)

### Target System
- **Platform:** Databricks (Unity Catalog)
- **Storage:** Delta Lake
- **Catalog:** `loan_warehouse`
- **Characteristics:**
  - Proper Spark SQL types (DATE, DECIMAL, INT, BOOLEAN, TIMESTAMP)
  - Meaningful, readable column names
  - Normalized structure with referential integrity
  - Delta Lake constraints for data quality
  - Partitioning for query performance

### Source Tables

| Legacy Table | Records | Target Table | Description |
|-------------|---------|-------------|-------------|
| `CDW_BORR_MSTR` | 5 | `loan_warehouse.borrowers` | Borrower dimension |
| `CDW_LN_PROD` | 5 | `loan_warehouse.loan_products` | Product reference |
| `CDW_LN_ACCT` | 5 | `loan_warehouse.loan_accounts` | Loan accounts fact |
| `CDW_PMT_HIST` | 10 | `loan_warehouse.payments` | Payment history fact |

---

## Architecture

```
+-------------------+     +--------------------+     +-------------------+
|   Legacy CDW      |     |   PySpark ETL      |     |   Delta Lake      |
|   (CSV/Parquet)   | --> |   Ingestion        | --> |   Tables          |
|                   |     |   Pipeline         |     |                   |
+-------------------+     +--------------------+     +-------------------+
                                    |
                                    v
                          +--------------------+
                          |   Data Quality     |
                          |   Framework        |
                          +--------------------+
                                    |
                                    v
                          +--------------------+
                          |   Quality Report   |
                          |   (Markdown)       |
                          +--------------------+
```

### Pipeline Components

| Component | Path | Purpose |
|-----------|------|---------|
| DDL Scripts | `databricks/ddl/` | Delta Lake CREATE TABLE statements |
| Ingestion Scripts | `databricks/ingestion/` | PySpark ETL for each table |
| Quality Framework | `databricks/quality/` | Post-ingestion validation |
| This Runbook | `docs/DATABRICKS_MIGRATION_RUNBOOK.md` | Documentation |

---

## Execution Order

The migration must be executed in dependency order. Tables with foreign key relationships must be loaded after their parent tables.

### Step-by-Step Execution

```
Step 1: Create Database/Catalog
  └── CREATE DATABASE IF NOT EXISTS loan_warehouse

Step 2: Create Delta Lake Tables (DDL)
  ├── 01_borrowers.sql        (no dependencies)
  ├── 02_loan_products.sql    (no dependencies)
  ├── 03_loan_accounts.sql    (depends on borrowers, loan_products)
  └── 04_payments.sql         (depends on loan_accounts)

Step 3: Run Ingestion Pipeline
  ├── ingest_borrowers.py     (first - no dependencies)
  ├── ingest_loan_products.py (first - no dependencies)
  ├── ingest_loan_accounts.py (second - after borrowers & products)
  └── ingest_payments.py      (third - after loan_accounts)

Step 4: Run Data Quality Checks
  └── run_quality_checks.py   (after all ingestion complete)
```

### Databricks Job Configuration

```json
{
  "name": "CDW_Legacy_Migration",
  "tasks": [
    {
      "task_key": "create_tables",
      "notebook_task": {
        "notebook_path": "/Repos/migration/databricks/ddl/run_all_ddl"
      }
    },
    {
      "task_key": "ingest_borrowers",
      "depends_on": [{"task_key": "create_tables"}],
      "notebook_task": {
        "notebook_path": "/Repos/migration/databricks/ingestion/ingest_borrowers"
      }
    },
    {
      "task_key": "ingest_loan_products",
      "depends_on": [{"task_key": "create_tables"}],
      "notebook_task": {
        "notebook_path": "/Repos/migration/databricks/ingestion/ingest_loan_products"
      }
    },
    {
      "task_key": "ingest_loan_accounts",
      "depends_on": [{"task_key": "ingest_borrowers"}, {"task_key": "ingest_loan_products"}],
      "notebook_task": {
        "notebook_path": "/Repos/migration/databricks/ingestion/ingest_loan_accounts"
      }
    },
    {
      "task_key": "ingest_payments",
      "depends_on": [{"task_key": "ingest_loan_accounts"}],
      "notebook_task": {
        "notebook_path": "/Repos/migration/databricks/ingestion/ingest_payments"
      }
    },
    {
      "task_key": "quality_checks",
      "depends_on": [{"task_key": "ingest_payments"}],
      "notebook_task": {
        "notebook_path": "/Repos/migration/databricks/quality/run_quality_checks"
      }
    }
  ]
}
```

---

## Column Mappings

### CDW_BORR_MSTR -> loan_warehouse.borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `BORR_ID` | `external_id` | VARCHAR(20) -> STRING | Direct copy |
| `BORR_FST_NM` | `first_name` | VARCHAR(50) -> STRING | Direct copy |
| `BORR_LST_NM` | `last_name` | VARCHAR(50) -> STRING | Direct copy |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR(1) -> STRING | Direct copy |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR(100) -> STRING | Direct copy |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR(10) -> DATE | Parse `MM/DD/YYYY` |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR(100) -> STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR(100) -> STRING | Direct copy |
| `BORR_CTY_NM` | `city` | VARCHAR(50) -> STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR(2) -> STRING | Direct copy |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR(10) -> STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR(15) -> STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR(100) -> STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR(5) -> INT | Parse string to integer |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR(20) -> STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR(15) -> DECIMAL(12,2) | Remove commas, parse |
| `BORR_CRET_DT` | `created_at` | VARCHAR(10) -> TIMESTAMP | Parse `MM/DD/YYYY` |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR(10) -> TIMESTAMP | Parse `MM/DD/YYYY` |
| `BORR_STAT_CD` | `status` | VARCHAR(5) -> STRING | Expand code |
| `BORR_REC_TYP` | *(dropped)* | — | Not needed in modern schema |

### CDW_LN_PROD -> loan_warehouse.loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PROD_CD` | `code` | VARCHAR(10) -> STRING | Direct copy |
| `PROD_DESC_TXT` | `name` | VARCHAR(200) -> STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR(5) -> STRING | Direct copy |
| `PROD_TERM_MOS` | `term_months` | VARCHAR(5) -> INT | Parse string |
| `PROD_RT_TYP` | `rate_type` | VARCHAR(10) -> STRING | Direct copy |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR(15) -> DECIMAL(12,2) | Remove commas, parse |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR(15) -> DECIMAL(12,2) | Remove commas, parse |
| `PROD_STAT_CD` | `is_active` | VARCHAR(5) -> BOOLEAN | ACT->true, INA->false |
| `PROD_EFF_DT` | `effective_date` | VARCHAR(10) -> DATE | Parse `MM/DD/YYYY` |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR(10) -> DATE | Parse `MM/DD/YYYY` |

### CDW_LN_ACCT -> loan_warehouse.loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `LN_ACCT_NBR` | `account_number` | VARCHAR(20) -> STRING | Direct copy |
| `BORR_ID` | `borrower_id` | VARCHAR(20) -> BIGINT | FK lookup via external_id |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_code` | VARCHAR(10) -> STRING | FK reference to products |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR(15) -> DECIMAL(12,2) | Remove commas, parse |
| `LN_CURR_BAL` | `current_balance` | VARCHAR(15) -> DECIMAL(12,2) | Remove commas, parse |
| `LN_INT_RT` | `interest_rate` | VARCHAR(8) -> DECIMAL(5,3) | Parse string |
| `LN_TERM_MOS` | `term_months` | VARCHAR(5) -> INT | Parse string |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR(15) -> DECIMAL(10,2) | Remove commas, parse |
| `LN_ORIG_DT` | `origination_date` | VARCHAR(10) -> DATE | Parse `MM/DD/YYYY` |
| `LN_MAT_DT` | `maturity_date` | VARCHAR(10) -> DATE | Parse `MM/DD/YYYY` |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR(10) -> DATE | Parse `MM/DD/YYYY` |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR(10) -> DATE | Parse `MM/DD/YYYY` |
| `LN_STAT_CD` | `status` | VARCHAR(5) -> STRING | Expand code |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR(5) -> INT | Parse string |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR(15) -> DECIMAL(10,2) | Remove commas, parse |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR(8) -> DECIMAL(5,2) | Parse string |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR(100) -> STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR(50) -> STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR(2) -> STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR(10) -> STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR(10) -> STRING | Expand code |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR(15) -> DECIMAL(12,2) | Remove commas, parse |
| `LN_CRET_DT` | `created_at` | VARCHAR(10) -> TIMESTAMP | Parse `MM/DD/YYYY` |
| `LN_UPDT_DT` | `updated_at` | VARCHAR(10) -> TIMESTAMP | Parse `MM/DD/YYYY` |

### CDW_PMT_HIST -> loan_warehouse.payments

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PMT_SEQ_NBR` | `legacy_sequence_id` | VARCHAR(20) -> STRING | Preserved for audit |
| `LN_ACCT_NBR` | `loan_account_number` | VARCHAR(20) -> STRING | FK to loan_accounts |
| `PMT_DT` | `payment_date` | VARCHAR(10) -> DATE | Parse `MM/DD/YYYY` |
| `PMT_AMT` | `total_amount` | VARCHAR(15) -> DECIMAL(10,2) | Remove commas, parse |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR(15) -> DECIMAL(10,2) | Remove commas, parse |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR(15) -> DECIMAL(10,2) | Remove commas, parse |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR(15) -> DECIMAL(10,2) | Remove commas, parse |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR(15) -> DECIMAL(10,2) | Remove commas, parse |
| `PMT_TYP_CD` | `type` | VARCHAR(5) -> STRING | Expand code |
| `PMT_STAT_CD` | `status` | VARCHAR(5) -> STRING | Expand code |
| `PMT_RECV_DT` | `received_date` | VARCHAR(10) -> DATE | Parse `MM/DD/YYYY` |
| `PMT_PROC_DT` | `processed_date` | VARCHAR(10) -> DATE | Parse `MM/DD/YYYY` |
| `PMT_CRET_DT` | `created_at` | VARCHAR(10) -> TIMESTAMP | Parse `MM/DD/YYYY` |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR(10) -> TIMESTAMP | Parse `MM/DD/YYYY` |

---

## Type Conversion Decisions

### Date Handling

| Decision | Rationale |
|----------|-----------|
| Use `to_date(col, "MM/dd/yyyy")` | Legacy format is consistently `MM/DD/YYYY` across all tables |
| NULL for empty/malformed dates | Preserves data; avoids silent data loss from coercion |
| TIMESTAMP for audit columns (`created_at`, `updated_at`) | Aligns with Delta Lake best practices for audit trails |
| DATE for business dates (`origination_date`, `payment_date`) | Business meaning is date-level, not timestamp-level |

### Amount/Decimal Handling

| Decision | Rationale |
|----------|-----------|
| Strip commas via `regexp_replace` before cast | Legacy stores "285,000" format consistently |
| `DECIMAL(12,2)` for large amounts (loan balances) | Supports up to $9,999,999,999.99 - sufficient for mortgage amounts |
| `DECIMAL(10,2)` for payment amounts | Payments are smaller; saves storage |
| `DECIMAL(5,3)` for interest rates | Supports rates up to 99.999% with 3 decimal places |
| `DECIMAL(5,2)` for percentages (LTV) | Standard percentage precision |
| NULL for empty/malformed amounts | Don't silently convert to zero |

### Integer Handling

| Decision | Rationale |
|----------|-----------|
| Direct string-to-INT cast after comma removal | Simple numeric strings in source |
| NULL for non-parseable values | Preserve data quality visibility |

### Boolean Conversion

| Decision | Rationale |
|----------|-----------|
| `PROD_STAT_CD` ACT -> true, INA -> false | Product active status is inherently boolean |
| NULL for unknown codes | Don't assume active or inactive |

---

## Status Code Expansions

### Loan Status (`LN_STAT_CD`)

| Code | Expanded Value | Description |
|------|---------------|-------------|
| `ACT` | `ACTIVE` | Loan is current and active |
| `CLO` | `CLOSED` | Loan has been paid off or closed |
| `DFT` | `DEFAULT` | Loan is in default |
| `FRB` | `FORBEARANCE` | Loan is in forbearance |

### Borrower Status (`BORR_STAT_CD`)

| Code | Expanded Value | Description |
|------|---------------|-------------|
| `ACT` | `ACTIVE` | Active borrower |
| `INA` | `INACTIVE` | Inactive borrower |

### Payment Type (`PMT_TYP_CD`)

| Code | Expanded Value | Description |
|------|---------------|-------------|
| `REG` | `REGULAR` | Regular scheduled payment |
| `EXT` | `EXTRA` | Extra/additional payment |
| `PRT` | `PARTIAL` | Partial payment |
| `PRE` | `PREPAYMENT` | Loan prepayment |

### Payment Status (`PMT_STAT_CD`)

| Code | Expanded Value | Description |
|------|---------------|-------------|
| `PST` | `POSTED` | Payment successfully posted |
| `REV` | `REVERSED` | Payment reversed |
| `NSF` | `NSF` | Non-Sufficient Funds (kept as-is, industry standard) |
| `PND` | `PENDING` | Payment pending processing |

### Property Type (`PROP_TYP_CD`)

| Code | Expanded Value | Description |
|------|---------------|-------------|
| `SFR` | `Single Family` | Single-family residence |
| `CND` | `Condominium` | Condominium unit |
| `MFR` | `Multi-Family` | Multi-family property |
| `TWN` | `Townhouse` | Townhouse |

### Unmapped Code Handling

Any status code not in the mapping dictionary is preserved with an `_UNMAPPED` suffix (e.g., `XYZ_UNMAPPED`). This ensures:
- No data is silently dropped
- Unmapped codes are easily discoverable via quality checks
- The data quality report flags these for investigation

---

## Partitioning Strategy

### Rationale

| Table | Partition Column(s) | Rationale |
|-------|-------------------|-----------|
| `borrowers` | `state` | Geographic queries are common in lending; even distribution across ~50 values |
| `loan_products` | *(none)* | Small reference table (<100 rows); partitioning would add overhead |
| `loan_accounts` | `status` | Most queries filter by active/closed status; 4 partitions |
| `payments` | `payment_year`, `payment_month` | Time-series queries on payment history; natural date-based partitioning |

### Delta Lake Optimization Settings

All tables include these properties:
- `delta.autoOptimize.optimizeWrite = true` - Automatically coalesces small files
- `delta.autoOptimize.autoCompact = true` - Background compaction of small files
- `delta.columnMapping.mode = name` - Enables column renaming/dropping without rewrite

### Generated Columns

| Table | Column | Expression | Purpose |
|-------|--------|-----------|---------|
| `loan_accounts` | `origination_year` | `year(origination_date)` | Enables year-based filtering without full date scan |
| `payments` | `payment_year` | `year(payment_date)` | Partition key for time-series partitioning |
| `payments` | `payment_month` | `month(payment_date)` | Sub-partition for monthly granularity |

---

## Data Quality Framework

### Check Categories

1. **Row Count Reconciliation** - Source count == Target count for each table
2. **Null Checks** - Required fields have no NULL values after transformation
3. **Referential Integrity** - FK relationships are valid (borrower exists, product exists, loan exists)
4. **Business Rules** - Domain-specific validations

### Business Rules Enforced

| Rule | Table | Logic |
|------|-------|-------|
| Active loans have positive balance | `loan_accounts` | `status='ACTIVE' => current_balance > 0` |
| Closed loans are settled | `loan_accounts` | `status='CLOSED' => balance=0 OR maturity_date < today` |
| Payment components sum correctly | `payments` | `principal + interest + escrow + late_fee ≈ total_amount` (±$0.02) |
| Credit scores in FICO range | `borrowers` | `credit_score BETWEEN 300 AND 850` |
| Loan statuses are valid expanded values | `loan_accounts` | `status IN ('ACTIVE','CLOSED','DEFAULT','FORBEARANCE')` |

### Running Quality Checks

```python
from databricks.quality.run_quality_checks import run_all_checks

results = run_all_checks(spark, {
    "base_source_path": "/mnt/legacy",
    "report_path": "/mnt/migration/DATA_QUALITY_REPORT.md"
})
```

---

## Error Handling

### Rejected Records

Records that fail validation are **never silently dropped**. Instead:

1. They are written to a separate `rejected/` path under the migration directory
2. Each rejected record includes a `_rejection_reason` column explaining why it was rejected
3. The ingestion metrics report includes rejected counts
4. The data quality report flags any non-zero rejection counts

### Rejection Path Structure

```
/mnt/migration/rejected/
├── borrowers/
├── loan_products/
├── loan_accounts/
└── payments/
```

### Parse Error Handling

| Scenario | Behavior |
|----------|----------|
| Empty string in date field | Converted to NULL (not rejected) |
| Malformed date (e.g., "13/32/2025") | Converted to NULL (logged) |
| Amount with non-numeric chars | Converted to NULL after comma/$ stripping |
| Unknown status code | Preserved with `_UNMAPPED` suffix |
| NULL in required field | Record rejected with reason |

### Pipeline Failure Handling

The orchestrator (`run_pipeline.py`) implements dependency-aware failure handling:
- If borrower ingestion fails, loan accounts and payments are **skipped** (not attempted)
- If loan accounts ingestion fails, payments are **skipped**
- Loan products and borrowers can run independently

---

## Operational Procedures

### Pre-Migration Checklist

- [ ] Verify source CSV/Parquet files are available at configured paths
- [ ] Confirm Delta Lake catalog `loan_warehouse` exists
- [ ] Validate cluster has sufficient resources (recommend 4+ workers for production)
- [ ] Ensure write permissions on target catalog and rejection paths
- [ ] Back up any existing target tables if running re-migration

### Execution

```bash
# Option 1: Run via Databricks Job (recommended)
# Configure and trigger the job defined in the Databricks Job Configuration section above

# Option 2: Run interactively in a notebook
%run /Repos/migration/databricks/ingestion/run_pipeline
```

### Post-Migration Verification

1. Review the `DATA_QUALITY_REPORT.md` generated by the quality framework
2. Verify row counts match between source and target
3. Spot-check specific records for data accuracy
4. Validate that downstream applications can query the new tables
5. Monitor Delta Lake table metrics (file count, size, partition balance)

### Rollback Procedure

Delta Lake supports time travel, enabling easy rollback:

```sql
-- View table history
DESCRIBE HISTORY loan_warehouse.borrowers;

-- Rollback to before migration
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.loan_products TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.payments TO VERSION AS OF 0;
```

### Monitoring

Key metrics to track post-migration:
- Table row counts (should match source)
- Query performance on partitioned tables vs. legacy
- Delta Lake file compaction metrics
- Any `_UNMAPPED` status values appearing in data

---

## Configuration Reference

### Spark Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `migration.base_source_path` | `/mnt/legacy` | Base path for legacy source files |
| `migration.base_rejected_path` | `/mnt/migration/rejected` | Path for rejected records |
| `migration.write_mode` | `overwrite` | Write mode (overwrite or append) |
| `migration.borrowers.source_path` | `{base}/cdw_borr_mstr/` | Borrower source path |
| `migration.loan_products.source_path` | `{base}/cdw_ln_prod/` | Loan products source path |
| `migration.loan_accounts.source_path` | `{base}/cdw_ln_acct/` | Loan accounts source path |
| `migration.payments.source_path` | `{base}/cdw_pmt_hist/` | Payments source path |
| `migration.quality_report_path` | `/mnt/migration/DATA_QUALITY_REPORT.md` | Quality report output path |

### Migration Metadata Columns

All target tables include metadata columns for audit:
- `_migration_source` - Name of the source CDW table
- `_migrated_at` - Timestamp when the record was migrated

---

*Last updated: 2026-05-07*
