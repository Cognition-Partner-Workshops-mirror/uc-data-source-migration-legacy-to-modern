# Databricks Migration Runbook

## Legacy CDW → Delta Lake Migration

This runbook documents the complete migration pipeline from the legacy Corporate Data Warehouse (CDW) all-VARCHAR H2 tables to properly typed Delta Lake tables in Databricks.

---

## 1. Source System Overview

### Legacy Schema Characteristics

| Property | Value |
|----------|-------|
| Database | H2 (embedded, in-memory) |
| Tables | 4: `CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| All columns | `VARCHAR` — no typed columns |
| Date format | `MM/DD/YYYY` stored as strings |
| Amount format | Comma-separated strings (e.g., `"285,000"`, `"1,487.02"`) |
| Status codes | 3-letter abbreviations (ACT, CLO, DFT, FRB, etc.) |
| Foreign keys | None enforced — referential integrity by convention only |
| Denormalization | Borrower fields duplicated in `CDW_LN_ACCT` |

### Known Data Quality Issues

Refer to `docs/DATA_ANOMALY_REPORT.md` for the full catalog. Key issues:

1. **Payment component sum mismatches** — principal + interest + escrow + late_fee ≠ total for some records
2. **SSN last-4 matching phone suffixes** — likely data entry errors in all 5 borrower records
3. **Delinquent loans with ACT status** — business rule inconsistency
4. **Null values in fields treated as required** — address_line2, middle_initial
5. **No FK constraints** — orphaned records possible

---

## 2. Target Schema Design

### Delta Lake Tables

| Target Table | Source Table | Partition Key | Rationale |
|--------------|-------------|---------------|-----------|
| `loan_warehouse.borrowers` | `CDW_BORR_MSTR` | `status` | Filter active/inactive borrowers efficiently |
| `loan_warehouse.loan_products` | `CDW_LN_PROD` | *(none)* | Small reference table (~10s of rows) |
| `loan_warehouse.loan_accounts` | `CDW_LN_ACCT` | `origination_year` | Time-range queries on loan vintage |
| `loan_warehouse.payments` | `CDW_PMT_HIST` | `payment_year` | Time-range queries on payment history |

### Partitioning Rationale

- **`origination_year`** for loans: Most analytical queries filter by loan vintage (origination cohort analysis, regulatory reporting by year). Cardinality is low (~5-10 distinct years).
- **`payment_year`** for payments: Payment history queries typically span date ranges. Year-level partitioning keeps partition count manageable while enabling predicate pushdown.
- **`status`** for borrowers: Common filter dimension (ACTIVE vs INACTIVE). Only 2 partition values.
- **No partitioning** for loan_products: Reference table with <100 rows; partitioning would add overhead with no benefit.

### Delta Lake Table Properties

All tables use:
- `delta.autoOptimize.optimizeWrite = true` — coalesces small files during writes
- `delta.autoOptimize.autoCompact = true` — triggers compaction automatically

---

## 3. Column Mapping Reference

### CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `BORR_ID` | `borrower_id` | VARCHAR → STRING | Primary key, trimmed |
| `BORR_FST_NM` | `first_name` | VARCHAR → STRING | Trimmed, NOT NULL |
| `BORR_LST_NM` | `last_name` | VARCHAR → STRING | Trimmed, NOT NULL |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR → STRING | Nullable |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR → STRING | Direct copy |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR → STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR → STRING | Nullable |
| `BORR_CTY_NM` | `city` | VARCHAR → STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR → STRING | 2-letter code |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR → STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR → STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR → STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR → INT | `trim().cast(IntegerType)` |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR → STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR → DECIMAL(12,2) | Strip `$`, `,`, whitespace then cast |
| `BORR_STAT_CD` | `status` | VARCHAR → STRING | Expand: ACT→ACTIVE, INA→INACTIVE |
| `BORR_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| `BORR_REC_TYP` | *(dropped)* | — | Not needed in modern schema |

### CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `PROD_CD` | `product_code` | VARCHAR → STRING | Primary key |
| `PROD_DESC_TXT` | `name` | VARCHAR → STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR → STRING | FXD, ARM, FHA, VA |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | `trim().cast(IntegerType)` |
| `PROD_RT_TYP` | `rate_type` | VARCHAR → STRING | FIXED or VARIABLE |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) | Strip commas then cast |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) | Strip commas then cast |
| `PROD_STAT_CD` | `is_active` | VARCHAR → BOOLEAN | ACT→true, INA→false |
| `PROD_EFF_DT` | `effective_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |

### CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `LN_ACCT_NBR` | `account_number` | VARCHAR → STRING | Primary key |
| `BORR_ID` | `borrower_id` | VARCHAR → STRING | FK to borrowers |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_code` | VARCHAR → STRING | FK to loan_products |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) | Strip commas then cast |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) | Strip commas then cast |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | `trim().cast(DecimalType)` |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | `trim().cast(IntegerType)` |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) | Strip commas then cast |
| `LN_ORIG_DT` | `origination_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `LN_MAT_DT` | `maturity_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `LN_STAT_CD` | `status` | VARCHAR → STRING | Expand: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | Default null → 0 |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Strip commas then cast |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | `trim().cast(DecimalType)` |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR → STRING | Expand: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Strip commas then cast |
| *(derived)* | `origination_year` | — → INT | `YEAR(origination_date)` — partition key |
| `LN_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| `LN_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |

### CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `PMT_SEQ_NBR` | `payment_id` | VARCHAR → STRING | Primary key |
| `LN_ACCT_NBR` | `loan_account_number` | VARCHAR → STRING | FK to loan_accounts |
| `PMT_DT` | `payment_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `PMT_AMT` | `total_amount` | VARCHAR → DECIMAL(10,2) | Strip commas then cast |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR → DECIMAL(10,2) | Strip commas then cast |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR → DECIMAL(10,2) | Strip commas then cast |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR → DECIMAL(10,2) | Strip commas then cast |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR → DECIMAL(10,2) | Default null → 0 |
| `PMT_TYP_CD` | `type` | VARCHAR → STRING | Expand: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| `PMT_STAT_CD` | `status` | VARCHAR → STRING | Expand: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| `PMT_RECV_DT` | `received_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `PMT_PROC_DT` | `processed_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| *(derived)* | `component_sum_valid` | — → BOOLEAN | `abs(total - (principal+interest+escrow+late_fee)) <= 0.02` |
| *(derived)* | `payment_year` | — → INT | `YEAR(payment_date)` — partition key |
| `PMT_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |

---

## 4. Transformation Decisions

### 4.1 Date Parsing

**Decision:** Use Spark's `to_date(col, "MM/dd/yyyy")` which returns `null` for unparseable values.

**Rationale:** The legacy system stores dates as `MM/DD/YYYY` strings. Some records contain placeholder dates (`00/00/0000`) or ISO-format dates (`2025-01-15`) that will fail MM/DD/YYYY parsing. Returning null is preferred over crashing the pipeline — null dates are flagged by the data quality framework.

### 4.2 Amount Parsing

**Decision:** Strip `$`, `,`, and whitespace with `regexp_replace`, then cast to `DecimalType(12,2)`.

**Rationale:** Legacy amounts use US formatting with commas as thousands separators. Some amounts contain dollar signs. The regex approach handles all variants in a single pass. Unparseable values become null (caught by DQ checks).

### 4.3 Status Code Expansion

**Decision:** Expand abbreviations using conditional `when/otherwise` chains. Unrecognized codes are preserved as-is.

**Rationale:** Expanded status values are more readable in reports and dashboards. Preserving unrecognized codes (rather than nullifying them) ensures no data loss — the DQ framework will flag them.

| Table | Legacy Code | Expanded Value |
|-------|-------------|----------------|
| borrowers | ACT | ACTIVE |
| borrowers | INA | INACTIVE |
| loan_accounts | ACT | ACTIVE |
| loan_accounts | CLO | CLOSED |
| loan_accounts | DFT | DEFAULT |
| loan_accounts | FRB | FORBEARANCE |
| payments (type) | REG | REGULAR |
| payments (type) | EXT | EXTRA |
| payments (type) | PRT | PARTIAL |
| payments (type) | PRE | PREPAYMENT |
| payments (status) | PST | POSTED |
| payments (status) | REV | REVERSED |
| payments (status) | NSF | NSF |
| payments (status) | PND | PENDING |
| loan_accounts (property) | SFR | Single Family |
| loan_accounts (property) | CND | Condominium |
| loan_accounts (property) | MFR | Multi-Family |
| loan_accounts (property) | TWN | Townhouse |

### 4.4 Denormalization Removal

**Decision:** Drop `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` from the loan_accounts ingestion. Use `borrower_id` FK to join to the borrowers dimension.

**Rationale:** These fields are duplicated from `CDW_BORR_MSTR` into `CDW_LN_ACCT`. In the modern schema, borrower data lives in a single source-of-truth table. This eliminates update anomalies and reduces storage.

### 4.5 Derived Columns

| Column | Table | Derivation |
|--------|-------|------------|
| `origination_year` | loan_accounts | `YEAR(origination_date)` |
| `payment_year` | payments | `YEAR(payment_date)` |
| `component_sum_valid` | payments | `abs(total - components) <= 0.02` |
| `is_active` | loan_products | `PROD_STAT_CD == 'ACT'` |

### 4.6 Null Handling

| Scenario | Decision |
|----------|----------|
| Null delinquency_days | Default to 0 (no delinquency) |
| Null late_fee | Default to 0 (no fee) |
| Null dates | Preserved as null — flagged by DQ |
| Null amounts | Preserved as null — flagged by DQ |
| Null address fields | Preserved as null — no business impact |

### 4.7 Quarantine Pattern

Records that fail required-field null checks are not dropped — they are written to a quarantine path (`dbfs:/mnt/legacy-cdw/quarantine/{table_name}/`) as a separate Delta table. This preserves all source data while keeping the target tables clean.

---

## 5. Execution Order

### Prerequisites

1. Databricks workspace with Unity Catalog enabled
2. Storage account mounted at `dbfs:/mnt/legacy-cdw/`
3. Legacy CDW data exported as CSV files to `dbfs:/mnt/legacy-cdw/{TABLE_NAME}/`
4. Cluster with PySpark and Delta Lake support (DBR 13.3+)

### Step-by-Step Execution

```
Step 1: Create target database
────────────────────────────────
Notebook: databricks/ddl/ (run all 4 DDL files)
Command:  CREATE DATABASE IF NOT EXISTS loan_warehouse;
Then run: 01_borrowers.sql, 02_loan_products.sql, 03_loan_accounts.sql, 04_payments.sql

Step 2: Ingest dimension tables (no dependencies)
──────────────────────────────────────────────────
Notebook: databricks/ingestion/ingest_borrowers.py
Notebook: databricks/ingestion/ingest_loan_products.py
(These can run in parallel)

Step 3: Ingest fact tables (depend on dimensions)
──────────────────────────────────────────────────
Notebook: databricks/ingestion/ingest_loan_accounts.py
  (Depends on: borrowers, loan_products)
Notebook: databricks/ingestion/ingest_payments.py
  (Depends on: loan_accounts)

Step 4: Run data quality checks
────────────────────────────────
Notebook: databricks/quality/data_quality_checks.py
Output:   dbfs:/mnt/legacy-cdw/reports/DATA_QUALITY_REPORT.md

Step 5: Review quarantine tables
────────────────────────────────
Check: dbfs:/mnt/legacy-cdw/quarantine/borrowers/
Check: dbfs:/mnt/legacy-cdw/quarantine/loan_accounts/
Check: dbfs:/mnt/legacy-cdw/quarantine/payments/
```

### Automated Execution

Use `databricks/quality/run_pipeline.py` to execute all steps in order:

```python
# In a Databricks notebook:
%run ./databricks/quality/run_pipeline
```

This orchestrator:
1. Creates the `loan_warehouse` database
2. Ingests all 4 tables in dependency order
3. Runs all data quality checks
4. Generates and writes the quality report

---

## 6. Data Quality Checks

The post-ingestion quality framework (`databricks/quality/data_quality_checks.py`) validates:

### Row Count Reconciliation
- Source row count (from CSV) minus quarantined records equals target Delta table count

### Null Checks (per table)
- **borrowers:** borrower_id, first_name, last_name, status
- **loan_products:** product_code, name, type, term_months, rate_type, is_active
- **loan_accounts:** account_number, borrower_id, product_code, original_amount, current_balance, interest_rate, term_months, monthly_payment, origination_date, maturity_date, status
- **payments:** payment_id, loan_account_number, payment_date, total_amount, type, status

### Referential Integrity
- `loan_accounts.borrower_id` → `borrowers.borrower_id`
- `loan_accounts.product_code` → `loan_products.product_code`
- `payments.loan_account_number` → `loan_accounts.account_number`

### Business Rules
1. Active loans must have positive `current_balance`
2. Closed loans must have a non-null `maturity_date`
3. All loans must have positive `original_amount`
4. All payments must have positive `total_amount`
5. Payment component sums must match total (within $0.02 tolerance)
6. Interest rates must be between 0 and 100
7. No loans originated in the future
8. Loan status codes must be expanded (not abbreviated)
9. Payment status codes must be expanded (not abbreviated)

---

## 7. Lineage Metadata

Every record in the target tables includes:

| Column | Purpose |
|--------|---------|
| `_ingestion_ts` | UTC timestamp of when the record was ingested |
| `_source_file` | Path to the source file the record came from |

These columns enable:
- Identifying records from a specific load
- Debugging data issues back to source files
- Auditing when data was last refreshed

---

## 8. Rollback Procedure

Since Delta Lake supports time travel, rolling back a bad load is straightforward:

```sql
-- View table history
DESCRIBE HISTORY loan_warehouse.loan_accounts;

-- Restore to a previous version
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF <version_number>;

-- Or restore to a timestamp
RESTORE TABLE loan_warehouse.loan_accounts TO TIMESTAMP AS OF '2024-01-15T00:00:00';
```

---

## 9. Post-Migration Validation Queries

```sql
-- Verify row counts match
SELECT 'borrowers' AS table_name, COUNT(*) AS cnt FROM loan_warehouse.borrowers
UNION ALL
SELECT 'loan_products', COUNT(*) FROM loan_warehouse.loan_products
UNION ALL
SELECT 'loan_accounts', COUNT(*) FROM loan_warehouse.loan_accounts
UNION ALL
SELECT 'payments', COUNT(*) FROM loan_warehouse.payments;

-- Check for orphaned loan accounts
SELECT la.account_number, la.borrower_id
FROM loan_warehouse.loan_accounts la
LEFT JOIN loan_warehouse.borrowers b ON la.borrower_id = b.borrower_id
WHERE b.borrower_id IS NULL;

-- Check payment component integrity
SELECT payment_id, total_amount,
       principal_amount + interest_amount + escrow_amount + late_fee AS component_sum,
       component_sum_valid
FROM loan_warehouse.payments
WHERE component_sum_valid = false;

-- Verify status expansion
SELECT DISTINCT status FROM loan_warehouse.loan_accounts;
-- Expected: ACTIVE, CLOSED, DEFAULT, FORBEARANCE (no ACT, CLO, DFT, FRB)
```
