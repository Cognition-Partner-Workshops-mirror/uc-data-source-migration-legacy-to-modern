# Databricks Migration Runbook

## 1. Overview

This runbook documents the migration of loan management data from the legacy CDW (Core Data Warehouse) all-VARCHAR schema into a modern, typed Delta Lake schema on Databricks. The legacy system stores every column as `VARCHAR` — dates as `MM/DD/YYYY` strings, monetary amounts as comma-formatted strings, and status fields as 2–3 character abbreviations with no foreign keys or referential constraints.

### Source Tables

| Legacy Table | Description | Row Count (seed) |
|---|---|---|
| `CDW_BORR_MSTR` | Borrower master records | 5 |
| `CDW_LN_PROD` | Loan product definitions | 5 |
| `CDW_LN_ACCT` | Loan accounts (denormalized with borrower data) | 5 |
| `CDW_PMT_HIST` | Payment history | 10 |

### Target Tables

| Delta Table | Description | Partition Column |
|---|---|---|
| `loan_warehouse.borrowers` | Borrower dimension | `state` |
| `loan_warehouse.loan_products` | Loan product reference | *(none — low cardinality)* |
| `loan_warehouse.loan_accounts` | Loan account fact | `status` |
| `loan_warehouse.payments` | Payment history fact | `payment_year` |

---

## 2. Column Mappings

### 2.1 CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| `BORR_ID` | `external_id` | VARCHAR(20) → STRING | Direct copy |
| `BORR_FST_NM` | `first_name` | VARCHAR(50) → STRING | Trim whitespace |
| `BORR_LST_NM` | `last_name` | VARCHAR(50) → STRING | Trim whitespace |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR(1) → STRING | Direct copy |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR(100) → STRING | Direct copy (re-encryption recommended) |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → DateType |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR(100) → STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR(100) → STRING | Direct copy |
| `BORR_CTY_NM` | `city` | VARCHAR(50) → STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR(2) → STRING | Direct copy |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR(10) → STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR(15) → STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR(100) → STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR(5) → INT | Cast string → integer |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR(20) → STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR(15) → DECIMAL(12,2) | Strip commas, cast |
| `BORR_CRET_DT` | `created_at` | VARCHAR(10) → TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR(10) → TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |
| `BORR_STAT_CD` | `status` | VARCHAR(5) → STRING | Expand: ACT→ACTIVE, INA→INACTIVE |
| `BORR_REC_TYP` | *(dropped)* | — | Not needed in modern schema |

### 2.2 CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| `PROD_CD` | `code` | VARCHAR(10) → STRING | Direct copy |
| `PROD_DESC_TXT` | `name` | VARCHAR(200) → STRING | Trim whitespace |
| `PROD_TYP_CD` | `type` | VARCHAR(5) → STRING | Direct copy |
| `PROD_TERM_MOS` | `term_months` | VARCHAR(5) → INT | Cast string → integer |
| `PROD_RT_TYP` | `rate_type` | VARCHAR(10) → STRING | Direct copy |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR(15) → DECIMAL(12,2) | Strip commas, cast |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR(15) → DECIMAL(12,2) | Strip commas, cast |
| `PROD_STAT_CD` | `is_active` | VARCHAR(5) → BOOLEAN | ACT→true, INA→false |
| `PROD_EFF_DT` | `effective_date` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → DateType |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → DateType |

### 2.3 CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| `LN_ACCT_NBR` | `account_number` | VARCHAR(20) → STRING | Direct copy |
| `BORR_ID` | `borrower_id` | VARCHAR(20) → BIGINT | FK lookup: borrowers.external_id → borrowers.borrower_id |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_id` | VARCHAR(10) → BIGINT | FK lookup: loan_products.code → loan_products.product_id |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR(15) → DECIMAL(12,2) | Strip commas, cast |
| `LN_CURR_BAL` | `current_balance` | VARCHAR(15) → DECIMAL(12,2) | Strip commas, cast |
| `LN_INT_RT` | `interest_rate` | VARCHAR(8) → DECIMAL(5,3) | Cast string → decimal |
| `LN_TERM_MOS` | `term_months` | VARCHAR(5) → INT | Cast string → integer |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR(15) → DECIMAL(10,2) | Strip commas, cast |
| `LN_ORIG_DT` | `origination_date` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → DateType |
| `LN_MAT_DT` | `maturity_date` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → DateType |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → DateType |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → DateType |
| `LN_STAT_CD` | `status` | VARCHAR(5) → STRING | Expand: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR(5) → INT | Cast string → integer |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR(15) → DECIMAL(10,2) | Strip commas, cast |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR(8) → DECIMAL(5,2) | Cast string → decimal |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR(100) → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR(50) → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR(2) → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR(10) → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR(10) → STRING | Expand: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR(15) → DECIMAL(12,2) | Strip commas, cast |
| `LN_CRET_DT` | `created_at` | VARCHAR(10) → TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |
| `LN_UPDT_DT` | `updated_at` | VARCHAR(10) → TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |

### 2.4 CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| `PMT_SEQ_NBR` | `legacy_sequence_nbr` | VARCHAR(20) → STRING | Preserved for audit traceability |
| `LN_ACCT_NBR` | `loan_account_id` | VARCHAR(20) → BIGINT | FK lookup: loan_accounts.account_number → loan_accounts.loan_account_id |
| `PMT_DT` | `payment_date` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → DateType |
| `PMT_AMT` | `total_amount` | VARCHAR(15) → DECIMAL(10,2) | Strip commas, cast |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR(15) → DECIMAL(10,2) | Strip commas, cast |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR(15) → DECIMAL(10,2) | Strip commas, cast |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR(15) → DECIMAL(10,2) | Strip commas, cast |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR(15) → DECIMAL(10,2) | Strip commas, cast |
| `PMT_TYP_CD` | `type` | VARCHAR(5) → STRING | Expand: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| `PMT_STAT_CD` | `status` | VARCHAR(5) → STRING | Expand: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| `PMT_RECV_DT` | `received_date` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → DateType |
| `PMT_PROC_DT` | `processed_date` | VARCHAR(10) → DATE | Parse `MM/DD/YYYY` → DateType |
| `PMT_CRET_DT` | `created_at` | VARCHAR(10) → TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR(10) → TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |

---

## 3. Transformation Decisions

### 3.1 Date Handling

All legacy dates are stored as `MM/DD/YYYY` VARCHAR strings. PySpark's `to_date()` with format `"MM/dd/yyyy"` handles the conversion. Created/updated audit timestamps are parsed to `TIMESTAMP` type (defaulting to midnight) to align with the modern schema's `DEFAULT CURRENT_TIMESTAMP` semantics. Null or malformed date strings produce `NULL` rather than causing row failures — the quality framework flags these downstream.

### 3.2 Amount Parsing

Monetary values like `"285,000"` and `"1,487.02"` use commas as thousands separators. The pipeline strips commas via `regexp_replace(col, ",", "")` before casting to `DECIMAL`. This is safe because no legacy amount uses commas as decimal separators. All monetary columns use `DECIMAL(12,2)` for loan-level amounts and `DECIMAL(10,2)` for payment-level amounts — matching the modern schema's precision requirements.

### 3.3 Status Code Expansion

Legacy status codes are 2–3 character abbreviations. The mapping is applied via PySpark `CASE` expressions:

| Context | Code | Expanded Value |
|---|---|---|
| Loan status | ACT | ACTIVE |
| Loan status | CLO | CLOSED |
| Loan status | DFT | DEFAULT |
| Loan status | FRB | FORBEARANCE |
| Borrower status | ACT | ACTIVE |
| Borrower status | INA | INACTIVE |
| Product status | ACT | true (boolean) |
| Product status | INA | false (boolean) |
| Payment type | REG | REGULAR |
| Payment type | EXT | EXTRA |
| Payment type | PRT | PARTIAL |
| Payment type | PRE | PREPAYMENT |
| Payment status | PST | POSTED |
| Payment status | REV | REVERSED |
| Payment status | NSF | NSF |
| Payment status | PND | PENDING |
| Property type | SFR | Single Family |
| Property type | CND | Condominium |
| Property type | MFR | Multi-Family |
| Property type | TWN | Townhouse |

Unknown codes are preserved as `"UNKNOWN:<original_code>"` so they can be identified in quality reports without silently losing data.

### 3.4 Denormalization Removal

The legacy `CDW_LN_ACCT` table embeds borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) directly in each loan row. In the modern schema, these are dropped and replaced by a `borrower_id` foreign key that references the `borrowers` dimension table. The FK is resolved during ingestion by joining on `BORR_ID = borrowers.external_id`.

### 3.5 Foreign Key Resolution

Legacy tables use string identifiers with no enforced relationships. The ingestion pipeline resolves these into typed BIGINT foreign keys:

| Child Table | FK Column | Lookup | Join Key |
|---|---|---|---|
| `loan_accounts` | `borrower_id` | `borrowers` | `BORR_ID = external_id` |
| `loan_accounts` | `product_id` | `loan_products` | `PROD_CD = code` |
| `payments` | `loan_account_id` | `loan_accounts` | `LN_ACCT_NBR = account_number` |

Unresolved FKs produce `NULL` in the target column and are logged as warnings. The quality framework then flags these as referential integrity violations.

### 3.6 Dropped Columns

| Table | Column | Reason |
|---|---|---|
| `CDW_BORR_MSTR` | `BORR_REC_TYP` | Internal record-type marker; no business meaning in modern schema |
| `CDW_LN_ACCT` | `BORR_FST_NM` | Denormalized; redundant with borrowers dimension |
| `CDW_LN_ACCT` | `BORR_LST_NM` | Denormalized; redundant with borrowers dimension |
| `CDW_LN_ACCT` | `BORR_SSN_LST4` | Denormalized; redundant with borrowers dimension |

### 3.7 Added Columns

| Table | Column | Purpose |
|---|---|---|
| All tables | `_load_ts` | Ingestion timestamp for audit/lineage |
| All tables | `_source_system` | Identifies the legacy source table |
| `payments` | `legacy_sequence_nbr` | Preserves `PMT_SEQ_NBR` for traceability |
| `payments` | `payment_year` | Generated column for partitioning |

---

## 4. Partitioning Rationale

| Table | Partition Column | Rationale |
|---|---|---|
| `borrowers` | `state` | Regional compliance queries frequently filter by state. ~50 distinct values keeps partition count manageable. |
| `loan_products` | *(none)* | Very small reference table (<100 rows expected). Partitioning would add overhead with no query benefit. |
| `loan_accounts` | `status` | Portfolio segmentation (active vs. closed vs. default) is the most common access pattern. 4 distinct values. |
| `payments` | `payment_year` | Payment history queries typically filter by date range. Year-level partitioning balances partition count against data skew. |

All Delta tables have `autoOptimize.optimizeWrite` and `autoOptimize.autoCompact` enabled to handle small-file compaction automatically.

---

## 5. Execution Order

The pipeline must be executed in strict dependency order:

```
Step 0: Create schema        → databricks/ddl/00_create_schema.sql
Step 1: Create DDL tables    → databricks/ddl/01_borrowers.sql
                              → databricks/ddl/02_loan_products.sql
                              → databricks/ddl/03_loan_accounts.sql
                              → databricks/ddl/04_payments.sql
Step 2: Ingest borrowers     → databricks/ingestion/ingest_borrowers.py
Step 3: Ingest loan products → databricks/ingestion/ingest_loan_products.py
Step 4: Ingest loan accounts → databricks/ingestion/ingest_loan_accounts.py   (depends on 2, 3)
Step 5: Ingest payments      → databricks/ingestion/ingest_payments.py        (depends on 4)
Step 6: Run quality checks   → databricks/quality/run_quality.py
```

Steps 2 and 3 can run in parallel since they have no dependencies on each other. Steps 4 and 5 must run sequentially due to FK dependencies.

The orchestrator script `databricks/ingestion/run_pipeline.py` automates steps 2–5 with dependency checking and will skip downstream steps if an upstream step fails.

### Running the Full Pipeline

```python
# In a Databricks notebook
from ingestion.run_pipeline import run_full_pipeline
from quality.run_quality import main as run_quality

# Step 1: Run ingestion
report = run_full_pipeline(
    spark,
    base_path="dbfs:/mnt/legacy/",
    source_format="csv",
    write_mode="overwrite",
)

# Step 2: Run quality checks
run_quality(
    spark,
    source_base_path="dbfs:/mnt/legacy/",
    source_format="csv",
    report_path="dbfs:/mnt/reports/DATA_QUALITY_REPORT.md",
)
```

---

## 6. Data Quality Checks

The quality framework (`databricks/quality/data_quality.py`) runs four categories of validation after ingestion:

### 6.1 Row Count Reconciliation
Compares the number of rows in each legacy source file against the corresponding Delta target table. Any mismatch triggers a FAIL.

### 6.2 Null Checks on Required Fields
Verifies that columns marked as NOT NULL in the DDL have zero null values. Covers all primary keys, required business fields (amounts, dates, status), and foreign keys.

### 6.3 Referential Integrity
Uses `LEFT ANTI JOIN` to detect orphaned foreign keys:
- `loan_accounts.borrower_id` must exist in `borrowers.borrower_id`
- `loan_accounts.product_id` must exist in `loan_products.product_id`
- `payments.loan_account_id` must exist in `loan_accounts.loan_account_id`

### 6.4 Business Rule Validation
Domain-specific checks:
- Active loans must have `current_balance > 0`
- All loans must have positive `original_amount`
- Interest rates must be in `[0, 100]`
- `maturity_date` must be after `origination_date`
- LTV percent must be in `[0, 200]` (if present)
- Delinquency days must be `>= 0`
- Loan status values must be in `{ACTIVE, CLOSED, DEFAULT, FORBEARANCE}`
- Payment amounts must be `>= 0`
- Credit scores must be in `[300, 850]` (if present)
- Annual income must be `>= 0`

The output is a `DATA_QUALITY_REPORT.md` with pass/fail results and violation counts.

---

## 7. Error Handling Strategy

The pipeline follows a **flag-and-continue** approach rather than fail-fast:

1. **Malformed values** (unparseable dates, non-numeric amounts) are coerced to `NULL` by PySpark's cast functions. They are NOT silently dropped.
2. **Unresolved foreign keys** produce `NULL` FK values and are logged as warnings during ingestion.
3. **Invalid rows** are tagged with `_is_valid = false` during transformation but are still written to the target table. This allows the quality framework to report on them and human reviewers to investigate.
4. **Unknown status codes** are preserved as `"UNKNOWN:<code>"` to prevent data loss.

This approach ensures zero data loss during migration while providing full visibility into data issues through the quality report.

---

## 8. Prerequisites

- **Databricks Runtime:** 13.3 LTS or later (for Unity Catalog support)
- **Unity Catalog:** A catalog named `loan_migration` must exist (or adjust `00_create_schema.sql`)
- **Source data:** Legacy table exports in CSV or Parquet format, organized under a base path with subdirectories `cdw_borr_mstr/`, `cdw_ln_prod/`, `cdw_ln_acct/`, `cdw_pmt_hist/`
- **Cluster permissions:** User must have `CREATE TABLE`, `CREATE SCHEMA` privileges on the target catalog

---

## 9. Rollback Procedure

Since all tables use `overwrite` mode by default:

1. **Delta time travel** can restore any table to its pre-migration state:
   ```sql
   RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF 0;
   ```
2. **Full rollback** — drop the entire schema:
   ```sql
   DROP SCHEMA IF EXISTS loan_warehouse CASCADE;
   ```

For incremental loads (using `append` mode), use Delta's `MERGE` capabilities for idempotent upserts keyed on `external_id`, `code`, `account_number`, or `legacy_sequence_nbr`.
