# Databricks Migration Runbook

## Overview

This runbook documents the migration of loan management data from the legacy Corporate Data Warehouse (CDW) schema to a modern Delta Lake schema on Databricks. The legacy system uses all-VARCHAR columns, cryptic abbreviated names, no foreign keys, and status code abbreviations. The modern target uses proper Spark SQL types, meaningful names, referential integrity, and partitioned Delta Lake tables.

---

## Source System Summary

| Legacy Table | Description | Record Count |
|-------------|-------------|-------------|
| `CDW_BORR_MSTR` | Borrower master records | 5 |
| `CDW_LN_PROD` | Loan product definitions | 5 |
| `CDW_LN_ACCT` | Loan accounts (denormalized) | 5 |
| `CDW_PMT_HIST` | Payment history | 10 |

### Legacy Schema Characteristics
- **All-VARCHAR columns**: Every field stored as string regardless of semantic type
- **Cryptic naming**: `BORR_FST_NM`, `LN_CURR_BAL`, `PMT_ESCROW_AMT`
- **No foreign keys**: Relationships implied but not enforced
- **String dates**: `MM/DD/YYYY` format stored as VARCHAR(10)
- **String amounts**: Comma-formatted numbers stored as VARCHAR(15) (e.g., "285,000")
- **Status abbreviations**: ACT, CLO, DFT, FRB, REG, PST, etc.
- **Denormalized structure**: Borrower data duplicated inside loan accounts

---

## Target Schema (Delta Lake)

| Target Table | Database | Partitioning | Description |
|-------------|----------|-------------|-------------|
| `loan_warehouse.borrowers` | loan_warehouse | `state` | Normalized borrower dimension |
| `loan_warehouse.loan_products` | loan_warehouse | None | Product reference table |
| `loan_warehouse.loan_accounts` | loan_warehouse | `status` | Loan accounts fact table |
| `loan_warehouse.payments` | loan_warehouse | `payment_year` | Payment history fact table |

---

## Column Mapping Reference

### CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `BORR_ID` | `external_id` | VARCHAR → STRING | Direct copy, unique constraint |
| `BORR_FST_NM` | `first_name` | VARCHAR → STRING | Direct copy |
| `BORR_LST_NM` | `last_name` | VARCHAR → STRING | Direct copy |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR → STRING | Direct copy, nullable |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR → STRING | Direct copy (re-encrypt recommended) |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR → STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR → STRING | Direct copy, nullable |
| `BORR_CTY_NM` | `city` | VARCHAR → STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR → STRING | Direct copy, partition key |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR → STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR → STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR → STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR → INT | Parse string to integer |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR → STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `BORR_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |
| `BORR_STAT_CD` | `status` | VARCHAR → STRING | ACT→Active, INA→Inactive |
| `BORR_REC_TYP` | *(dropped)* | — | Legacy-only field, not needed |

### CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `PROD_CD` | `code` | VARCHAR → STRING | Direct copy, unique constraint |
| `PROD_DESC_TXT` | `name` | VARCHAR → STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR → STRING | Direct copy (FXD, ARM, FHA, VA) |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | Parse string to integer |
| `PROD_RT_TYP` | `rate_type` | VARCHAR → STRING | Direct copy (FIXED, VARIABLE) |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `PROD_STAT_CD` | `is_active` | VARCHAR → BOOLEAN | ACT→true, INA→false |
| `PROD_EFF_DT` | `effective_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR → DATE | Parse MM/DD/YYYY |

### CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `LN_ACCT_NBR` | `account_number` | VARCHAR → STRING | Direct copy, unique constraint |
| `BORR_ID` | `borrower_id` | VARCHAR → BIGINT | FK lookup via borrowers.external_id |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized, use FK instead |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized, use FK instead |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized, use FK instead |
| `PROD_CD` | `product_id` | VARCHAR → BIGINT | FK lookup via loan_products.code |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | Parse string to decimal |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | Parse string to integer |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `LN_ORIG_DT` | `origination_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `LN_MAT_DT` | `maturity_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `LN_STAT_CD` | `status` | VARCHAR → STRING | ACT→Active, CLO→Closed, DFT→Default, FRB→Forbearance |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | Parse string to integer |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | Parse string to decimal |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR → STRING | SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |
| `LN_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |

### CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `PMT_SEQ_NBR` | `legacy_payment_id` | VARCHAR → STRING | Preserved for audit trail |
| `LN_ACCT_NBR` | `loan_account_id` | VARCHAR → BIGINT | FK lookup via loan_accounts.account_number |
| `PMT_DT` | `payment_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `PMT_AMT` | `total_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_TYP_CD` | `type` | VARCHAR → STRING | REG→Regular, EXT→Extra, PRT→Partial, PRE→Prepayment |
| `PMT_STAT_CD` | `status` | VARCHAR → STRING | PST→Posted, REV→Reversed, NSF→NSF, PND→Pending |
| `PMT_RECV_DT` | `received_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `PMT_PROC_DT` | `processed_date` | VARCHAR → DATE | Parse MM/DD/YYYY |
| `PMT_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse MM/DD/YYYY |

---

## Transformation Decisions

### 1. Date Parsing Strategy
- **Format**: All legacy dates are stored as `MM/DD/YYYY` VARCHAR strings
- **Target**: Converted to Spark `DateType` (DATE) or `TimestampType` (TIMESTAMP)
- **Function**: `to_date(col, "MM/dd/yyyy")` / `to_timestamp(col, "MM/dd/yyyy")`
- **Null handling**: If a date string cannot be parsed, it becomes NULL (logged, not dropped)
- **Rationale**: DATE for business dates (payment_date, origination_date); TIMESTAMP for audit fields (created_at, updated_at) to allow future time-of-day precision

### 2. Amount Parsing Strategy
- **Format**: Amounts stored with commas as thousands separators (e.g., "285,000", "1,487.02")
- **Target**: Converted to `DECIMAL(12,2)` or `DECIMAL(10,2)` depending on expected magnitude
- **Function**: `regexp_replace(col, ",", "").cast(DecimalType(x,y))`
- **Precision choices**:
  - `DECIMAL(12,2)`: For loan amounts, property values, annual income (up to $9,999,999,999.99)
  - `DECIMAL(10,2)`: For payment amounts, escrow balances (up to $99,999,999.99)
  - `DECIMAL(5,3)`: For interest rates (up to 99.999%)
  - `DECIMAL(5,2)`: For LTV percentage (up to 999.99%)

### 3. Status Code Expansion
- **Rationale**: Abbreviated codes are opaque to analysts and downstream consumers
- **Approach**: Expand to human-readable strings for self-documenting data
- **Mappings**:
  - Loan status: `ACT→Active`, `CLO→Closed`, `DFT→Default`, `FRB→Forbearance`
  - Payment type: `REG→Regular`, `EXT→Extra`, `PRT→Partial`, `PRE→Prepayment`
  - Payment status: `PST→Posted`, `REV→Reversed`, `NSF→NSF`, `PND→Pending`
  - Borrower status: `ACT→Active`, `INA→Inactive`
  - Product status: `ACT→true` (boolean), `INA→false`
  - Property type: `SFR→Single Family`, `CND→Condominium`, `MFR→Multi-Family`, `TWN→Townhouse`
- **Unknown codes**: Preserved as-is (not dropped) with a warning logged

### 4. Denormalization Removal
- **Problem**: `CDW_LN_ACCT` embeds borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) redundantly
- **Solution**: Drop denormalized fields from loan_accounts; use `borrower_id` FK to join borrowers table
- **Benefit**: Single source of truth for borrower data, no stale copies

### 5. Foreign Key Resolution
- **Legacy approach**: String-based implicit relationships (BORR_ID, PROD_CD, LN_ACCT_NBR)
- **Modern approach**: Surrogate BIGINT keys with explicit FK constraints
- **Resolution method**:
  - `CDW_LN_ACCT.BORR_ID` → Join on `borrowers.external_id` → get `borrowers.id`
  - `CDW_LN_ACCT.PROD_CD` → Join on `loan_products.code` → get `loan_products.id`
  - `CDW_PMT_HIST.LN_ACCT_NBR` → Join on `loan_accounts.account_number` → get `loan_accounts.id`
- **Unresolved references**: Logged as warnings (not dropped) for investigation

### 6. Partitioning Strategy
| Table | Partition Key | Rationale |
|-------|--------------|-----------|
| `borrowers` | `state` | Geographic queries common in loan servicing; low cardinality (50 states) |
| `loan_products` | None | Small reference table (~100 rows max), no benefit from partitioning |
| `loan_accounts` | `status` | Most queries filter by Active/Closed/Default; low cardinality (4 values) |
| `payments` | `payment_year` | Time-range queries dominant in reporting; keeps partition sizes manageable |

### 7. Delta Lake Table Properties
- `delta.autoOptimize.optimizeWrite = true`: Automatic file sizing for optimal read performance
- `delta.autoOptimize.autoCompact = true`: Background compaction of small files
- `delta.columnMapping.mode = name`: Enables column rename/drop without rewriting data
- Reader/Writer versions set to 2/5 for full feature support

---

## Execution Order

The pipeline must be executed in this specific order due to foreign key dependencies:

```
Step 1: Create Database
        └── CREATE DATABASE IF NOT EXISTS loan_warehouse

Step 2: Create Tables (DDL)
        ├── 01_borrowers.sql
        ├── 02_loan_products.sql
        ├── 03_loan_accounts.sql
        └── 04_payments.sql

Step 3: Ingest Borrowers (no dependencies)
        └── ingest_borrowers.py

Step 4: Ingest Loan Products (no dependencies)
        └── ingest_loan_products.py

Step 5: Ingest Loan Accounts (depends on Steps 3 + 4)
        └── ingest_loan_accounts.py
        └── Resolves: borrower_id, product_id

Step 6: Ingest Payments (depends on Step 5)
        └── ingest_payments.py
        └── Resolves: loan_account_id

Step 7: Data Quality Validation (depends on Steps 3-6)
        └── data_quality_checks.py
        └── Generates: DATA_QUALITY_REPORT.md
```

**Note**: Steps 3 and 4 can run in parallel since they have no mutual dependencies.

---

## Databricks Execution Instructions

### Option A: Databricks Notebooks

1. Upload all scripts to Databricks Workspace under `/Workspace/migrations/loan_cdw/`
2. Create a Databricks Workflow with tasks chained in dependency order
3. Configure cluster: Runtime 13.3 LTS+, Delta Lake enabled

### Option B: spark-submit

```bash
# From the databricks/ directory
spark-submit --master local[*] run_migration.py
```

### Option C: Databricks Jobs API

```json
{
  "name": "Legacy CDW to Delta Lake Migration",
  "tasks": [
    {"task_key": "create_ddl", "notebook_task": {"notebook_path": "/migrations/loan_cdw/ddl/create_all"}},
    {"task_key": "ingest_borrowers", "depends_on": [{"task_key": "create_ddl"}], "spark_python_task": {"python_file": "dbfs:/migrations/ingestion/ingest_borrowers.py"}},
    {"task_key": "ingest_products", "depends_on": [{"task_key": "create_ddl"}], "spark_python_task": {"python_file": "dbfs:/migrations/ingestion/ingest_loan_products.py"}},
    {"task_key": "ingest_accounts", "depends_on": [{"task_key": "ingest_borrowers"}, {"task_key": "ingest_products"}], "spark_python_task": {"python_file": "dbfs:/migrations/ingestion/ingest_loan_accounts.py"}},
    {"task_key": "ingest_payments", "depends_on": [{"task_key": "ingest_accounts"}], "spark_python_task": {"python_file": "dbfs:/migrations/ingestion/ingest_payments.py"}},
    {"task_key": "quality_checks", "depends_on": [{"task_key": "ingest_payments"}], "spark_python_task": {"python_file": "dbfs:/migrations/quality/data_quality_checks.py"}}
  ]
}
```

---

## Data Quality Checks

The quality framework validates four categories after ingestion:

### 1. Row Count Reconciliation
- Compares target table row counts against expected source counts
- Ensures no records silently dropped during transformation

### 2. Null Constraint Validation
- Verifies NOT NULL fields contain no null values
- Covers all required fields defined in the Delta Lake DDL

### 3. Referential Integrity
- `loan_accounts.borrower_id` → `borrowers.id` (no orphans)
- `loan_accounts.product_id` → `loan_products.id` (no orphans)
- `payments.loan_account_id` → `loan_accounts.id` (no orphans)

### 4. Business Rule Validation
- Active loans must have `current_balance > 0`
- Payment amounts must be positive
- Credit scores in range 300-850
- Interest rates in range 0-30%
- Delinquency days >= 0
- Origination date < maturity date
- Loan status values are valid expanded values

---

## Error Handling & Recovery

### Malformed Record Handling
- Records that fail parsing are **quarantined** (not dropped)
- Quarantine location: `/mnt/quarantine/{table_name}/`
- Quarantined records include the raw source data for investigation
- Pipeline continues processing valid records

### Unresolved Foreign Keys
- If a FK lookup fails (e.g., BORR_ID not found in borrowers), the record is **preserved with NULL FK**
- Warning logged with count of unresolved references
- Investigation required before promoting to production

### Rerunability
- All writes use `mode("overwrite")` — safe to rerun without duplicates
- For production: switch to Delta MERGE (upsert) for incremental loads

---

## Post-Migration Validation

After running the pipeline, verify:

1. **Row counts match** (check DATA_QUALITY_REPORT.md)
2. **Sample record comparison**: Manually verify 2-3 records end-to-end
3. **Amount accuracy**: Sum of all loan balances matches between source and target
4. **Date accuracy**: Spot-check date conversions (watch for month/day swap issues)
5. **FK integrity**: No orphan records in any child table

---

## Rollback Plan

If migration fails or produces incorrect data:

1. **Drop and recreate tables**: DDL scripts are idempotent
2. **Fix source data or transformation logic**
3. **Rerun pipeline**: Overwrite mode ensures clean state
4. **Check quarantine**: Review `/mnt/quarantine/` for patterns in failures

---

## Future Enhancements

1. **Incremental loads**: Switch from overwrite to Delta MERGE for ongoing CDC
2. **Schema evolution**: Use `delta.columnMapping.mode = name` for safe schema changes
3. **Data lineage**: Add source metadata columns (source_system, load_timestamp, batch_id)
4. **Streaming ingestion**: Convert batch scripts to Structured Streaming for near-real-time
5. **Unity Catalog**: Register tables in Unity Catalog for governance and access control
