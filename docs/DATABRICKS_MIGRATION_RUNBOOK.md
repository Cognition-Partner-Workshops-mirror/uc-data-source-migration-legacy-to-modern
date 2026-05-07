# Databricks Migration Runbook

## Legacy CDW → Modern Loan Warehouse (Delta Lake)

**Version:** 1.0
**Last Updated:** 2026-05-07
**Pipeline Location:** `databricks/`

---

## 1. Overview

This runbook documents the complete migration pipeline from the legacy Corporate Data Warehouse (CDW) tables to a modern, normalized Delta Lake schema on Databricks. The legacy system stores all data as VARCHAR strings with cryptic abbreviated column names, denormalized structures, and no foreign key constraints. The modern target uses proper Spark SQL types, meaningful names, and referential integrity.

### Source Tables (Legacy CDW)

| Legacy Table | Description | Row Estimate |
|-------------|-------------|-------------|
| `CDW_BORR_MSTR` | Borrower master records | ~5 (seed), scales to millions |
| `CDW_LN_PROD` | Loan product catalog | ~5 (seed), typically < 100 |
| `CDW_LN_ACCT` | Loan accounts (denormalized with borrower data) | ~5 (seed), scales to millions |
| `CDW_PMT_HIST` | Payment history | ~10 (seed), scales to hundreds of millions |

### Target Tables (Modern Delta Lake)

| Target Table | Schema | Partitioning |
|-------------|--------|-------------|
| `loan_warehouse.borrowers` | Normalized borrower dimension | `state` |
| `loan_warehouse.loan_products` | Product reference/dimension | None (small table) |
| `loan_warehouse.loan_accounts` | Loan fact table with FKs | `origination_year` |
| `loan_warehouse.payments` | Payment fact table with FKs | `payment_year`, `payment_month` |

---

## 2. Column Mapping Reference

### 2.1 CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `BORR_ID` | `external_id` | VARCHAR → STRING | Direct copy; used for FK lookups |
| `BORR_FST_NM` | `first_name` | VARCHAR → STRING | Direct copy |
| `BORR_LST_NM` | `last_name` | VARCHAR → STRING | Direct copy |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR → STRING | Direct copy; nullable |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR → STRING | Direct copy; recommend re-encryption |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR(MM/DD/YYYY) → DATE | `to_date(col, 'MM/dd/yyyy')` |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR → STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR → STRING | Direct copy; nullable |
| `BORR_CTY_NM` | `city` | VARCHAR → STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR → STRING | Direct copy; used as partition key |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR → STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR → STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR → STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR → INT | `cast(col as INT)` |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR → STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR → DECIMAL(12,2) | Remove commas, then cast |
| `BORR_CRET_DT` | `created_at` | VARCHAR(MM/DD/YYYY) → TIMESTAMP | `to_timestamp(col, 'MM/dd/yyyy')` |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR(MM/DD/YYYY) → TIMESTAMP | `to_timestamp(col, 'MM/dd/yyyy')` |
| `BORR_STAT_CD` | `status` | VARCHAR → STRING | ACT→Active, INA→Inactive |
| `BORR_REC_TYP` | *(dropped)* | — | Not needed in modern schema |

### 2.2 CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `PROD_CD` | `code` | VARCHAR → STRING | Direct copy; unique key |
| `PROD_DESC_TXT` | `name` | VARCHAR → STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR → STRING | Direct copy (FXD, ARM, FHA, VA) |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | `cast(col as INT)` |
| `PROD_RT_TYP` | `rate_type` | VARCHAR → STRING | Direct copy (FIXED, VARIABLE) |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, then cast |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, then cast |
| `PROD_STAT_CD` | `is_active` | VARCHAR → BOOLEAN | ACT→true, INA→false |
| `PROD_EFF_DT` | `effective_date` | VARCHAR(MM/DD/YYYY) → DATE | `to_date(col, 'MM/dd/yyyy')` |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR(MM/DD/YYYY) → DATE | `to_date(col, 'MM/dd/yyyy')` |

### 2.3 CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `LN_ACCT_NBR` | `account_number` | VARCHAR → STRING | Direct copy; unique key |
| `BORR_ID` | `borrower_id` | VARCHAR → BIGINT | FK lookup via `borrowers.external_id` |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_id` | VARCHAR → BIGINT | FK lookup via `loan_products.code` |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, then cast |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) | Remove commas, then cast |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | `cast(col as DECIMAL(5,3))` |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | `cast(col as INT)` |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) | Remove commas, then cast |
| `LN_ORIG_DT` | `origination_date` | VARCHAR(MM/DD/YYYY) → DATE | `to_date(col, 'MM/dd/yyyy')` |
| `LN_MAT_DT` | `maturity_date` | VARCHAR(MM/DD/YYYY) → DATE | `to_date(col, 'MM/dd/yyyy')` |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR(MM/DD/YYYY) → DATE | `to_date(col, 'MM/dd/yyyy')` |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR(MM/DD/YYYY) → DATE | `to_date(col, 'MM/dd/yyyy')` |
| `LN_STAT_CD` | `status` | VARCHAR → STRING | ACT→Active, CLO→Closed, DFT→Default, FRB→Forbearance |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | `cast(col as INT)` |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Remove commas, then cast |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | `cast(col as DECIMAL(5,2))` |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR → STRING | SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Remove commas, then cast |
| `LN_CRET_DT` | `created_at` | VARCHAR(MM/DD/YYYY) → TIMESTAMP | `to_timestamp(col, 'MM/dd/yyyy')` |
| `LN_UPDT_DT` | `updated_at` | VARCHAR(MM/DD/YYYY) → TIMESTAMP | `to_timestamp(col, 'MM/dd/yyyy')` |

### 2.4 CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `PMT_SEQ_NBR` | `legacy_sequence_id` | VARCHAR → STRING | Preserved for audit trail |
| `LN_ACCT_NBR` | `loan_account_id` | VARCHAR → BIGINT | FK lookup via `loan_accounts.account_number` |
| `PMT_DT` | `payment_date` | VARCHAR(MM/DD/YYYY) → DATE | `to_date(col, 'MM/dd/yyyy')` |
| `PMT_AMT` | `total_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, then cast |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, then cast |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, then cast |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, then cast |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR → DECIMAL(10,2) | Remove commas, then cast |
| `PMT_TYP_CD` | `type` | VARCHAR → STRING | REG→Regular, EXT→Extra, PRT→Partial, PRE→Prepayment |
| `PMT_STAT_CD` | `status` | VARCHAR → STRING | PST→Posted, REV→Reversed, NSF→NSF, PND→Pending |
| `PMT_RECV_DT` | `received_date` | VARCHAR(MM/DD/YYYY) → DATE | `to_date(col, 'MM/dd/yyyy')` |
| `PMT_PROC_DT` | `processed_date` | VARCHAR(MM/DD/YYYY) → DATE | `to_date(col, 'MM/dd/yyyy')` |
| `PMT_CRET_DT` | `created_at` | VARCHAR(MM/DD/YYYY) → TIMESTAMP | `to_timestamp(col, 'MM/dd/yyyy')` |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR(MM/DD/YYYY) → TIMESTAMP | `to_timestamp(col, 'MM/dd/yyyy')` |

---

## 3. Transformation Decisions

### 3.1 Date Parsing

All legacy dates are stored as `MM/DD/YYYY` VARCHAR strings. We use Spark's native `to_date()` and `to_timestamp()` functions with the format pattern `MM/dd/yyyy`:

```python
F.to_date(F.col("BORR_DOB_DT"), "MM/dd/yyyy")     # → DateType
F.to_timestamp(F.col("BORR_CRET_DT"), "MM/dd/yyyy") # → TimestampType
```

**Decision:** Audit/tracking columns (`created_at`, `updated_at`) are converted to `TIMESTAMP` (midnight of the given date) since the legacy system only stored the date portion. The modern schema uses `TIMESTAMP` for these fields to support future sub-day precision.

### 3.2 Amount Parsing

Legacy amounts contain comma-formatted strings (e.g., `"285,000"`, `"1,487.02"`). We strip commas then cast:

```python
F.regexp_replace(F.col("LN_ORIG_AMT"), ",", "").cast(DecimalType(12, 2))
```

**Precision choices:**
- `DECIMAL(12,2)` for large amounts (loan balances, original amounts, appraised values) — supports up to $9,999,999,999.99
- `DECIMAL(10,2)` for payment amounts and escrow balances — supports up to $99,999,999.99
- `DECIMAL(5,3)` for interest rates — supports up to 99.999%
- `DECIMAL(5,2)` for LTV percent — supports up to 999.99%

### 3.3 Status Code Expansion

Legacy tables use 3-character abbreviations. We expand them to human-readable values:

| Domain | Code | Expanded Value |
|--------|------|---------------|
| Loan Status | `ACT` | Active |
| Loan Status | `CLO` | Closed |
| Loan Status | `DFT` | Default |
| Loan Status | `FRB` | Forbearance |
| Borrower Status | `ACT` | Active |
| Borrower Status | `INA` | Inactive |
| Payment Type | `REG` | Regular |
| Payment Type | `EXT` | Extra |
| Payment Type | `PRT` | Partial |
| Payment Type | `PRE` | Prepayment |
| Payment Status | `PST` | Posted |
| Payment Status | `REV` | Reversed |
| Payment Status | `NSF` | NSF |
| Payment Status | `PND` | Pending |
| Property Type | `SFR` | Single Family |
| Property Type | `CND` | Condominium |
| Property Type | `MFR` | Multi-Family |
| Property Type | `TWN` | Townhouse |
| Product Status | `ACT` | true (boolean) |
| Product Status | `INA` | false (boolean) |

**Decision:** Unknown codes are preserved as `UNKNOWN:<original_code>` rather than silently dropped, ensuring no data loss and enabling downstream investigation.

### 3.4 Denormalization Removal

The legacy `CDW_LN_ACCT` table contains embedded borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`). In the modern schema these are dropped because:

1. They are redundant with `CDW_BORR_MSTR` (the authoritative source)
2. The modern `loan_accounts` table references `borrowers` via `borrower_id` (FK)
3. This eliminates update anomalies where borrower name changes would need to propagate to loan records

**Decision:** During migration, we resolve `BORR_ID` to the modern `borrower_id` via a join to the already-migrated `borrowers` table. Unresolved references are quarantined with a logged warning.

### 3.5 Foreign Key Resolution

Legacy tables use string-based IDs (`BORR_ID = 'B-10001'`, `PROD_CD = 'FXD30'`). The modern schema uses `BIGINT` auto-generated IDs. Resolution is performed via left joins:

```
CDW_LN_ACCT.BORR_ID  → borrowers.external_id   → borrowers.borrower_id
CDW_LN_ACCT.PROD_CD  → loan_products.code       → loan_products.product_id
CDW_PMT_HIST.LN_ACCT_NBR → loan_accounts.account_number → loan_accounts.loan_account_id
```

Rows with unresolved FKs are quarantined rather than silently dropped.

### 3.6 Null and Malformed Data Handling

- **Null values in required fields:** Rows are quarantined to `_quarantine_<table>` tables with a `_quarantine_reason` column explaining which fields were null.
- **Malformed dates:** Spark's `to_date()` returns NULL for unparseable strings; these are caught by null checks.
- **Malformed amounts:** `regexp_replace` + `cast` returns NULL for non-numeric strings; caught by null checks.
- **Duplicates:** Deduplication on natural keys (`external_id`, `account_number`, `code`) with latest `updated_at` winning.

**Decision:** We never silently drop records. Every source row either ends up in the target table or in the quarantine table with a reason.

---

## 4. Partitioning Rationale

### borrowers — Partitioned by `state`

- Borrower queries frequently filter by geographic region (state-level compliance, regional reporting)
- ~50 distinct values (US states + territories), providing good partition cardinality
- Enables partition pruning for state-specific regulatory queries

### loan_products — No partitioning

- Reference/dimension table with very few rows (typically < 100)
- Partitioning would create excessive small files with no query benefit

### loan_accounts — Partitioned by `origination_year`

- Loan vintage analysis is a primary analytics use case (cohort performance tracking)
- Provides manageable partition count (~10-30 years of data)
- Enables efficient time-range queries for annual reporting
- Computed column: `YEAR(origination_date)`

### payments — Partitioned by `payment_year`, `payment_month`

- Payment data is the highest-volume table (grows monthly)
- Monthly partitioning aligns with standard financial reporting cycles
- Enables efficient reconciliation queries that scan specific months
- Two-level partitioning (year + month) balances partition count vs. file size

---

## 5. Execution Order

The pipeline must be run in strict dependency order due to FK resolution:

```
Step 1: databricks/ddl/create_schema.sql        # Create the loan_warehouse schema
Step 2: databricks/ddl/borrowers.sql             # Create borrowers table (no deps)
Step 3: databricks/ddl/loan_products.sql         # Create loan_products table (no deps)
Step 4: databricks/ddl/loan_accounts.sql         # Create loan_accounts table (deps: borrowers, loan_products)
Step 5: databricks/ddl/payments.sql              # Create payments table (deps: loan_accounts)
Step 6: databricks/ingestion/ingest_borrowers.py       # Ingest borrower data
Step 7: databricks/ingestion/ingest_loan_products.py   # Ingest loan product data
Step 8: databricks/ingestion/ingest_loan_accounts.py   # Ingest loan accounts (needs steps 6, 7)
Step 9: databricks/ingestion/ingest_payments.py        # Ingest payments (needs step 8)
Step 10: databricks/quality/data_quality_checks.py     # Run quality validation
```

Steps 6 and 7 can run in parallel. Steps 2 and 3 can run in parallel.

Alternatively, use the orchestrator script:

```bash
spark-submit --py-files utils.py databricks/ingestion/run_full_migration.py
```

---

## 6. Databricks Cluster Configuration

### Recommended Cluster Specs

| Parameter | Development | Production |
|-----------|------------|------------|
| Runtime | DBR 14.x LTS | DBR 14.x LTS |
| Node Type | Standard_DS3_v2 (or equivalent) | Standard_DS4_v2 |
| Workers | 2-4 | 8-16 (auto-scale) |
| Driver | Same as worker | 1 size larger |
| Spark Config | Default | `spark.sql.shuffle.partitions=200` |

### Required Libraries

- PySpark (included in Databricks Runtime)
- No additional PyPI packages required — all transformations use native Spark functions

### Source Data Preparation

Before running the pipeline, extract legacy data to a cloud storage location accessible from Databricks:

```
/mnt/legacy-extracts/CDW_BORR_MSTR/    # CSV or Parquet
/mnt/legacy-extracts/CDW_LN_PROD/
/mnt/legacy-extracts/CDW_LN_ACCT/
/mnt/legacy-extracts/CDW_PMT_HIST/
```

To change the source format from CSV to Parquet, update the `SOURCE_FORMAT` constant in each ingestion script.

---

## 7. Migration Audit Trail

Each migrated table includes two audit columns:

| Column | Type | Purpose |
|--------|------|---------|
| `_migration_source` | STRING | Name of the source legacy table (e.g., `CDW_BORR_MSTR`) |
| `_migrated_at` | TIMESTAMP | Timestamp when the row was written to the target |

These columns enable:
- Tracing any target row back to its legacy source
- Identifying when data was migrated (useful for incremental runs)
- Filtering out migrated data from subsequent incremental loads

---

## 8. Data Quality Checks

After ingestion, run the data quality framework:

```bash
spark-submit databricks/quality/data_quality_checks.py
```

The framework validates:

1. **Row Count Reconciliation** — Source rows = Target rows + Quarantined rows
2. **Null Checks** — Required fields have no nulls in target tables
3. **Referential Integrity** — All FK references resolve to parent records
4. **Business Rules:**
   - Active loans have balance > 0
   - Closed loans have maturity_date populated
   - Original amounts > 0
   - Interest rates between 0-100%
   - LTV percent between 0-200%
   - Non-negative delinquency days
   - Origination date before maturity date
   - Valid status/type enum values
   - Credit scores between 300-850
   - Non-negative annual income
   - Positive payment amounts
   - Payment component sum ≈ total amount (within $0.02 tolerance)
   - Received date on or before processed date
   - Product min_amount ≤ max_amount
   - Positive product term_months

Output: `DATA_QUALITY_REPORT.md` at the configured path (default: `/dbfs/migration-reports/`).

---

## 9. Rollback Procedure

Delta Lake supports time travel, enabling easy rollback:

```sql
-- View table history
DESCRIBE HISTORY loan_warehouse.borrowers;

-- Rollback to a specific version
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF 0;

-- Or rollback to a timestamp
RESTORE TABLE loan_warehouse.loan_accounts TO TIMESTAMP AS OF '2026-05-01T00:00:00';
```

To completely reset the migration:

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

## 10. File Inventory

```
databricks/
├── ddl/
│   ├── create_schema.sql          # Schema creation (run first)
│   ├── borrowers.sql              # Borrower dimension table DDL
│   ├── loan_products.sql          # Loan product dimension table DDL
│   ├── loan_accounts.sql          # Loan account fact table DDL
│   └── payments.sql               # Payment fact table DDL
├── ingestion/
│   ├── utils.py                   # Shared parsing/mapping/logging utilities
│   ├── ingest_borrowers.py        # Borrower ingestion pipeline
│   ├── ingest_loan_products.py    # Loan product ingestion pipeline
│   ├── ingest_loan_accounts.py    # Loan account ingestion pipeline
│   ├── ingest_payments.py         # Payment ingestion pipeline
│   └── run_full_migration.py      # Orchestrator (runs all in order)
├── quality/
│   ├── __init__.py
│   └── data_quality_checks.py     # Post-migration quality framework
docs/
└── DATABRICKS_MIGRATION_RUNBOOK.md  # This document
```
