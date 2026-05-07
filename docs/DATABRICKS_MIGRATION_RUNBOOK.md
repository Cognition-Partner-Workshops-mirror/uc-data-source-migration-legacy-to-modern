# Databricks Migration Runbook

## Legacy CDW → Delta Lake Loan Data Warehouse

---

## 1. Overview

This runbook documents the migration of a legacy CDW (Corporate Data Warehouse) loan management schema to a modern Delta Lake architecture on Databricks. The legacy system stores all data as VARCHAR columns with cryptic abbreviated names, no foreign keys, denormalized structures, and status codes represented as short abbreviations.

### Source System

| Legacy Table | Description | Row Volume (seed) |
|---|---|---|
| `CDW_BORR_MSTR` | Borrower master records | 5 |
| `CDW_LN_PROD` | Loan product definitions | 5 |
| `CDW_LN_ACCT` | Loan accounts (denormalized with borrower data) | 5 |
| `CDW_PMT_HIST` | Payment history | 10 |

### Target System

| Delta Table | Description |
|---|---|
| `loan_warehouse.borrowers` | Normalized borrower dimension |
| `loan_warehouse.loan_products` | Loan product reference |
| `loan_warehouse.loan_accounts` | Loan accounts with FK references |
| `loan_warehouse.payments` | Payment transaction history |

---

## 2. Column Mapping Reference

### 2.1 CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `BORR_ID` | `external_id` | VARCHAR → STRING | Direct copy; preserved for traceability |
| `BORR_FST_NM` | `first_name` | VARCHAR → STRING | Trimmed |
| `BORR_LST_NM` | `last_name` | VARCHAR → STRING | Trimmed |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR → STRING | Trimmed |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR → STRING | Carried forward; re-encryption recommended |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR → STRING | Trimmed |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR → STRING | Trimmed |
| `BORR_CTY_NM` | `city` | VARCHAR → STRING | Trimmed |
| `BORR_ST_CD` | `state` | VARCHAR → STRING | Trimmed; used as partition key |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR → STRING | Trimmed |
| `BORR_PH_NBR` | `phone` | VARCHAR → STRING | Trimmed |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR → STRING | Trimmed |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR → INT | Parse string to integer |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR → STRING | Trimmed |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `BORR_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `BORR_STAT_CD` | `status` | VARCHAR → STRING | Expand: ACT→ACTIVE, INA→INACTIVE |
| `BORR_REC_TYP` | *(dropped)* | — | Record type indicator not needed |

### 2.2 CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `PROD_CD` | `code` | VARCHAR → STRING | Direct copy |
| `PROD_DESC_TXT` | `name` | VARCHAR → STRING | Trimmed |
| `PROD_TYP_CD` | `type` | VARCHAR → STRING | FXD, ARM, FHA, VA |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | Parse string |
| `PROD_RT_TYP` | `rate_type` | VARCHAR → STRING | FIXED or VARIABLE |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `PROD_STAT_CD` | `is_active` | VARCHAR → BOOLEAN | ACT→true, INA→false |
| `PROD_EFF_DT` | `effective_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |

### 2.3 CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `LN_ACCT_NBR` | `account_number` | VARCHAR → STRING | Direct copy |
| `BORR_ID` | `borrower_id` | VARCHAR → BIGINT | FK lookup via `borrowers.external_id` |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_id` | VARCHAR → BIGINT | FK lookup via `loan_products.code` |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | Parse rate string (e.g. "5.250") |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | Parse string |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `LN_ORIG_DT` | `origination_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_MAT_DT` | `maturity_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_STAT_CD` | `status` | VARCHAR → STRING | ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | Parse string |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | Parse percentage string |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR → STRING | Trimmed |
| `PROP_CTY_NM` | `property_city` | VARCHAR → STRING | Trimmed |
| `PROP_ST_CD` | `property_state` | VARCHAR → STRING | Trimmed |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR → STRING | Trimmed |
| `PROP_TYP_CD` | `property_type` | VARCHAR → STRING | SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `LN_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| *(derived)* | `origination_year` | — → INT | `year(origination_date)` for partitioning |

### 2.4 CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `PMT_SEQ_NBR` | `legacy_payment_id` | VARCHAR → STRING | Preserved for traceability |
| `LN_ACCT_NBR` | `loan_account_id` | VARCHAR → BIGINT | FK lookup via `loan_accounts.account_number` |
| `PMT_DT` | `payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_AMT` | `total_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_TYP_CD` | `type` | VARCHAR → STRING | REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| `PMT_STAT_CD` | `status` | VARCHAR → STRING | PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| `PMT_RECV_DT` | `received_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_PROC_DT` | `processed_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| *(derived)* | `payment_year` | — → INT | `year(payment_date)` for partitioning |

---

## 3. Transformation Decisions

### 3.1 Date Parsing

All legacy dates are stored as `VARCHAR(10)` in `MM/DD/YYYY` format. The pipeline uses Spark's `to_date()` with format `"MM/dd/yyyy"`. Records with unparseable dates are logged as warnings but not dropped — the column is set to `NULL` and flagged in the quality report.

**Rationale:** Silently dropping records with bad dates would cause row-count mismatches and data loss. Preserving them with NULLs surfaces the issue in quality checks.

### 3.2 Amount Parsing

Legacy amounts are stored as comma-formatted strings (e.g. `"285,000"`, `"271,432.56"`). The pipeline removes commas via `regexp_replace` then casts to `DecimalType`.

**Precision choices:**
- Loan amounts, balances, appraised values: `DECIMAL(12,2)` — supports values up to $9,999,999,999.99
- Monthly payments, escrow, fees: `DECIMAL(10,2)` — supports values up to $99,999,999.99
- Interest rates: `DECIMAL(5,3)` — supports rates up to 99.999%
- Percentages (LTV): `DECIMAL(5,2)` — supports up to 999.99%

### 3.3 Status Code Expansion

All legacy status codes are expanded to human-readable values per the mapping specification:

| Domain | Legacy Code | Modern Value |
|---|---|---|
| Loan Status | ACT | ACTIVE |
| Loan Status | CLO | CLOSED |
| Loan Status | DFT | DEFAULT |
| Loan Status | FRB | FORBEARANCE |
| Borrower Status | ACT | ACTIVE |
| Borrower Status | INA | INACTIVE |
| Product Status | ACT | true (boolean) |
| Product Status | INA | false (boolean) |
| Payment Type | REG | REGULAR |
| Payment Type | EXT | EXTRA |
| Payment Type | PRT | PARTIAL |
| Payment Type | PRE | PREPAYMENT |
| Payment Status | PST | POSTED |
| Payment Status | REV | REVERSED |
| Payment Status | NSF | NSF |
| Payment Status | PND | PENDING |
| Property Type | SFR | Single Family |
| Property Type | CND | Condominium |
| Property Type | MFR | Multi-Family |
| Property Type | TWN | Townhouse |

**Unknown codes** are preserved with a `_UNKNOWN` suffix (e.g. `"XYZ_UNKNOWN"`) so they are visible in quality checks rather than silently dropped.

### 3.4 Denormalization Removal

The legacy `CDW_LN_ACCT` table embeds borrower columns (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) directly. In the modern schema these are dropped and replaced with a `borrower_id` FK that references `loan_warehouse.borrowers`. This:

- Eliminates data duplication and inconsistency risk
- Enables borrower updates in a single place
- Follows standard star-schema dimensional modeling

### 3.5 FK Resolution Strategy

Legacy tables use string-based identifiers (e.g. `BORR_ID = "B-10001"`, `PROD_CD = "FXD30"`). The modern schema uses auto-generated `BIGINT` surrogate keys. The ingestion pipeline resolves FKs via left joins:

- `loan_accounts.borrower_id` ← lookup `borrowers.id` WHERE `borrowers.external_id = CDW_LN_ACCT.BORR_ID`
- `loan_accounts.product_id` ← lookup `loan_products.id` WHERE `loan_products.code = CDW_LN_ACCT.PROD_CD`
- `payments.loan_account_id` ← lookup `loan_accounts.id` WHERE `loan_accounts.account_number = CDW_PMT_HIST.LN_ACCT_NBR`

Unresolved FKs result in `NULL` values and are logged as warnings.

### 3.6 Lineage Columns

Every target table includes two metadata columns:
- `_migration_src` — the legacy source table name (e.g. `CDW_BORR_MSTR`)
- `_migrated_at` — timestamp of when the record was migrated

These support audit trails and debugging.

---

## 4. Partitioning Strategy

| Table | Partition Column | Rationale |
|---|---|---|
| `borrowers` | `state` | Regional queries for compliance and servicing |
| `loan_products` | *(none)* | Small reference table; no partitioning needed |
| `loan_accounts` | `status` | Most queries filter by ACTIVE/CLOSED/DEFAULT |
| `payments` | `payment_year` | Time-range queries dominate payment analytics |

**Delta Lake optimizations enabled:**
- `autoOptimize.optimizeWrite = true` — coalesces small files on write
- `autoOptimize.autoCompact = true` — compacts small files asynchronously
- `columnMapping.mode = name` — enables column rename/drop without rewriting data

---

## 5. Execution Order

The pipeline must run in strict dependency order because later tables depend on FK lookups against earlier tables.

```
Step 1: Run DDL scripts (create database and tables)
  └─ databricks/ddl/00_database.sql
  └─ databricks/ddl/01_borrowers.sql
  └─ databricks/ddl/02_loan_products.sql
  └─ databricks/ddl/03_loan_accounts.sql
  └─ databricks/ddl/04_payments.sql

Step 2: Stage legacy data as CSV/Parquet in landing zone
  └─ /mnt/landing/cdw/cdw_borr_mstr/
  └─ /mnt/landing/cdw/cdw_ln_prod/
  └─ /mnt/landing/cdw/cdw_ln_acct/
  └─ /mnt/landing/cdw/cdw_pmt_hist/

Step 3: Run ingestion pipeline (in order)
  └─ ingest_borrowers       (no FK dependencies)
  └─ ingest_loan_products   (no FK dependencies)
  └─ ingest_loan_accounts   (depends on borrowers + loan_products)
  └─ ingest_payments         (depends on loan_accounts)

Step 4: Run data quality checks
  └─ run_quality_checks(spark, pipeline_results)
  └─ Review DATA_QUALITY_REPORT.md

Step 5: Post-migration verification
  └─ Spot-check sample records against legacy source
  └─ Validate aggregate totals (sum of balances, payment counts)
  └─ Confirm partitioning is correct (DESCRIBE DETAIL table)
```

### Orchestrator Shortcut

Steps 3 and 4 can be executed together:

```python
from databricks.ingestion.run_pipeline import run_migration
from databricks.quality.run_quality_checks import run_quality_checks

results = run_migration(spark, base_path="/mnt/landing/cdw/")
report = run_quality_checks(spark, results, output_path="/dbfs/reports/")
```

---

## 6. Error Handling & Quarantine

The pipeline never silently drops records. Instead:

1. **Required-field violations** — Records missing critical fields (e.g. `BORR_ID`, `LN_ACCT_NBR`) are written to quarantine tables:
   - `loan_warehouse._quarantine_borrowers`
   - `loan_warehouse._quarantine_loan_products`
   - `loan_warehouse._quarantine_loan_accounts`
   - `loan_warehouse._quarantine_payments`

2. **Type-conversion failures** — Fields that fail parsing (e.g. a date string `"99/99/9999"`) become `NULL` in the target. These are caught by the null-check quality validators.

3. **Unresolved FKs** — Loan accounts referencing non-existent borrowers or products get `NULL` FK values. These are caught by the referential integrity checks.

4. **Unknown status codes** — Codes not in the mapping dictionaries are expanded with a `_UNKNOWN` suffix (e.g. `"XYZ_UNKNOWN"`) rather than being dropped.

All anomalies are logged via Python's `logging` module and summarized in the data quality report.

---

## 7. Data Quality Checks

The quality framework validates four categories after each migration run:

### 7.1 Row Count Reconciliation
- Source row count = target row count + quarantined row count
- Zero-row targets are flagged as failures

### 7.2 Null Checks on Required Fields
- `borrowers`: external_id, first_name, last_name, status
- `loan_products`: code, name, type
- `loan_accounts`: account_number, borrower_id, product_id, status
- `payments`: loan_account_id, payment_date, status

### 7.3 Referential Integrity
- Every `loan_accounts.borrower_id` exists in `borrowers.id`
- Every `loan_accounts.product_id` exists in `loan_products.id`
- Every `payments.loan_account_id` exists in `loan_accounts.id`

### 7.4 Business Rules
- Active loans must have `current_balance > 0`
- Closed loans must have a `maturity_date`
- Interest rate must be between 0 and 100
- Delinquency days must be >= 0
- Posted payments must have `total_amount > 0`
- `origination_date` must be before `maturity_date`
- LTV percent must be between 0 and 200

---

## 8. Rollback Procedure

Delta Lake's time-travel capability enables safe rollback:

```sql
-- View table history
DESCRIBE HISTORY loan_warehouse.loan_accounts;

-- Rollback to a previous version
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF <version>;

-- Or rollback to a timestamp
RESTORE TABLE loan_warehouse.loan_accounts TO TIMESTAMP AS OF '2025-01-15T00:00:00';
```

For a full rollback of the entire migration:

```sql
DROP TABLE IF EXISTS loan_warehouse.payments;
DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
DROP TABLE IF EXISTS loan_warehouse.loan_products;
DROP TABLE IF EXISTS loan_warehouse.borrowers;
-- Also drop quarantine tables
DROP TABLE IF EXISTS loan_warehouse._quarantine_borrowers;
DROP TABLE IF EXISTS loan_warehouse._quarantine_loan_products;
DROP TABLE IF EXISTS loan_warehouse._quarantine_loan_accounts;
DROP TABLE IF EXISTS loan_warehouse._quarantine_payments;
```

---

## 9. Post-Migration Optimization

After the initial load, run the following optimizations:

```sql
-- Optimize file layout
OPTIMIZE loan_warehouse.borrowers ZORDER BY (external_id);
OPTIMIZE loan_warehouse.loan_accounts ZORDER BY (account_number, origination_date);
OPTIMIZE loan_warehouse.payments ZORDER BY (loan_account_id, payment_date);

-- Analyze table statistics for query planning
ANALYZE TABLE loan_warehouse.borrowers COMPUTE STATISTICS FOR ALL COLUMNS;
ANALYZE TABLE loan_warehouse.loan_products COMPUTE STATISTICS FOR ALL COLUMNS;
ANALYZE TABLE loan_warehouse.loan_accounts COMPUTE STATISTICS FOR ALL COLUMNS;
ANALYZE TABLE loan_warehouse.payments COMPUTE STATISTICS FOR ALL COLUMNS;
```

---

## 10. File Inventory

| Path | Description |
|---|---|
| `databricks/ddl/00_database.sql` | Database creation |
| `databricks/ddl/01_borrowers.sql` | Borrower table DDL |
| `databricks/ddl/02_loan_products.sql` | Loan products table DDL |
| `databricks/ddl/03_loan_accounts.sql` | Loan accounts table DDL |
| `databricks/ddl/04_payments.sql` | Payments table DDL |
| `databricks/ingestion/__init__.py` | Package init |
| `databricks/ingestion/common.py` | Shared transformation utilities |
| `databricks/ingestion/ingest_borrowers.py` | Borrower ingestion script |
| `databricks/ingestion/ingest_loan_products.py` | Loan product ingestion script |
| `databricks/ingestion/ingest_loan_accounts.py` | Loan account ingestion script |
| `databricks/ingestion/ingest_payments.py` | Payment ingestion script |
| `databricks/ingestion/run_pipeline.py` | Pipeline orchestrator |
| `databricks/quality/__init__.py` | Package init |
| `databricks/quality/validators.py` | Quality check implementations |
| `databricks/quality/run_quality_checks.py` | Quality check runner & report generator |
| `docs/DATABRICKS_MIGRATION_RUNBOOK.md` | This document |
| `data/mappings/column_mappings.md` | Legacy-to-modern column mapping spec |
