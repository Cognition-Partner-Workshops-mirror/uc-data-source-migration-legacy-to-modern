# Databricks Migration Runbook

## 1. Overview

This runbook documents the migration of the legacy Corporate Data Warehouse (CDW) loan data into a modern, strongly-typed Delta Lake schema on Databricks. It covers every transformation decision, the full column mapping from legacy to modern names, type conversion choices, partitioning rationale, and the recommended execution order.

### Source System

- **Legacy tables:** `CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST`
- **Characteristics:** All columns VARCHAR, dates as `MM/DD/YYYY` strings, amounts as comma-formatted strings (`"285,000"`), cryptic abbreviated column names, denormalized structures, no foreign key constraints, status codes as short abbreviations

### Target System

- **Database:** `loan_warehouse` (Databricks / Delta Lake)
- **Tables:** `borrowers`, `loan_products`, `loan_accounts`, `payments`
- **Format:** Delta Lake with auto-optimize enabled

---

## 2. Column Mappings

### 2.1 CDW_BORR_MSTR -> borrowers

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `BORR_ID` | `external_id` | VARCHAR -> STRING | Direct copy |
| `BORR_FST_NM` | `first_name` | VARCHAR -> STRING | Trimmed |
| `BORR_LST_NM` | `last_name` | VARCHAR -> STRING | Trimmed |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR -> STRING | Direct copy |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR -> STRING | Direct copy (re-encrypt recommended post-migration) |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR `MM/DD/YYYY` -> DATE | Parsed via `to_date()` |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR -> STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR -> STRING | Direct copy |
| `BORR_CTY_NM` | `city` | VARCHAR -> STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR -> STRING | Direct copy |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR -> STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR -> STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR -> STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR -> INT | Cast string to integer |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR -> STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR `"92,500"` -> DECIMAL(12,2) | Remove commas, cast |
| `BORR_STAT_CD` | `status` | VARCHAR -> STRING | Expand: ACT->ACTIVE, INA->INACTIVE |
| `BORR_CRET_DT` | `created_at` | VARCHAR `MM/DD/YYYY` -> TIMESTAMP | Parsed via `to_timestamp()` |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR `MM/DD/YYYY` -> TIMESTAMP | Parsed via `to_timestamp()` |
| `BORR_REC_TYP` | *(dropped)* | — | Internal CDW record type; not needed |
| *(generated)* | `id` | — -> BIGINT | Surrogate key via `monotonically_increasing_id()` |

### 2.2 CDW_LN_PROD -> loan_products

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `PROD_CD` | `code` | VARCHAR -> STRING | Direct copy |
| `PROD_DESC_TXT` | `name` | VARCHAR -> STRING | Trimmed |
| `PROD_TYP_CD` | `type` | VARCHAR -> STRING | Direct copy (FXD, ARM, FHA, VA) |
| `PROD_TERM_MOS` | `term_months` | VARCHAR -> INT | Cast string to integer |
| `PROD_RT_TYP` | `rate_type` | VARCHAR -> STRING | Direct copy (FIXED, VARIABLE) |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR -> DECIMAL(12,2) | Remove commas, cast |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR -> DECIMAL(12,2) | Remove commas, cast |
| `PROD_STAT_CD` | `is_active` | VARCHAR -> BOOLEAN | ACT->true, INA->false |
| `PROD_EFF_DT` | `effective_date` | VARCHAR -> DATE | Parsed via `to_date()` |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR -> DATE | Parsed via `to_date()` |
| *(generated)* | `id` | — -> BIGINT | Surrogate key |

### 2.3 CDW_LN_ACCT -> loan_accounts

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `LN_ACCT_NBR` | `account_number` | VARCHAR -> STRING | Direct copy |
| `BORR_ID` | `borrower_id` | VARCHAR -> BIGINT | FK lookup: `borrowers.external_id` -> `borrowers.id` |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_id` | VARCHAR -> BIGINT | FK lookup: `loan_products.code` -> `loan_products.id` |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR -> DECIMAL(12,2) | Remove commas, cast |
| `LN_CURR_BAL` | `current_balance` | VARCHAR -> DECIMAL(12,2) | Remove commas, cast |
| `LN_INT_RT` | `interest_rate` | VARCHAR -> DECIMAL(5,3) | Cast string |
| `LN_TERM_MOS` | `term_months` | VARCHAR -> INT | Cast string |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR -> DECIMAL(10,2) | Remove commas, cast |
| `LN_ORIG_DT` | `origination_date` | VARCHAR -> DATE | Parsed via `to_date()` |
| `LN_MAT_DT` | `maturity_date` | VARCHAR -> DATE | Parsed via `to_date()` |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR -> DATE | Parsed via `to_date()` |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR -> DATE | Parsed via `to_date()` |
| `LN_STAT_CD` | `status` | VARCHAR -> STRING | ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR -> INT | Cast string |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR -> DECIMAL(10,2) | Remove commas, cast |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR -> DECIMAL(5,2) | Cast string |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR -> STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR -> STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR -> STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR -> STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR -> STRING | SFR->Single Family, CND->Condominium, MFR->Multi-Family, TWN->Townhouse |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR -> DECIMAL(12,2) | Remove commas, cast |
| `LN_CRET_DT` | `created_at` | VARCHAR -> TIMESTAMP | Parsed via `to_timestamp()` |
| `LN_UPDT_DT` | `updated_at` | VARCHAR -> TIMESTAMP | Parsed via `to_timestamp()` |
| *(derived)* | `origination_year` | — -> INT | `year(origination_date)` for analytics |
| *(generated)* | `id` | — -> BIGINT | Surrogate key |

### 2.4 CDW_PMT_HIST -> payments

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `PMT_SEQ_NBR` | `legacy_sequence_number` | VARCHAR -> STRING | Preserved for traceability |
| `LN_ACCT_NBR` | `loan_account_id` | VARCHAR -> BIGINT | FK lookup: `loan_accounts.account_number` -> `loan_accounts.id` |
| `PMT_DT` | `payment_date` | VARCHAR -> DATE | Parsed via `to_date()` |
| `PMT_AMT` | `total_amount` | VARCHAR -> DECIMAL(10,2) | Remove commas, cast |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR -> DECIMAL(10,2) | Remove commas, cast |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR -> DECIMAL(10,2) | Remove commas, cast |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR -> DECIMAL(10,2) | Remove commas, cast |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR -> DECIMAL(10,2) | Remove commas, cast |
| `PMT_TYP_CD` | `type` | VARCHAR -> STRING | REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT |
| `PMT_STAT_CD` | `status` | VARCHAR -> STRING | PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING |
| `PMT_RECV_DT` | `received_date` | VARCHAR -> DATE | Parsed via `to_date()` |
| `PMT_PROC_DT` | `processed_date` | VARCHAR -> DATE | Parsed via `to_date()` |
| `PMT_CRET_DT` | `created_at` | VARCHAR -> TIMESTAMP | Parsed via `to_timestamp()` |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR -> TIMESTAMP | Parsed via `to_timestamp()` |
| *(generated)* | `id` | — -> BIGINT | Surrogate key |

---

## 3. Transformation Decisions

### 3.1 Date Parsing

- **Format:** All legacy dates use `MM/DD/YYYY` string format.
- **Target type:** `DATE` for business dates (DOB, origination, payment), `TIMESTAMP` for audit fields (created_at, updated_at) set to midnight.
- **PySpark function:** `F.to_date(col, "MM/dd/yyyy")` and `F.to_timestamp(col, "MM/dd/yyyy")`.
- **Null handling:** Unparseable dates become `null` and are flagged via `_has_quality_issue`. No records are dropped.

### 3.2 Amount Parsing

- **Format:** Legacy amounts are comma-formatted strings (e.g., `"285,000"`, `"271,432.56"`).
- **Approach:** Strip commas with `regexp_replace(col, ",", "")` then `.cast(DecimalType(p,s))`.
- **Precision choices:**
  - Loan amounts, balances, appraised values: `DECIMAL(12,2)` (up to $9.99 billion)
  - Payment amounts, fees: `DECIMAL(10,2)` (up to $99.99 million)
  - Interest rates: `DECIMAL(5,3)` (e.g., `5.250`)
  - LTV percentages: `DECIMAL(5,2)` (e.g., `82.50`)

### 3.3 Status Code Expansion

| Domain | Code | Expanded Value |
|--------|------|---------------|
| Loan status | ACT | ACTIVE |
| Loan status | CLO | CLOSED |
| Loan status | DFT | DEFAULT |
| Loan status | FRB | FORBEARANCE |
| Borrower status | ACT | ACTIVE |
| Borrower status | INA | INACTIVE |
| Product status | ACT | true (is_active) |
| Product status | INA | false (is_active) |
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

- **Unknown codes:** Preserved with a `_UNKNOWN` suffix (e.g., `XYZ_UNKNOWN`) so they appear in quality reports rather than being silently lost.

### 3.4 Denormalization Removal (Borrower Split)

The legacy `CDW_LN_ACCT` table embeds borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) directly in the loan record. In the modern schema:

1. These three columns are **dropped** from `loan_accounts`.
2. The `BORR_ID` is resolved to a `borrower_id` (BIGINT FK) by joining against the `borrowers` table on `external_id`.
3. Similarly, `PROD_CD` is resolved to a `product_id` FK by joining against `loan_products` on `code`.
4. Unresolvable FKs are logged as warnings and flagged — records are **not** dropped.

### 3.5 Surrogate Key Generation

All target tables use `monotonically_increasing_id()` for the `id` column. This is suitable for batch migration. For incremental loads, consider switching to a sequence generator or UUID.

### 3.6 Quality Flagging (No Silent Drops)

Every ingestion script adds a transient `_has_quality_issue` boolean column that is `True` when any required field is null after transformation. This column is used for reporting but is **stripped before writing** to Delta. All records are preserved in the target — nothing is silently dropped.

---

## 4. Partitioning Strategy

| Table | Partition Column(s) | Rationale |
|-------|-------------------|-----------|
| `borrowers` | `status` | Low cardinality (ACTIVE, INACTIVE). Supports common filtered queries on borrower status. |
| `loan_products` | *(none)* | Small reference/dimension table (< 100 rows). Partitioning would cause overhead with tiny files. |
| `loan_accounts` | `status` | Low cardinality (ACTIVE, CLOSED, DEFAULT, FORBEARANCE). Most analytics queries filter by loan status. |
| `payments` | `status` | Low cardinality (POSTED, REVERSED, NSF, PENDING). Reconciliation queries almost always filter by payment status. |

**Why status over origination_year?**

- Status-based partitioning yields 2-4 partitions (manageable file sizes).
- Origination year could yield 10+ partitions, some very small (e.g., only a few loans in 2017).
- Status is the most common filter predicate in downstream analytics and reporting queries.
- `origination_year` is available as a derived column in `loan_accounts` for ad-hoc queries without partition overhead.
- Delta Lake's auto-optimize and Z-ordering can handle secondary access patterns efficiently.

**Delta Lake table properties:**

- `delta.autoOptimize.optimizeWrite = true` — coalesces small files automatically.
- `delta.autoOptimize.autoCompact = true` — compacts files in the background.

---

## 5. Recommended Execution Order

### Prerequisites

1. Databricks workspace with Unity Catalog or Hive metastore configured.
2. Legacy source files (CSV or Parquet) available at `/mnt/legacy/` (or configure alternative path).
3. Delta Lake storage path `/mnt/delta/loan_warehouse/` accessible.

### Step-by-Step Execution

```
Step 1: Create the database and all Delta tables
────────────────────────────────────────────────
Run: databricks/schemas/create_tables.py
  - Creates loan_warehouse database
  - Creates borrowers, loan_products, loan_accounts, payments tables

Step 2: Run ingestion pipeline
──────────────────────────────
Run: databricks/ingestion/run_ingestion.py --source-dir /mnt/legacy --format csv
  - Step 2a: Ingest borrowers    (CDW_BORR_MSTR -> borrowers)
  - Step 2b: Ingest loan_products (CDW_LN_PROD -> loan_products)
  - Step 2c: Ingest loan_accounts (CDW_LN_ACCT -> loan_accounts)
             ↳ depends on borrowers + loan_products for FK resolution
  - Step 2d: Ingest payments      (CDW_PMT_HIST -> payments)
             ↳ depends on loan_accounts for FK resolution

Step 3: Run data quality checks
────────────────────────────────
Run: databricks/quality/run_quality_checks.py --source-dir /mnt/legacy --format csv
  - Row count reconciliation (4 checks)
  - Null checks on required fields (25 checks)
  - Referential integrity (3 checks)
  - Business rule validation (6 checks)
  - Generates DATA_QUALITY_REPORT.md

Step 4: Review quality report
─────────────────────────────
  - Check DATA_QUALITY_REPORT.md for any FAIL results
  - Investigate and remediate any issues
  - Re-run quality checks after fixes
```

### Databricks Notebook Execution

```python
# Cell 1: Create tables
%run ./databricks/schemas/create_tables

# Cell 2: Run ingestion
%run ./databricks/ingestion/run_ingestion

# Cell 3: Run quality checks
%run ./databricks/quality/run_quality_checks
```

### Databricks Job Configuration

For production use, configure a multi-task Databricks job:

| Task | Script | Depends On |
|------|--------|------------|
| `create_tables` | `databricks/schemas/create_tables.py` | — |
| `ingest_borrowers` | `databricks/ingestion/ingest_borrowers.py` | `create_tables` |
| `ingest_loan_products` | `databricks/ingestion/ingest_loan_products.py` | `create_tables` |
| `ingest_loan_accounts` | `databricks/ingestion/ingest_loan_accounts.py` | `ingest_borrowers`, `ingest_loan_products` |
| `ingest_payments` | `databricks/ingestion/ingest_payments.py` | `ingest_loan_accounts` |
| `quality_checks` | `databricks/quality/run_quality_checks.py` | `ingest_payments` |

---

## 6. Data Quality Checks

The quality framework (`databricks/quality/`) runs the following checks after ingestion:

### 6.1 Row Count Reconciliation
- Source CSV/Parquet row count must equal Delta target row count for each table.

### 6.2 Null Checks
- Required fields must have zero nulls:
  - **borrowers:** external_id, first_name, last_name, status
  - **loan_products:** code, name, type, term_months, rate_type
  - **loan_accounts:** account_number, borrower_id, product_id, original_amount, current_balance, interest_rate, term_months, monthly_payment, origination_date, maturity_date, status
  - **payments:** loan_account_id, payment_date, total_amount, type, status

### 6.3 Referential Integrity
- Every `loan_accounts.borrower_id` must exist in `borrowers.id`
- Every `loan_accounts.product_id` must exist in `loan_products.id`
- Every `payments.loan_account_id` must exist in `loan_accounts.id`

### 6.4 Business Rules
- Active loans must have `current_balance > 0`
- Closed loans must have a non-null `maturity_date`
- Posted payments must have `total_amount > 0`
- Payment components (`principal + interest + escrow + late_fee`) must approximately equal `total_amount` (tolerance: $0.01)
- `origination_date < maturity_date` for all loans
- Interest rate must be between 0% and 30%

---

## 7. Rollback Procedure

If the migration needs to be reverted:

1. **Delta Lake time travel:** Each table supports time travel. Roll back to the pre-migration version:
   ```sql
   RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF 0;
   RESTORE TABLE loan_warehouse.loan_products TO VERSION AS OF 0;
   RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF 0;
   RESTORE TABLE loan_warehouse.payments TO VERSION AS OF 0;
   ```

2. **Full drop and recreate:** If needed, drop the entire warehouse and re-create:
   ```sql
   DROP DATABASE IF EXISTS loan_warehouse CASCADE;
   ```

---

## 8. Post-Migration Considerations

1. **SSN re-encryption:** The `ssn_hash` column is copied as-is. Consider re-encrypting with a modern algorithm.
2. **Incremental loads:** The current pipeline is designed for full-refresh (overwrite mode). For ongoing incremental updates, consider:
   - Using Delta Lake MERGE (upsert) instead of overwrite
   - Implementing change data capture (CDC) from the legacy system
   - Switching surrogate keys from `monotonically_increasing_id()` to a deterministic hash or sequence
3. **Z-ordering:** For large datasets, consider Z-ordering on frequently filtered columns:
   ```sql
   OPTIMIZE loan_warehouse.loan_accounts ZORDER BY (origination_year, borrower_id);
   OPTIMIZE loan_warehouse.payments ZORDER BY (payment_date, loan_account_id);
   ```
4. **Statistics collection:** After initial load, run `ANALYZE TABLE` to update statistics for query optimization.
