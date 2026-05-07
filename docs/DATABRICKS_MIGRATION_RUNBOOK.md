# Databricks Migration Runbook

## Legacy CDW → Modern Delta Lake Loan Data Warehouse

---

## 1. Overview

This runbook documents the migration of the legacy CDW (Corporate Data Warehouse) loan management data into a modern Delta Lake schema on Databricks. The legacy system stores all data as VARCHAR strings with cryptic abbreviated column names, no foreign keys, and denormalized structures. The target is a properly typed, normalized, partitioned Delta Lake warehouse.

### Source System

| Table | Description | Rows (seed) |
|-------|-------------|-------------|
| `CDW_BORR_MSTR` | Borrower master | 5 |
| `CDW_LN_PROD` | Loan product definitions | 5 |
| `CDW_LN_ACCT` | Loan accounts (denormalized) | 5 |
| `CDW_PMT_HIST` | Payment history | 10 |

### Target System

| Table | Description | Partitioned By |
|-------|-------------|----------------|
| `loan_warehouse.borrowers` | Borrower dimension | `state` |
| `loan_warehouse.loan_products` | Product reference | *(none — small table)* |
| `loan_warehouse.loan_accounts` | Loan account facts | `status` |
| `loan_warehouse.payments` | Payment history facts | `payment_year`, `payment_month` |

---

## 2. Column Mapping Reference

### 2.1 CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `BORR_ID` | `external_id` | VARCHAR → STRING | Direct copy |
| `BORR_FST_NM` | `first_name` | VARCHAR → STRING | Direct copy |
| `BORR_LST_NM` | `last_name` | VARCHAR → STRING | Direct copy |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR → STRING | Direct copy |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR → STRING | Direct copy |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
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
| `BORR_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `BORR_STAT_CD` | `status` | VARCHAR → STRING | `ACT`→`Active`, `INA`→`Inactive` |
| `BORR_REC_TYP` | *(dropped)* | — | Not needed in modern schema |

### 2.2 CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PROD_CD` | `code` | VARCHAR → STRING | Direct copy |
| `PROD_DESC_TXT` | `name` | VARCHAR → STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR → STRING | Direct copy (FXD, ARM, FHA, VA) |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | Parse string to integer |
| `PROD_RT_TYP` | `rate_type` | VARCHAR → STRING | Direct copy (FIXED, VARIABLE) |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `PROD_STAT_CD` | `is_active` | VARCHAR → BOOLEAN | `ACT`→`true`, `INA`→`false` |
| `PROD_EFF_DT` | `effective_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |

### 2.3 CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `LN_ACCT_NBR` | `account_number` | VARCHAR → STRING | Direct copy |
| `BORR_ID` | `borrower_key` | VARCHAR → BIGINT | FK lookup via `borrowers.external_id` |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_key` | VARCHAR → BIGINT | FK lookup via `loan_products.code` |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | Parse string |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | Parse string |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `LN_ORIG_DT` | `origination_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_MAT_DT` | `maturity_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_STAT_CD` | `status` | VARCHAR → STRING | `ACT`→`Active`, `CLO`→`Closed`, `DFT`→`Default`, `FRB`→`Forbearance` |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | Parse string |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | Parse string |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR → STRING | `SFR`→`Single Family`, `CND`→`Condominium`, `MFR`→`Multi-Family`, `TWN`→`Townhouse` |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `LN_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |

### 2.4 CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PMT_SEQ_NBR` | `legacy_sequence_id` | VARCHAR → STRING | Preserved for traceability |
| `LN_ACCT_NBR` | `loan_account_key` | VARCHAR → BIGINT | FK lookup via `loan_accounts.account_number` |
| `PMT_DT` | `payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_AMT` | `total_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_TYP_CD` | `type` | VARCHAR → STRING | `REG`→`Regular`, `EXT`→`Extra`, `PRT`→`Partial`, `PRE`→`Prepayment` |
| `PMT_STAT_CD` | `status` | VARCHAR → STRING | `PST`→`Posted`, `REV`→`Reversed`, `NSF`→`NSF`, `PND`→`Pending` |
| `PMT_RECV_DT` | `received_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_PROC_DT` | `processed_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |

---

## 3. Transformation Decisions

### 3.1 Date Parsing

All legacy dates are stored as `MM/DD/YYYY` VARCHAR strings. The pipeline uses PySpark's `to_date` with format `"MM/dd/yyyy"`.

- **Created/updated timestamps** are parsed to `TIMESTAMP` (midnight of the given date) since the legacy system did not store time-of-day.
- **Business dates** (origination, maturity, payment) are parsed to `DATE`.
- **Malformed dates** result in `NULL` with a logged warning — records are never dropped.

### 3.2 Amount Parsing

Legacy amounts contain embedded commas (e.g., `"285,000"`, `"1,487.02"`). The pipeline:
1. Strips commas via `regexp_replace`
2. Casts to the appropriate `DECIMAL(precision, scale)`

Precision/scale choices:
- `DECIMAL(12,2)` for large amounts (loan balances, appraised values, income) — supports up to $9,999,999,999.99
- `DECIMAL(10,2)` for payment amounts — supports up to $99,999,999.99
- `DECIMAL(5,3)` for interest rates — supports up to 99.999%
- `DECIMAL(5,2)` for LTV percent — supports up to 999.99%

### 3.3 Status Code Expansion

Legacy codes are expanded to human-readable values to improve downstream analytics:

| Context | Legacy | Modern |
|---------|--------|--------|
| Borrower status | `ACT` | `Active` |
| Borrower status | `INA` | `Inactive` |
| Loan status | `ACT` | `Active` |
| Loan status | `CLO` | `Closed` |
| Loan status | `DFT` | `Default` |
| Loan status | `FRB` | `Forbearance` |
| Product status | `ACT` | `true` (boolean) |
| Product status | `INA` | `false` (boolean) |
| Payment type | `REG` | `Regular` |
| Payment type | `EXT` | `Extra` |
| Payment type | `PRT` | `Partial` |
| Payment type | `PRE` | `Prepayment` |
| Payment status | `PST` | `Posted` |
| Payment status | `REV` | `Reversed` |
| Payment status | `NSF` | `NSF` |
| Payment status | `PND` | `Pending` |
| Property type | `SFR` | `Single Family` |
| Property type | `CND` | `Condominium` |
| Property type | `MFR` | `Multi-Family` |
| Property type | `TWN` | `Townhouse` |

**Unknown codes** are preserved as `UNKNOWN:<original_code>` to prevent data loss and enable investigation.

### 3.4 Denormalization Removal

The legacy `CDW_LN_ACCT` table embeds borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) directly. In the modern schema:

- These columns are **dropped** from `loan_accounts`
- A `borrower_key` FK references the `borrowers` table
- The FK is resolved by joining `CDW_LN_ACCT.BORR_ID` to `borrowers.external_id`

This normalization eliminates data redundancy and ensures borrower updates propagate to all related loan accounts.

### 3.5 Foreign Key Resolution

Legacy tables use string-based IDs with no enforced relationships. The pipeline resolves FKs in order:

1. **borrowers** ingested first → `borrower_key` (IDENTITY) generated
2. **loan_products** ingested first → `product_key` (IDENTITY) generated
3. **loan_accounts** joins against both dimension tables to resolve `borrower_key` and `product_key`
4. **payments** joins against `loan_accounts` to resolve `loan_account_key`

Unresolved FKs are logged as errors but records are **not dropped** — they are written with `NULL` keys to allow manual remediation.

### 3.6 Dropped Columns

| Table | Column | Reason |
|-------|--------|--------|
| `CDW_BORR_MSTR` | `BORR_REC_TYP` | Internal record type flag; not needed |
| `CDW_LN_ACCT` | `BORR_FST_NM` | Denormalized; use borrower FK |
| `CDW_LN_ACCT` | `BORR_LST_NM` | Denormalized; use borrower FK |
| `CDW_LN_ACCT` | `BORR_SSN_LST4` | Denormalized; use borrower FK |

### 3.7 Added Columns

| Table | Column | Purpose |
|-------|--------|---------|
| All tables | `_migration_source` | Tracks which legacy table this row originated from |
| All tables | `_migrated_at` | Timestamp of when the row was migrated |
| `loan_accounts` | `origination_year` | Generated column (`YEAR(origination_date)`) for query optimization |
| `payments` | `payment_year` | Generated column for partition pruning |
| `payments` | `payment_month` | Generated column for partition pruning |
| `payments` | `legacy_sequence_id` | Preserves `PMT_SEQ_NBR` for traceability |

---

## 4. Partitioning Strategy

### borrowers — Partitioned by `state`
- Loan servicing queries frequently filter by geographic region
- 50 US states + territories = manageable partition count
- Enables efficient state-level regulatory reporting

### loan_products — No partitioning
- Small reference table (< 100 rows expected)
- Partitioning would add overhead with no benefit

### loan_accounts — Partitioned by `status`
- Most operational queries filter by `Active` status
- Only 4 distinct values (Active, Closed, Default, Forbearance)
- Enables efficient partition pruning for portfolio reporting

### payments — Partitioned by `payment_year`, `payment_month`
- Payment queries are almost always time-bounded
- Year/month provides good granularity without over-partitioning
- Supports efficient monthly statement generation and period-end reconciliation

---

## 5. Delta Lake Table Properties

All tables use:
- `delta.autoOptimize.optimizeWrite = true` — coalesces small files during writes
- `delta.autoOptimize.autoCompact = true` — automatically compacts small files
- `quality.tier = gold` — metadata tag for data governance

---

## 6. Recommended Execution Order

Execute the migration in the following strict order. Steps within the same phase can run in parallel.

### Phase 0: Setup
```sql
-- Run: databricks/ddl/00_database_setup.sql
CREATE DATABASE IF NOT EXISTS loan_warehouse;
```

### Phase 1: Create Tables
```sql
-- Run in order:
-- databricks/ddl/01_borrowers.sql
-- databricks/ddl/02_loan_products.sql
-- databricks/ddl/03_loan_accounts.sql
-- databricks/ddl/04_payments.sql
```

### Phase 2: Extract Legacy Data
Export legacy tables to CSV or Parquet in the landing zone:
```
/mnt/landing/cdw_borr_mstr/
/mnt/landing/cdw_ln_prod/
/mnt/landing/cdw_ln_acct/
/mnt/landing/cdw_pmt_hist/
```

### Phase 3a: Ingest Dimension Tables (parallel)
```bash
spark-submit databricks/ingestion/ingest_borrowers.py \
    --source /mnt/landing/cdw_borr_mstr/

spark-submit databricks/ingestion/ingest_loan_products.py \
    --source /mnt/landing/cdw_ln_prod/
```

### Phase 3b: Ingest Fact Tables (sequential, after 3a)
```bash
spark-submit databricks/ingestion/ingest_loan_accounts.py \
    --source /mnt/landing/cdw_ln_acct/

spark-submit databricks/ingestion/ingest_payments.py \
    --source /mnt/landing/cdw_pmt_hist/
```

### Phase 3 (alternative): Run Full Pipeline
```bash
spark-submit databricks/ingestion/run_full_pipeline.py \
    --borrowers /mnt/landing/cdw_borr_mstr/ \
    --products  /mnt/landing/cdw_ln_prod/ \
    --accounts  /mnt/landing/cdw_ln_acct/ \
    --payments  /mnt/landing/cdw_pmt_hist/
```

### Phase 4: Data Quality Validation
```bash
spark-submit databricks/quality/data_quality_checks.py \
    --borrowers-source /mnt/landing/cdw_borr_mstr/ \
    --products-source  /mnt/landing/cdw_ln_prod/ \
    --accounts-source  /mnt/landing/cdw_ln_acct/ \
    --payments-source  /mnt/landing/cdw_pmt_hist/ \
    --output           databricks/quality/DATA_QUALITY_REPORT.md
```

Review the generated `DATA_QUALITY_REPORT.md` before proceeding.

### Phase 5: Optimize Tables
```sql
OPTIMIZE loan_warehouse.borrowers ZORDER BY (external_id);
OPTIMIZE loan_warehouse.loan_products ZORDER BY (code);
OPTIMIZE loan_warehouse.loan_accounts ZORDER BY (account_number, borrower_key);
OPTIMIZE loan_warehouse.payments ZORDER BY (loan_account_key, payment_date);
```

### Phase 6: Cutover
1. Verify all data quality checks pass
2. Update downstream application connection strings
3. Monitor for 24-48 hours
4. Archive legacy landing zone files

---

## 7. Error Handling Strategy

The pipeline follows a **log-and-continue** approach:

| Scenario | Behavior |
|----------|----------|
| Malformed date string | Set to `NULL`, log warning |
| Malformed amount string | Set to `NULL`, log warning |
| Unknown status code | Set to `UNKNOWN:<code>`, log warning |
| Unresolved FK (borrower/product) | Set FK to `NULL`, log error with record IDs |
| Row count mismatch after transform | Log error (never silently drop rows) |
| Null in required field | Log warning, write record as-is |

Records are **never silently dropped**. Every anomaly is logged for post-migration remediation.

---

## 8. Rollback Plan

Delta Lake provides time travel for rollback:

```sql
-- View table history
DESCRIBE HISTORY loan_warehouse.borrowers;

-- Restore to a previous version
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF <version_number>;

-- Or restore to a timestamp
RESTORE TABLE loan_warehouse.loan_accounts TO TIMESTAMP AS OF '2025-01-01T00:00:00';
```

To perform a full rollback:
```sql
DROP TABLE IF EXISTS loan_warehouse.payments;
DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
DROP TABLE IF EXISTS loan_warehouse.loan_products;
DROP TABLE IF EXISTS loan_warehouse.borrowers;
-- Then re-run DDL scripts and re-ingest
```

---

## 9. File Inventory

```
databricks/
├── ddl/
│   ├── 00_database_setup.sql       # Database creation
│   ├── 01_borrowers.sql            # Borrower dimension table
│   ├── 02_loan_products.sql        # Product reference table
│   ├── 03_loan_accounts.sql        # Loan account fact table
│   └── 04_payments.sql             # Payment history fact table
├── ingestion/
│   ├── __init__.py
│   ├── transforms.py               # Shared transformation functions
│   ├── ingest_borrowers.py         # CDW_BORR_MSTR ingestion
│   ├── ingest_loan_products.py     # CDW_LN_PROD ingestion
│   ├── ingest_loan_accounts.py     # CDW_LN_ACCT ingestion
│   ├── ingest_payments.py          # CDW_PMT_HIST ingestion
│   └── run_full_pipeline.py        # Full pipeline orchestrator
└── quality/
    ├── __init__.py
    ├── data_quality_checks.py      # Post-ingestion validation suite
    └── DATA_QUALITY_REPORT.md      # Quality report (generated at runtime)
```
