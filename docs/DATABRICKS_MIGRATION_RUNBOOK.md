# Databricks Migration Runbook: CDW Legacy to Delta Lake

## 1. Overview

This runbook documents the complete migration of loan servicing data from a legacy Corporate Data Warehouse (CDW) system to a modern Databricks Delta Lake warehouse.

### Migration Scope

| Metric | Value |
|--------|-------|
| Source system | CDW (Corporate Data Warehouse) — H2/SQL |
| Target system | Databricks Delta Lake |
| Source tables | 4 (`CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST`) |
| Target tables | 4 (`borrowers`, `loan_products`, `loan_accounts`, `payments`) |
| Legacy characteristics | All-VARCHAR columns, MM/DD/YYYY dates, comma-formatted amounts, cryptic names, denormalized structures |
| Target characteristics | Proper Spark SQL types, normalized schema, Delta Lake format with auto-optimize |

---

## 2. Column Mapping Reference

### 2.1 CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `BORR_ID` | `external_id` | VARCHAR(20) → STRING | Direct copy |
| `BORR_FST_NM` | `first_name` | VARCHAR(50) → STRING | Direct copy |
| `BORR_LST_NM` | `last_name` | VARCHAR(50) → STRING | Direct copy |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR(1) → STRING | Direct copy |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR(100) → STRING | Direct copy (re-encrypt recommended) |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR(10) → DATE | Parse MM/DD/YYYY → DATE |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR(100) → STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR(100) → STRING | Direct copy |
| `BORR_CTY_NM` | `city` | VARCHAR(50) → STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR(2) → STRING | Direct copy |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR(10) → STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR(15) → STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR(100) → STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR(5) → INT | Parse string → integer |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR(20) → STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR(15) → DECIMAL(12,2) | Strip commas, parse to decimal |
| `BORR_CRET_DT` | `created_at` | VARCHAR(10) → TIMESTAMP | Parse MM/DD/YYYY → TIMESTAMP |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR(10) → TIMESTAMP | Parse MM/DD/YYYY → TIMESTAMP |
| `BORR_STAT_CD` | `status` | VARCHAR(5) → STRING | Expand: ACT→ACTIVE, INA→INACTIVE |
| `BORR_REC_TYP` | *(dropped)* | — | Not needed in modern schema |

### 2.2 CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PROD_CD` | `code` | VARCHAR(10) → STRING | Direct copy (natural key) |
| `PROD_DESC_TXT` | `name` | VARCHAR(200) → STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR(5) → STRING | Direct copy |
| `PROD_TERM_MOS` | `term_months` | VARCHAR(5) → INT | Parse string → integer |
| `PROD_RT_TYP` | `rate_type` | VARCHAR(10) → STRING | Direct copy |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR(15) → DECIMAL(12,2) | Strip commas, parse to decimal |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR(15) → DECIMAL(12,2) | Strip commas, parse to decimal |
| `PROD_STAT_CD` | `is_active` | VARCHAR(5) → BOOLEAN | ACT→true, INA→false |
| `PROD_EFF_DT` | `effective_date` | VARCHAR(10) → DATE | Parse MM/DD/YYYY → DATE |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR(10) → DATE | Parse MM/DD/YYYY → DATE |

### 2.3 CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `LN_ACCT_NBR` | `account_number` | VARCHAR(20) → STRING | Direct copy (natural key) |
| `BORR_ID` | `borrower_id` | VARCHAR(20) → STRING | FK to borrowers.external_id |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_code` | VARCHAR(10) → STRING | FK to loan_products.code |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR(15) → DECIMAL(12,2) | Strip commas, parse to decimal |
| `LN_CURR_BAL` | `current_balance` | VARCHAR(15) → DECIMAL(12,2) | Strip commas, parse to decimal |
| `LN_INT_RT` | `interest_rate` | VARCHAR(8) → DECIMAL(5,3) | Parse string → decimal |
| `LN_TERM_MOS` | `term_months` | VARCHAR(5) → INT | Parse string → integer |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR(15) → DECIMAL(10,2) | Strip commas, parse to decimal |
| `LN_ORIG_DT` | `origination_date` | VARCHAR(10) → DATE | Parse MM/DD/YYYY → DATE |
| `LN_MAT_DT` | `maturity_date` | VARCHAR(10) → DATE | Parse MM/DD/YYYY → DATE |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR(10) → DATE | Parse MM/DD/YYYY → DATE |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR(10) → DATE | Parse MM/DD/YYYY → DATE |
| `LN_STAT_CD` | `status` | VARCHAR(5) → STRING | Expand: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR(5) → INT | Parse string → integer |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR(15) → DECIMAL(10,2) | Strip commas, parse to decimal |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR(8) → DECIMAL(5,2) | Parse string → decimal |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR(100) → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR(50) → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR(2) → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR(10) → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR(10) → STRING | Expand: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR(15) → DECIMAL(12,2) | Strip commas, parse to decimal |
| `LN_CRET_DT` | `created_at` | VARCHAR(10) → TIMESTAMP | Parse MM/DD/YYYY → TIMESTAMP |
| `LN_UPDT_DT` | `updated_at` | VARCHAR(10) → TIMESTAMP | Parse MM/DD/YYYY → TIMESTAMP |

### 2.4 CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PMT_SEQ_NBR` | `payment_sequence` | VARCHAR(20) → STRING | Direct copy (natural key) |
| `LN_ACCT_NBR` | `loan_account_number` | VARCHAR(20) → STRING | FK to loan_accounts.account_number |
| `PMT_DT` | `payment_date` | VARCHAR(10) → DATE | Parse MM/DD/YYYY → DATE |
| `PMT_AMT` | `total_amount` | VARCHAR(15) → DECIMAL(10,2) | Strip commas, parse to decimal |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR(15) → DECIMAL(10,2) | Strip commas, parse to decimal |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR(15) → DECIMAL(10,2) | Strip commas, parse to decimal |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR(15) → DECIMAL(10,2) | Strip commas, parse to decimal |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR(15) → DECIMAL(10,2) | Strip commas, parse to decimal |
| `PMT_TYP_CD` | `type` | VARCHAR(5) → STRING | Expand: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| `PMT_STAT_CD` | `status` | VARCHAR(5) → STRING | Expand: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| `PMT_RECV_DT` | `received_date` | VARCHAR(10) → DATE | Parse MM/DD/YYYY → DATE |
| `PMT_PROC_DT` | `processed_date` | VARCHAR(10) → DATE | Parse MM/DD/YYYY → DATE |
| `PMT_CRET_DT` | `created_at` | VARCHAR(10) → TIMESTAMP | Parse MM/DD/YYYY → TIMESTAMP |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR(10) → TIMESTAMP | Parse MM/DD/YYYY → TIMESTAMP |

---

## 3. Transformation Rules

### 3.1 Date Parsing (MM/DD/YYYY → DATE or TIMESTAMP)

All legacy date columns store dates as `VARCHAR(10)` strings in `MM/DD/YYYY` format.

```python
# Date parsing — returns null on failure, flags error in companion column
from pyspark.sql import functions as F

parsed = F.to_date(F.col("BORR_DOB_DT"), "MM/dd/yyyy").alias("date_of_birth")

# Error flag — True when non-null value fails to parse
flag = (
    F.when(F.col("BORR_DOB_DT").isNull(), F.lit(False))
    .when(F.to_date(F.col("BORR_DOB_DT"), "MM/dd/yyyy").isNull(), F.lit(True))
    .otherwise(F.lit(False))
    .alias("_err_BORR_DOB_DT")
)
```

For TIMESTAMP columns (`created_at`, `updated_at`), `to_timestamp()` is used instead of `to_date()`.

### 3.2 Amount Parsing (comma-formatted string → DECIMAL)

Legacy amount columns store values like `"285,000"`, `"271,432.56"`, and `"0.00"`.

```python
# Strip commas and cast to appropriate DecimalType
parsed = (
    F.regexp_replace(F.col("LN_ORIG_AMT"), ",", "")
    .cast("decimal(12,2)")
    .alias("original_amount")
)
```

**DECIMAL precision guidelines:**
- `DECIMAL(12,2)` — Large dollar amounts (loan amounts, balances, appraised values, income)
- `DECIMAL(10,2)` — Payment-sized amounts (monthly payments, payment components)
- `DECIMAL(5,3)` — Interest rates (e.g., 4.750)
- `DECIMAL(5,2)` — Percentages (e.g., LTV 82.5%)

### 3.3 Status Code Expansion

Legacy status codes are cryptic abbreviations. The pipeline expands them to readable values:

| Domain | Code | Expanded Value |
|--------|------|----------------|
| Borrower status | ACT | ACTIVE |
| Borrower status | INA | INACTIVE |
| Loan status | ACT | ACTIVE |
| Loan status | CLO | CLOSED |
| Loan status | DFT | DEFAULT |
| Loan status | FRB | FORBEARANCE |
| Payment type | REG | REGULAR |
| Payment type | EXT | EXTRA |
| Payment type | PRT | PARTIAL |
| Payment type | PRE | PREPAYMENT |
| Payment status | PST | POSTED |
| Payment status | REV | REVERSED |
| Payment status | NSF | NSF |
| Payment status | PND | PENDING |
| Product status | ACT | true (boolean) |
| Product status | INA | false (boolean) |
| Property type | SFR | Single Family |
| Property type | CND | Condominium |
| Property type | MFR | Multi-Family |
| Property type | TWN | Townhouse |

**Unmapped codes** are preserved as-is and flagged in a companion `_err_*` column. They are never silently dropped.

### 3.4 Denormalization Removal

The legacy `CDW_LN_ACCT` table duplicates borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`). These are explicitly dropped during ingestion. The modern `loan_accounts` table uses `borrower_id` as a natural-key FK to `borrowers.external_id`.

---

## 4. Partitioning Strategy

| Table | Partition Column | Rationale |
|-------|-----------------|-----------|
| `borrowers` | `status` | Low-cardinality (ACTIVE/INACTIVE); most queries filter by active borrowers |
| `loan_products` | *(none)* | Small reference table (~10s of rows); partitioning adds overhead without benefit |
| `loan_accounts` | `status` | Low-cardinality (ACTIVE/CLOSED/DEFAULT/FORBEARANCE); common filter for loan status queries |
| `payments` | `payment_year_month` (YYYY-MM) | Time-based partitioning for transaction data; enables efficient range scans on payment dates |

All tables use Delta Lake auto-optimize properties:
- `delta.autoOptimize.optimizeWrite = true` — coalesces small files on write
- `delta.autoOptimize.autoCompact = true` — merges small files in background

---

## 5. Step-by-Step Execution Order

### 5.1 Prerequisites

1. Databricks workspace with cluster running
2. Landing zone mounted at `/mnt/landing/cdw/` with source CSV/Parquet files:
   - `/mnt/landing/cdw/CDW_BORR_MSTR/`
   - `/mnt/landing/cdw/CDW_LN_PROD/`
   - `/mnt/landing/cdw/CDW_LN_ACCT/`
   - `/mnt/landing/cdw/CDW_PMT_HIST/`
3. Report output directory exists: `/mnt/reports/`

### 5.2 Step 1: Create Database and Tables (DDL)

Run DDL scripts in dependency order:

```bash
# 1. Create the database
databricks sql execute --file databricks/ddl/create_database.sql

# 2. Create dimension/reference tables (no dependencies)
databricks sql execute --file databricks/ddl/borrowers.sql
databricks sql execute --file databricks/ddl/loan_products.sql

# 3. Create core fact table (depends on borrowers, loan_products)
databricks sql execute --file databricks/ddl/loan_accounts.sql

# 4. Create transaction table (depends on loan_accounts)
databricks sql execute --file databricks/ddl/payments.sql
```

### 5.3 Step 2: Extract Source Data

Export legacy CDW tables to CSV or Parquet format and place them in the landing zone:

```bash
# Example: extract from legacy database to CSV
# Adjust connection details for your environment
CDW_BORR_MSTR → /mnt/landing/cdw/CDW_BORR_MSTR/
CDW_LN_PROD   → /mnt/landing/cdw/CDW_LN_PROD/
CDW_LN_ACCT   → /mnt/landing/cdw/CDW_LN_ACCT/
CDW_PMT_HIST  → /mnt/landing/cdw/CDW_PMT_HIST/
```

### 5.4 Step 3: Run Ingestion Pipeline

Use the orchestrator to run all table ingestions in dependency order:

```bash
# Full ingestion — runs borrowers, loan_products, loan_accounts, payments in order
spark-submit databricks/ingestion/run_full_ingestion.py \
    --base-path /mnt/landing/cdw \
    --database loan_warehouse
```

Or run individual table scripts for targeted re-ingestion:

```bash
# Individual table ingestion
spark-submit databricks/ingestion/ingest_borrowers.py \
    --input /mnt/landing/cdw/CDW_BORR_MSTR \
    --output loan_warehouse.borrowers

spark-submit databricks/ingestion/ingest_loan_products.py \
    --input /mnt/landing/cdw/CDW_LN_PROD \
    --output loan_warehouse.loan_products

spark-submit databricks/ingestion/ingest_loan_accounts.py \
    --input /mnt/landing/cdw/CDW_LN_ACCT \
    --output loan_warehouse.loan_accounts

spark-submit databricks/ingestion/ingest_payments.py \
    --input /mnt/landing/cdw/CDW_PMT_HIST \
    --output loan_warehouse.payments
```

### 5.5 Step 4: Run Data Quality Checks

```bash
spark-submit databricks/quality/data_quality_checks.py \
    --database loan_warehouse \
    --source-path /mnt/landing/cdw \
    --report-path /mnt/reports
```

Review the generated `DATA_QUALITY_REPORT.md` for any FAIL or WARN results.

---

## 6. Dependency Graph

```
CDW_BORR_MSTR ──→ borrowers ─────────┐
                                       ├──→ loan_accounts ──→ payments
CDW_LN_PROD ───→ loan_products ──────┘         ↑
                                                │
CDW_LN_ACCT ────────────────────────────────────┘
                                                ↑
CDW_PMT_HIST ───────────────────────────────────┘
```

**Load order:**
1. `borrowers` (dimension — no dependencies)
2. `loan_products` (reference — no dependencies)
3. `loan_accounts` (depends on borrowers, loan_products for FK validation)
4. `payments` (depends on loan_accounts for FK validation)

Steps 1 and 2 can run in parallel. Step 3 must wait for both 1 and 2. Step 4 must wait for step 3.

---

## 7. Data Quality Check Descriptions

### 7.1 Row Count Reconciliation
Compares the number of rows in each source landing zone file against the corresponding Delta table. Counts must match exactly.

### 7.2 Null Checks on Required Fields
Verifies that columns defined as NOT NULL in the DDL contain zero null values:
- **borrowers**: `external_id`, `first_name`, `last_name`
- **loan_products**: `code`, `name`, `type`, `term_months`, `rate_type`
- **loan_accounts**: `account_number`, `borrower_id`, `product_code`, `original_amount`, `current_balance`, `interest_rate`, `term_months`, `monthly_payment`, `origination_date`, `maturity_date`
- **payments**: `payment_sequence`, `loan_account_number`, `payment_date`, `total_amount`, `type`, `status`

### 7.3 Referential Integrity
Validates that all FK references resolve to existing parent records:
- `loan_accounts.borrower_id` → `borrowers.external_id`
- `loan_accounts.product_code` → `loan_products.code`
- `payments.loan_account_number` → `loan_accounts.account_number`

### 7.4 Business Rule Validations

| # | Rule | Table | Severity |
|---|------|-------|----------|
| 1 | Active loans must have positive current balances | loan_accounts | FAIL |
| 2 | Origination date must be before maturity date | loan_accounts | FAIL |
| 3 | LTV percent must be in valid range (0–200%) | loan_accounts | WARN |
| 4 | Credit score must be in valid range (300–850) | borrowers | WARN |
| 5 | Payment component amounts must sum to total (tolerance: 0.02) | payments | FAIL |
| 6 | Product min_amount must be ≤ max_amount | loan_products | FAIL |
| 7 | Payment received_date must be ≤ processed_date | payments | WARN |

---

## 8. Operational Procedures

### 8.1 Initial Full Load

Follow the step-by-step execution order in Section 5. This performs a clean load of all data into empty Delta tables.

### 8.2 Incremental Loads (Delta MERGE for Upserts)

For ongoing incremental loads after the initial migration, use Delta Lake `MERGE` statements to upsert new/changed records:

```sql
-- Example: incremental upsert for borrowers
MERGE INTO loan_warehouse.borrowers AS target
USING staging.borrowers_incremental AS source
ON target.external_id = source.external_id
WHEN MATCHED THEN
    UPDATE SET
        target.first_name = source.first_name,
        target.last_name = source.last_name,
        target.credit_score = source.credit_score,
        target.annual_income = source.annual_income,
        target.status = source.status,
        target.updated_at = source.updated_at,
        target._migration_source = source._migration_source,
        target._migrated_at = current_timestamp()
WHEN NOT MATCHED THEN
    INSERT *;
```

```sql
-- Example: incremental upsert for payments
MERGE INTO loan_warehouse.payments AS target
USING staging.payments_incremental AS source
ON target.payment_sequence = source.payment_sequence
WHEN MATCHED THEN
    UPDATE SET *
WHEN NOT MATCHED THEN
    INSERT *;
```

### 8.3 Rollback via Delta Time Travel

Delta Lake maintains a history of all changes, enabling safe rollback if a migration run produces incorrect data:

```sql
-- View table history to find the version before a bad load
DESCRIBE HISTORY loan_warehouse.borrowers;

-- Restore to a specific version
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF 3;

-- Or restore to a specific timestamp
RESTORE TABLE loan_warehouse.borrowers TO TIMESTAMP AS OF '2026-05-01T00:00:00Z';
```

**Important:** Always check `DESCRIBE HISTORY` before restoring to confirm the correct version. Delta time travel retains 30 days of history by default.

---

## 9. Troubleshooting Guide

### 9.1 Date Parse Failures

**Symptom:** `_err_*` columns flagged as `True` for date fields; null values in date columns where data was expected.

**Cause:** Source data contains dates not in `MM/DD/YYYY` format (e.g., `YYYY-MM-DD`, `DD/MM/YYYY`, or malformed strings).

**Resolution:**
1. Check the ingestion log output for error counts and sample values
2. Identify the non-standard format(s) in the source data
3. Update `transform_utils.parse_date()` to handle additional formats using `F.coalesce()` with multiple `F.to_date()` calls
4. Re-run the affected table's ingestion script

### 9.2 Amount Format Issues

**Symptom:** Null values in decimal columns; `_err_*` flags for amount fields.

**Cause:** Source amounts contain unexpected characters (currency symbols, spaces, parentheses for negatives).

**Resolution:**
1. Review the flagged sample values in the ingestion log
2. Extend the `regexp_replace` in `transform_utils.parse_amount()` to strip additional characters (e.g., `$`, `(`, `)`)
3. Re-run the affected ingestion

### 9.3 Unmapped Status Codes

**Symptom:** `_err_*` flags for status columns; status values appear as the original abbreviation instead of the expanded form.

**Cause:** The source data contains status codes not included in the mapping dictionaries.

**Resolution:**
1. Identify the unmapped codes from the ingestion log
2. Add the new code-to-value mappings in `transform_utils.py` (e.g., add to `LOAN_STATUS_MAP`)
3. Re-run the affected ingestion

### 9.4 Row Count Mismatches

**Symptom:** Data quality check reports different counts between source and target.

**Cause:** Possible duplicate records in source, failed writes, or schema evolution conflicts.

**Resolution:**
1. Check if the Delta table was written to in append mode multiple times (causing duplicates)
2. If duplicates exist, use `RESTORE TABLE ... TO VERSION AS OF` to roll back, then re-run
3. Verify source file integrity (row counts, header rows, encoding)

### 9.5 FK Integrity Failures

**Symptom:** Referential integrity check reports orphan records.

**Cause:** Dimension tables loaded incompletely, or source data has references to records not in the extract.

**Resolution:**
1. Verify dimension tables (`borrowers`, `loan_products`) were loaded before fact tables
2. Check if the source extract is complete — missing parent records may need to be extracted separately
3. For known orphans, document them and decide whether to quarantine or create placeholder parent records
