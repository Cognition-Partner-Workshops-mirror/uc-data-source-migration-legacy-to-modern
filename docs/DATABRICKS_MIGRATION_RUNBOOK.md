# Databricks Migration Runbook

## CDW Legacy → Delta Lake (Loan Management System)

**Version:** 1.0
**Date:** 2026-05-07
**Scope:** Full migration of 4 legacy CDW tables to Delta Lake on Databricks

---

## 1. Overview

This runbook documents the migration of a loan management application's data from a legacy Corporate Data Warehouse (CDW) to a modern Delta Lake schema on Databricks. The legacy system stores all data as VARCHAR strings with cryptic abbreviated column names, no foreign keys, and denormalized structures. The target schema uses proper Spark SQL types, meaningful names, and referential integrity.

### Source Tables

| Legacy Table | Description | Row Volume (seed) |
|---|---|---|
| `CDW_BORR_MSTR` | Borrower master | 5 |
| `CDW_LN_PROD` | Loan product definitions | 5 |
| `CDW_LN_ACCT` | Loan accounts (denormalized) | 5 |
| `CDW_PMT_HIST` | Payment history | 10 |

### Target Tables

| Delta Lake Table | Description | Partition Column |
|---|---|---|
| `loan_warehouse.borrowers` | Borrower dimension | `state` |
| `loan_warehouse.loan_products` | Product reference | *(none — low cardinality)* |
| `loan_warehouse.loan_accounts` | Loan accounts fact | `status` |
| `loan_warehouse.payments` | Payment history | `payment_year` |

---

## 2. Column Mappings

### 2.1 CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `BORR_ID` | `external_id` | STRING (direct) | Unique legacy identifier |
| `BORR_FST_NM` | `first_name` | STRING (direct) | |
| `BORR_LST_NM` | `last_name` | STRING (direct) | |
| `BORR_MID_INIT` | `middle_initial` | STRING (direct) | Nullable |
| `BORR_SSN_ENCR` | `ssn_hash` | STRING (direct) | Re-encryption recommended |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `BORR_ADDR_LN1` | `address_line1` | STRING (direct) | |
| `BORR_ADDR_LN2` | `address_line2` | STRING (direct) | Nullable |
| `BORR_CTY_NM` | `city` | STRING (direct) | |
| `BORR_ST_CD` | `state` | STRING (direct) | Partition key |
| `BORR_ZIP_CD` | `zip_code` | STRING (direct) | |
| `BORR_PH_NBR` | `phone` | STRING (direct) | |
| `BORR_EMAIL_ADDR` | `email` | STRING (direct) | |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR → INT | Strip non-numeric |
| `BORR_EMP_STAT` | `employment_status` | STRING (direct) | |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR → DECIMAL(12,2) | Remove commas |
| `BORR_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `BORR_STAT_CD` | `status` | Code expansion | ACT→ACTIVE, INA→INACTIVE |
| `BORR_REC_TYP` | *(dropped)* | — | Not needed in modern schema |

### 2.2 CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `PROD_CD` | `code` | STRING (direct) | Unique product code |
| `PROD_DESC_TXT` | `name` | STRING (direct) | |
| `PROD_TYP_CD` | `type` | STRING (direct) | FXD, ARM, FHA, VA |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | |
| `PROD_RT_TYP` | `rate_type` | STRING (direct) | FIXED, VARIABLE |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) | Remove commas |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) | Remove commas |
| `PROD_STAT_CD` | `is_active` | Code → BOOLEAN | ACT→true, INA→false |
| `PROD_EFF_DT` | `effective_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |

### 2.3 CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `LN_ACCT_NBR` | `account_number` | STRING (direct) | |
| `BORR_ID` | `borrower_external_id` | STRING (direct) | FK to borrowers.external_id |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use FK |
| `PROD_CD` | `product_code` | STRING (direct) | FK to loan_products.code |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) | Remove commas |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) | Remove commas |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) | Remove commas |
| `LN_ORIG_DT` | `origination_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_MAT_DT` | `maturity_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_STAT_CD` | `status` | Code expansion | ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Remove commas |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | |
| `PROP_ADDR_LN1` | `property_address` | STRING (direct) | |
| `PROP_CTY_NM` | `property_city` | STRING (direct) | |
| `PROP_ST_CD` | `property_state` | STRING (direct) | |
| `PROP_ZIP_CD` | `property_zip` | STRING (direct) | |
| `PROP_TYP_CD` | `property_type` | Code expansion | SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Remove commas |
| `LN_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `LN_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| *(derived)* | `origination_year` | INT | `year(origination_date)` — helper for analytics |

### 2.4 CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `PMT_SEQ_NBR` | `legacy_sequence_number` | STRING (direct) | Preserved for traceability |
| `LN_ACCT_NBR` | `loan_account_number` | STRING (direct) | FK to loan_accounts.account_number |
| `PMT_DT` | `payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_AMT` | `total_amount` | VARCHAR → DECIMAL(10,2) | Remove commas |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR → DECIMAL(10,2) | Remove commas |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR → DECIMAL(10,2) | Remove commas |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR → DECIMAL(10,2) | Remove commas |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR → DECIMAL(10,2) | Remove commas |
| `PMT_TYP_CD` | `type` | Code expansion | REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| `PMT_STAT_CD` | `status` | Code expansion | PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| `PMT_RECV_DT` | `received_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_PROC_DT` | `processed_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| *(derived)* | `payment_year` | INT | `year(payment_date)` — partition key |

---

## 3. Transformation Decisions

### 3.1 Type Conversions

| Pattern | Legacy Format | Target Type | Method |
|---|---|---|---|
| Dates | `MM/DD/YYYY` string | `DATE` | `to_date(col, 'MM/dd/yyyy')` |
| Timestamps | `MM/DD/YYYY` string | `TIMESTAMP` | `to_timestamp(col, 'MM/dd/yyyy')` — time component defaults to 00:00:00 |
| Amounts | `"285,000"` or `"271,432.56"` | `DECIMAL(p,s)` | `regexp_replace(col, '[,$]', '').cast(DecimalType)` |
| Integers | `"360"` | `INT` | `regexp_replace(col, ',', '').cast(IntegerType)` |
| Booleans | `"ACT"/"INA"` | `BOOLEAN` | Map-based expansion |

**Rationale:** Using Spark built-in functions (`to_date`, `regexp_replace`, `cast`) over Python UDFs for performance. All conversions return NULL on parse failure rather than raising exceptions; rejected rows are logged separately.

### 3.2 Status Code Expansions

| Domain | Abbreviation | Expanded Value |
|---|---|---|
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

**Rationale:** Abbreviations are expanded to human-readable values for downstream BI/reporting usability. Unrecognized codes default to a safe value (e.g., "ACTIVE", "REGULAR") with a warning log.

### 3.3 Denormalization Removal

The legacy `CDW_LN_ACCT` table embeds borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) directly in the loan record. In the modern schema these are dropped, and `borrower_external_id` serves as the foreign key to the normalized `borrowers` table.

**Rationale:** Eliminates data duplication and update anomalies. Borrower data is maintained in a single source of truth.

### 3.4 FK Strategy

Instead of auto-increment BIGINT IDs for cross-table references (which would require a lookup join during ingestion), the Delta Lake schema uses natural keys:

- `loan_accounts.borrower_external_id` → `borrowers.external_id`
- `loan_accounts.product_code` → `loan_products.code`
- `payments.loan_account_number` → `loan_accounts.account_number`

**Rationale:** Natural keys simplify the ingestion pipeline (no multi-pass ID resolution), are human-readable in queries, and align with how downstream consumers reference these entities. The data quality framework validates referential integrity post-ingestion.

### 3.5 Null / Malformed Value Handling

- **Nulls:** Rows with NULL in required fields are separated into a rejected DataFrame, logged with full row details (via `log_rejected_rows`), and excluded from the Delta table write. They are never silently dropped.
- **Parse failures:** Spark's `to_date` / `cast` return NULL for unparseable values. The null-check phase catches these.
- **Edge cases:** Empty strings are treated as NULL. Leading/trailing whitespace is stripped from date and amount values.

---

## 4. Partitioning Rationale

| Table | Partition Column | Justification |
|---|---|---|
| `borrowers` | `state` | Loan servicing queries frequently filter by geographic region. ~50 distinct values keeps partition count manageable. |
| `loan_products` | *(none)* | Reference table with < 100 rows; partitioning would add overhead without benefit. |
| `loan_accounts` | `status` | Most common query pattern is "show me all active loans" vs. "show me all closed loans." 4 distinct values (ACTIVE, CLOSED, DEFAULT, FORBEARANCE) creates clean partition pruning. |
| `payments` | `payment_year` | Payment queries are almost always time-bounded (e.g., "payments in 2025"). Year-level partitioning balances partition count with query selectivity. |

All tables enable Delta Lake auto-optimization (`optimizeWrite` + `autoCompact`) to handle small-file consolidation automatically.

---

## 5. Audit Columns

Every target table includes:

| Column | Type | Purpose |
|---|---|---|
| `_ingestion_ts` | TIMESTAMP | When the row was ingested (pipeline execution time) |
| `_source_system` | STRING | Origin system identifier (e.g., `CDW_BORR_MSTR`) |

These support data lineage tracking and incident investigation.

---

## 6. Execution Order

The pipeline must be run in dependency order because referential integrity checks assume parent tables are populated first.

```
Step 1: Create database
        CREATE DATABASE IF NOT EXISTS loan_warehouse;

Step 2: Run DDL scripts (in order)
        databricks/ddl/001_borrowers.sql
        databricks/ddl/002_loan_products.sql
        databricks/ddl/003_loan_accounts.sql
        databricks/ddl/004_payments.sql

Step 3: Export legacy data to CSV/Parquet
        Export CDW_BORR_MSTR → /mnt/legacy/CDW_BORR_MSTR.csv
        Export CDW_LN_PROD   → /mnt/legacy/CDW_LN_PROD.csv
        Export CDW_LN_ACCT   → /mnt/legacy/CDW_LN_ACCT.csv
        Export CDW_PMT_HIST  → /mnt/legacy/CDW_PMT_HIST.csv

Step 4: Run ingestion (option A — orchestrator)
        spark-submit databricks/ingestion/run_full_ingestion.py \
            --borrowers /mnt/legacy/CDW_BORR_MSTR.csv \
            --products  /mnt/legacy/CDW_LN_PROD.csv \
            --accounts  /mnt/legacy/CDW_LN_ACCT.csv \
            --payments  /mnt/legacy/CDW_PMT_HIST.csv \
            --format csv

Step 4 (option B — individual scripts)
        spark-submit databricks/ingestion/ingest_borrowers.py      --source /mnt/legacy/CDW_BORR_MSTR.csv
        spark-submit databricks/ingestion/ingest_loan_products.py  --source /mnt/legacy/CDW_LN_PROD.csv
        spark-submit databricks/ingestion/ingest_loan_accounts.py  --source /mnt/legacy/CDW_LN_ACCT.csv
        spark-submit databricks/ingestion/ingest_payments.py       --source /mnt/legacy/CDW_PMT_HIST.csv

Step 5: Run data quality checks
        spark-submit databricks/quality/data_quality_checks.py \
            --source-borrowers /mnt/legacy/CDW_BORR_MSTR.csv \
            --source-products  /mnt/legacy/CDW_LN_PROD.csv \
            --source-accounts  /mnt/legacy/CDW_LN_ACCT.csv \
            --source-payments  /mnt/legacy/CDW_PMT_HIST.csv \
            --output-report    /mnt/reports/DATA_QUALITY_REPORT.md

Step 6: Review DATA_QUALITY_REPORT.md
        - All checks must PASS before promoting to production
        - Any FAIL requires investigation and remediation
```

---

## 7. Data Quality Checks

The quality framework (`databricks/quality/data_quality_checks.py`) runs the following checks:

### 7.1 Row Count Reconciliation
- Compares source CSV row count to Delta table row count for all 4 tables.
- Any mismatch indicates rows were rejected during ingestion.

### 7.2 Null Checks
- Validates required fields contain no NULLs:
  - **borrowers:** external_id, first_name, last_name, status
  - **loan_products:** code, name, type, term_months, rate_type
  - **loan_accounts:** account_number, borrower_external_id, product_code, original_amount, current_balance, interest_rate, term_months, monthly_payment, origination_date, maturity_date, status
  - **payments:** loan_account_number, payment_date, total_amount, type, status

### 7.3 Referential Integrity
- `loan_accounts.borrower_external_id` → `borrowers.external_id`
- `loan_accounts.product_code` → `loan_products.code`
- `payments.loan_account_number` → `loan_accounts.account_number`

### 7.4 Business Rules
| Rule | Table | Condition |
|---|---|---|
| Active loan positive balance | loan_accounts | `status = 'ACTIVE' → current_balance > 0` |
| Valid loan status values | loan_accounts | `status IN ('ACTIVE','CLOSED','DEFAULT','FORBEARANCE')` |
| Posted payment positive amount | payments | `status = 'POSTED' → total_amount > 0` |
| Payment component sum | payments | `principal + interest + escrow + late_fee ≈ total_amount (±$0.02)` |
| Origination before maturity | loan_accounts | `origination_date < maturity_date` |
| Credit score range | borrowers | `credit_score BETWEEN 300 AND 850` |
| LTV range | loan_accounts | `ltv_percent BETWEEN 0 AND 200` |

---

## 8. Databricks Notebook Execution

For interactive execution in Databricks notebooks:

```python
# Cell 1: Setup
%pip install delta-spark

# Cell 2: Run DDL
for ddl_file in ["001_borrowers", "002_loan_products", "003_loan_accounts", "004_payments"]:
    with open(f"/Workspace/databricks/ddl/{ddl_file}.sql") as f:
        spark.sql(f.read())

# Cell 3: Run ingestion
%run ./databricks/ingestion/run_full_ingestion

# Cell 4: Run quality checks
%run ./databricks/quality/data_quality_checks
```

---

## 9. Rollback Procedure

If migration issues are discovered post-ingestion:

1. **Delta Lake Time Travel:** All tables use Delta format, so previous versions are available:
   ```sql
   -- View table at a previous version
   SELECT * FROM loan_warehouse.borrowers VERSION AS OF 0;

   -- Restore to a previous version
   RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF 0;
   ```

2. **Full re-run:** The pipeline uses `mode="overwrite"`, so re-running from legacy sources produces a clean slate.

3. **Legacy system:** The original CDW tables are read-only and unmodified by this pipeline. They remain available as the source of truth until migration is fully validated.

---

## 10. Post-Migration Checklist

- [ ] All 4 DDL scripts executed successfully
- [ ] All 4 ingestion scripts completed without errors
- [ ] Data quality report shows all checks PASS
- [ ] Row counts match: borrowers (5), loan_products (5), loan_accounts (5), payments (10)
- [ ] Spot-check: verify a sample borrower record has correct types and values
- [ ] Spot-check: verify a sample loan's status expanded correctly (e.g., ACT → ACTIVE)
- [ ] Spot-check: verify denormalized borrower fields are absent from loan_accounts
- [ ] Spot-check: verify payment component amounts sum correctly
- [ ] Delta table properties confirmed (auto-optimize enabled)
- [ ] Downstream consumers updated to read from `loan_warehouse.*` tables
