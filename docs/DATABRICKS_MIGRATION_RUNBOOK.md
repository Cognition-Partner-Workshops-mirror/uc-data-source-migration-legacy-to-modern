# Databricks Migration Runbook

## Overview

This runbook documents the migration of the CDW (Corporate Data Warehouse) legacy loan management data to a modern Delta Lake schema on Databricks. It covers every transformation decision, column mapping, type conversion, partitioning rationale, and the recommended execution order.

---

## 1. Source System: Legacy CDW Schema

The legacy CDW schema consists of four denormalized tables where **all columns are VARCHAR**, dates are stored as `MM/DD/YYYY` strings, amounts include commas (`"285,000"`), and status fields use cryptic abbreviations.

| Legacy Table | Description | Row Count (seed) |
|---|---|---|
| `CDW_BORR_MSTR` | Borrower master records | 5 |
| `CDW_LN_PROD` | Loan product definitions | 5 |
| `CDW_LN_ACCT` | Loan accounts (denormalized with borrower data) | 5 |
| `CDW_PMT_HIST` | Payment history transactions | 10 |

### Key Legacy Problems Addressed

| Problem | Example | Resolution |
|---|---|---|
| All-VARCHAR columns | `LN_CURR_BAL VARCHAR(15)` stores `"271,432.56"` | Cast to `DECIMAL(12,2)` after stripping commas |
| String dates | `BORR_DOB_DT` = `"03/15/1978"` | Parse `MM/dd/yyyy` to `DATE` / `TIMESTAMP` |
| Cryptic names | `BORR_FST_NM`, `LN_LTV_PCT` | Renamed to `first_name`, `ltv_percent` |
| No foreign keys | `CDW_LN_ACCT.BORR_ID` is just a string | Resolved to surrogate `borrower_key` with FK constraint |
| Denormalized borrower data | `CDW_LN_ACCT` repeats `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` | Dropped from loan table; use `borrower_key` FK |
| Status abbreviations | `ACT`, `CLO`, `DFT`, `FRB` | Expanded to `Active`, `Closed`, `Default`, `Forbearance` |

---

## 2. Target System: Delta Lake Schema

### 2.1 Database

All tables reside in the `loan_warehouse` database (Unity Catalog schema).

### 2.2 Table Definitions

DDL scripts are in `databricks/ddl/` and must be executed in numeric order:

| Order | File | Target Table | Partitioning |
|---|---|---|---|
| 1 | `001_borrowers.sql` | `loan_warehouse.borrowers` | `state` |
| 2 | `002_loan_products.sql` | `loan_warehouse.loan_products` | None (small dim) |
| 3 | `003_loan_accounts.sql` | `loan_warehouse.loan_accounts` | `status` |
| 4 | `004_payments.sql` | `loan_warehouse.payments` | `payment_year` |

### 2.3 Partitioning Rationale

| Table | Partition Column | Rationale |
|---|---|---|
| `borrowers` | `state` | Regional queries for compliance reporting; ~50 distinct values |
| `loan_products` | *(none)* | Small reference table (<100 rows); partitioning adds overhead |
| `loan_accounts` | `status` | Most queries filter by loan status (Active vs Closed); 4 distinct values enable partition pruning |
| `payments` | `payment_year` | Time-range queries dominate payment analysis; yearly partitions balance granularity and file count |

### 2.4 Delta Table Properties

All tables use:
- `delta.autoOptimize.optimizeWrite = true` — auto-coalesces small files on write
- `delta.autoOptimize.autoCompact = true` — background compaction of small files
- `delta.columnMapping.mode = name` — enables column rename/drop without rewriting data

---

## 3. Column Mappings

### 3.1 CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `BORR_ID` | `external_id` | VARCHAR → STRING | Direct copy; UNIQUE constraint |
| `BORR_FST_NM` | `first_name` | VARCHAR → STRING | NOT NULL |
| `BORR_LST_NM` | `last_name` | VARCHAR → STRING | NOT NULL |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR → STRING | Nullable |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR → STRING | Direct copy; re-encryption recommended |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR → DATE | `MM/dd/yyyy` parse |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR → STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR → STRING | Nullable |
| `BORR_CTY_NM` | `city` | VARCHAR → STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR → STRING | 2-char code; partition column |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR → STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR → STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR → STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR → INT | String-to-integer parse |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR → STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR → DECIMAL(12,2) | Strip commas, parse |
| `BORR_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | `MM/dd/yyyy` parse to midnight |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | `MM/dd/yyyy` parse to midnight |
| `BORR_STAT_CD` | `status` | VARCHAR → STRING | `ACT`→`Active`, `INA`→`Inactive` |
| `BORR_REC_TYP` | `_legacy_record_type` | VARCHAR → STRING | Preserved for audit; not in modern schema |

### 3.2 CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `PROD_CD` | `code` | VARCHAR → STRING | UNIQUE constraint |
| `PROD_DESC_TXT` | `name` | VARCHAR → STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR → STRING | FXD, ARM, FHA, VA |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | String-to-integer |
| `PROD_RT_TYP` | `rate_type` | VARCHAR → STRING | FIXED, VARIABLE |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) | Strip commas |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) | Strip commas |
| `PROD_STAT_CD` | `is_active` | VARCHAR → BOOLEAN | `ACT`→`true`, `INA`→`false` |
| `PROD_EFF_DT` | `effective_date` | VARCHAR → DATE | `MM/dd/yyyy` parse |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR → DATE | `MM/dd/yyyy` parse |

### 3.3 CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `LN_ACCT_NBR` | `account_number` | VARCHAR → STRING | UNIQUE constraint |
| `BORR_ID` | `borrower_key` | VARCHAR → BIGINT | FK lookup via `borrowers.external_id` |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use FK |
| `PROD_CD` | `product_key` | VARCHAR → BIGINT | FK lookup via `loan_products.code` |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) | Strip commas |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) | Strip commas |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | Direct parse |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | String-to-integer |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) | Strip commas |
| `LN_ORIG_DT` | `origination_date` | VARCHAR → DATE | `MM/dd/yyyy` parse |
| `LN_MAT_DT` | `maturity_date` | VARCHAR → DATE | `MM/dd/yyyy` parse |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR → DATE | `MM/dd/yyyy` parse |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR → DATE | `MM/dd/yyyy` parse |
| `LN_STAT_CD` | `status` | VARCHAR → STRING | `ACT`→`Active`, `CLO`→`Closed`, `DFT`→`Default`, `FRB`→`Forbearance` |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | String-to-integer |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Strip commas |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | Direct parse |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR → STRING | `SFR`→`Single Family`, `CND`→`Condominium`, `MFR`→`Multi-Family`, `TWN`→`Townhouse` |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Strip commas |
| `LN_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | `MM/dd/yyyy` parse |
| `LN_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | `MM/dd/yyyy` parse |

### 3.4 CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `PMT_SEQ_NBR` | `legacy_sequence_nbr` | VARCHAR → STRING | Preserved for audit |
| `LN_ACCT_NBR` | `loan_account_key` | VARCHAR → BIGINT | FK lookup via `loan_accounts.account_number` |
| `PMT_DT` | `payment_date` | VARCHAR → DATE | `MM/dd/yyyy` parse |
| `PMT_AMT` | `total_amount` | VARCHAR → DECIMAL(10,2) | Strip commas |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR → DECIMAL(10,2) | Strip commas |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR → DECIMAL(10,2) | Strip commas |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR → DECIMAL(10,2) | Strip commas |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR → DECIMAL(10,2) | Strip commas |
| `PMT_TYP_CD` | `type` | VARCHAR → STRING | `REG`→`Regular`, `EXT`→`Extra`, `PRT`→`Partial`, `PRE`→`Prepayment` |
| `PMT_STAT_CD` | `status` | VARCHAR → STRING | `PST`→`Posted`, `REV`→`Reversed`, `NSF`→`NSF`, `PND`→`Pending` |
| `PMT_RECV_DT` | `received_date` | VARCHAR → DATE | `MM/dd/yyyy` parse |
| `PMT_PROC_DT` | `processed_date` | VARCHAR → DATE | `MM/dd/yyyy` parse |
| `PMT_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | `MM/dd/yyyy` parse |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | `MM/dd/yyyy` parse |
| *(derived)* | `payment_year` | — | `year(payment_date)` for partitioning |

---

## 4. Status Code Expansion Reference

### Loan Status (`LN_STAT_CD`)

| Code | Expanded Value | Description |
|---|---|---|
| `ACT` | `Active` | Loan is current and being serviced |
| `CLO` | `Closed` | Loan has been paid off or settled |
| `DFT` | `Default` | Borrower has defaulted on payments |
| `FRB` | `Forbearance` | Payments temporarily reduced or suspended |

### Borrower Status (`BORR_STAT_CD`)

| Code | Expanded Value |
|---|---|
| `ACT` | `Active` |
| `INA` | `Inactive` |

### Payment Type (`PMT_TYP_CD`)

| Code | Expanded Value |
|---|---|
| `REG` | `Regular` |
| `EXT` | `Extra` |
| `PRT` | `Partial` |
| `PRE` | `Prepayment` |

### Payment Status (`PMT_STAT_CD`)

| Code | Expanded Value |
|---|---|
| `PST` | `Posted` |
| `REV` | `Reversed` |
| `NSF` | `NSF` (Non-Sufficient Funds) |
| `PND` | `Pending` |

### Property Type (`PROP_TYP_CD`)

| Code | Expanded Value |
|---|---|
| `SFR` | `Single Family` |
| `CND` | `Condominium` |
| `MFR` | `Multi-Family` |
| `TWN` | `Townhouse` |

### Product Status (`PROD_STAT_CD`)

| Code | Expanded Value |
|---|---|
| `ACT` | `true` (boolean) |
| `INA` | `false` (boolean) |

---

## 5. Transformation Patterns

### 5.1 Date Parsing

All legacy dates are stored as `MM/DD/YYYY` strings. The pipeline uses:

```python
F.to_date(F.col("LEGACY_COL"), "MM/dd/yyyy")      # → DateType
F.to_timestamp(F.col("LEGACY_COL"), "MM/dd/yyyy")  # → TimestampType (midnight)
```

**Edge cases handled:**
- NULL input → NULL output (Spark default behavior)
- Malformed strings → NULL output (logged, record quarantined if critical)

### 5.2 Amount Parsing

Amounts like `"285,000"` and `"271,432.56"` are converted by:

```python
F.regexp_replace(F.col("LEGACY_COL"), ",", "").cast(DecimalType(12, 2))
```

**Edge cases handled:**
- NULL → NULL
- Empty string → NULL
- Non-numeric after comma removal → NULL (quarantined)

### 5.3 Status Code Expansion

Uses PySpark `CASE WHEN` chains built from mapping dictionaries. Unknown codes are preserved as-is and flagged in quality reports.

### 5.4 Foreign Key Resolution

Surrogate keys are resolved by joining to already-loaded dimension tables:

```
CDW_LN_ACCT.BORR_ID  →  JOIN borrowers ON external_id  →  borrower_key
CDW_LN_ACCT.PROD_CD  →  JOIN loan_products ON code      →  product_key
CDW_PMT_HIST.LN_ACCT_NBR → JOIN loan_accounts ON account_number → loan_account_key
```

LEFT JOINs are used to avoid dropping records with unresolved FKs. Unresolved records are flagged for review.

### 5.5 Denormalization Removal

Three columns from `CDW_LN_ACCT` are dropped:
- `BORR_FST_NM` — available via `borrower_key` FK
- `BORR_LST_NM` — available via `borrower_key` FK
- `BORR_SSN_LST4` — available via `borrower_key` FK (full SSN hash)

---

## 6. Error Handling Strategy

The pipeline uses a **quarantine pattern** rather than dropping records:

1. Each ingestion script produces two DataFrames: `good_df` and `quarantine_df`
2. `good_df` is written to the target Delta table
3. `quarantine_df` is written to `/mnt/quarantine/<source_table>/` as Delta
4. Quarantine criteria: missing required fields or critical parse failures
5. Non-critical parse failures (e.g., NULL credit score) produce NULLs in the target but do NOT quarantine

### Quarantine Locations

| Source | Quarantine Path |
|---|---|
| `CDW_BORR_MSTR` | `/mnt/quarantine/cdw_borr_mstr/` |
| `CDW_LN_PROD` | `/mnt/quarantine/cdw_ln_prod/` |
| `CDW_LN_ACCT` | `/mnt/quarantine/cdw_ln_acct/` |
| `CDW_PMT_HIST` | `/mnt/quarantine/cdw_pmt_hist/` |

---

## 7. Data Quality Framework

After ingestion, run `databricks/quality/data_quality_checks.py` to validate:

| Check Category | What It Validates |
|---|---|
| **Row Count Reconciliation** | `source_count == target_count + quarantine_count` for each table |
| **Null Checks** | Required columns have zero NULLs |
| **Referential Integrity** | All FK values exist in parent tables (no orphans) |
| **Business Rules** | Active loans: balance > 0; maturity > origination; rate in [0,100]; LTV in [0,200]; delinquency >= 0; payment components sum to total; credit score in [300,850] |

The framework generates `DATA_QUALITY_REPORT.md` with pass/fail for each check.

---

## 8. Execution Order

### Step-by-step instructions for Databricks:

```
1. Create the database
   spark.sql("CREATE DATABASE IF NOT EXISTS loan_warehouse")

2. Run DDL scripts (in order):
   %run ./databricks/ddl/001_borrowers.sql
   %run ./databricks/ddl/002_loan_products.sql
   %run ./databricks/ddl/003_loan_accounts.sql
   %run ./databricks/ddl/004_payments.sql

3. Stage source data:
   Upload legacy CSV/Parquet extracts to:
     /mnt/landing/cdw_borr_mstr/
     /mnt/landing/cdw_ln_prod/
     /mnt/landing/cdw_ln_acct/
     /mnt/landing/cdw_pmt_hist/

4. Run ingestion pipeline (respects dependency order):
   %run ./databricks/ingestion/run_pipeline

   Or run individually:
   a. %run ./databricks/ingestion/ingest_borrowers       (no deps)
   b. %run ./databricks/ingestion/ingest_loan_products    (no deps)
   c. %run ./databricks/ingestion/ingest_loan_accounts    (needs a + b)
   d. %run ./databricks/ingestion/ingest_payments         (needs c)

5. Run data quality checks:
   %run ./databricks/quality/data_quality_checks

6. Review the quality report:
   - Written to /mnt/reports/DATA_QUALITY_REPORT.md
   - Console output shows pass/fail summary

7. Review quarantined records:
   spark.read.format("delta").load("/mnt/quarantine/cdw_borr_mstr/").show()
   spark.read.format("delta").load("/mnt/quarantine/cdw_ln_acct/").show()
   etc.
```

### Dependency Graph

```
CDW_BORR_MSTR ──► borrowers ─────────┐
                                      ├──► loan_accounts ──► payments
CDW_LN_PROD   ──► loan_products ─────┘
```

---

## 9. Idempotency and Re-runs

- All ingestion scripts use `.mode("append")`. For a clean re-run, truncate target tables first:
  ```sql
  TRUNCATE TABLE loan_warehouse.payments;
  TRUNCATE TABLE loan_warehouse.loan_accounts;
  TRUNCATE TABLE loan_warehouse.loan_products;
  TRUNCATE TABLE loan_warehouse.borrowers;
  ```
- For incremental loads, consider switching to Delta Lake `MERGE INTO` with the natural keys (`external_id`, `code`, `account_number`, `legacy_sequence_nbr`).

---

## 10. Post-Migration Validation

After the pipeline completes and the quality report shows all checks passing:

1. **Spot-check sample records** against the legacy source
2. **Run the Spring Boot application** against the modern schema to verify API parity
3. **Compare golden file API responses** (see `docs/MIGRATION_TASKS.md`, Task 4)
4. **Archive legacy landing zone data** for audit trail retention

---

## 11. Files Reference

| Path | Description |
|---|---|
| `databricks/ddl/001_borrowers.sql` | Delta Lake DDL for borrowers |
| `databricks/ddl/002_loan_products.sql` | Delta Lake DDL for loan_products |
| `databricks/ddl/003_loan_accounts.sql` | Delta Lake DDL for loan_accounts |
| `databricks/ddl/004_payments.sql` | Delta Lake DDL for payments |
| `databricks/ingestion/transforms.py` | Shared transformation utilities |
| `databricks/ingestion/ingest_borrowers.py` | Borrower ingestion script |
| `databricks/ingestion/ingest_loan_products.py` | Loan product ingestion script |
| `databricks/ingestion/ingest_loan_accounts.py` | Loan account ingestion script |
| `databricks/ingestion/ingest_payments.py` | Payment ingestion script |
| `databricks/ingestion/run_pipeline.py` | Master pipeline orchestrator |
| `databricks/quality/data_quality_checks.py` | Post-ingestion quality framework |
| `data/mappings/column_mappings.md` | Source column mapping reference |
| `src/main/resources/schema-legacy.sql` | Legacy schema DDL |
| `src/main/resources/data-legacy.sql` | Legacy seed data |
