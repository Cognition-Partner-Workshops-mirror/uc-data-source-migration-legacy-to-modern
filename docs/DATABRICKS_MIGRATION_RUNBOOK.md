# Databricks Migration Runbook: CDW Legacy → Modern Loan Warehouse

## 1. Overview

This runbook documents the end-to-end migration of loan management data from a legacy Corporate Data Warehouse (CDW) schema to a modern, properly-typed Delta Lake schema on Databricks. The legacy schema uses all-VARCHAR columns, cryptic abbreviated names, denormalized structures, and no foreign key constraints. The target schema uses proper Spark SQL types, meaningful names, normalized tables, and referential integrity.

### Source Tables (Legacy CDW)

| Legacy Table | Description | Row Count (seed) |
|---|---|---|
| `CDW_BORR_MSTR` | Borrower master records | 5 |
| `CDW_LN_PROD` | Loan product definitions | 5 |
| `CDW_LN_ACCT` | Loan accounts (denormalized with borrower data) | 5 |
| `CDW_PMT_HIST` | Payment history | 10 |

### Target Tables (Modern Delta Lake)

| Target Table | Description | Partitioning |
|---|---|---|
| `loan_warehouse.borrowers` | Borrower dimension | None (small dimension) |
| `loan_warehouse.loan_products` | Product dimension | None (small dimension) |
| `loan_warehouse.loan_accounts` | Loan fact table | By `status` |
| `loan_warehouse.payments` | Payment fact table | By `payment_year` |

---

## 2. Column Mapping Reference

### 2.1 CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| `BORR_ID` | `external_id` | VARCHAR→STRING | Direct copy |
| `BORR_FST_NM` | `first_name` | VARCHAR→STRING | Trim whitespace |
| `BORR_LST_NM` | `last_name` | VARCHAR→STRING | Trim whitespace |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR→STRING | Direct copy |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR→STRING | Direct copy (re-encrypt recommended) |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR→DATE | Parse `MM/DD/YYYY` → DateType |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR→STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR→STRING | Direct copy |
| `BORR_CTY_NM` | `city` | VARCHAR→STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR→STRING | Direct copy |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR→STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR→STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR→STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR→INT | Parse string → integer |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR→STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR→DECIMAL(12,2) | Remove commas, parse to decimal |
| `BORR_CRET_DT` | `created_at` | VARCHAR→TIMESTAMP | Parse `MM/DD/YYYY` → timestamp (midnight) |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR→TIMESTAMP | Parse `MM/DD/YYYY` → timestamp (midnight) |
| `BORR_STAT_CD` | `status` | VARCHAR→STRING | Expand: `ACT`→`ACTIVE`, `INA`→`INACTIVE` |
| `BORR_REC_TYP` | _(dropped)_ | — | No business value in modern schema |

### 2.2 CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| `PROD_CD` | `code` | VARCHAR→STRING | Direct copy |
| `PROD_DESC_TXT` | `name` | VARCHAR→STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR→STRING | Direct copy |
| `PROD_TERM_MOS` | `term_months` | VARCHAR→INT | Parse string → integer |
| `PROD_RT_TYP` | `rate_type` | VARCHAR→STRING | Direct copy |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR→DECIMAL(12,2) | Remove commas, parse to decimal |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR→DECIMAL(12,2) | Remove commas, parse to decimal |
| `PROD_STAT_CD` | `is_active` | VARCHAR→BOOLEAN | `ACT`→`true`, `INA`→`false` |
| `PROD_EFF_DT` | `effective_date` | VARCHAR→DATE | Parse `MM/DD/YYYY` → DateType |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR→DATE | Parse `MM/DD/YYYY` → DateType |

### 2.3 CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| `LN_ACCT_NBR` | `account_number` | VARCHAR→STRING | Direct copy |
| `BORR_ID` | `borrower_id` | VARCHAR→BIGINT | FK lookup: `borrowers.external_id` → `borrowers.id` |
| `BORR_FST_NM` | _(dropped)_ | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | _(dropped)_ | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | _(dropped)_ | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_id` | VARCHAR→BIGINT | FK lookup: `loan_products.code` → `loan_products.id` |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR→DECIMAL(12,2) | Remove commas, parse to decimal |
| `LN_CURR_BAL` | `current_balance` | VARCHAR→DECIMAL(12,2) | Remove commas, parse to decimal |
| `LN_INT_RT` | `interest_rate` | VARCHAR→DECIMAL(5,3) | Parse string → decimal |
| `LN_TERM_MOS` | `term_months` | VARCHAR→INT | Parse string → integer |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR→DECIMAL(10,2) | Remove commas, parse to decimal |
| `LN_ORIG_DT` | `origination_date` | VARCHAR→DATE | Parse `MM/DD/YYYY` → DateType |
| `LN_MAT_DT` | `maturity_date` | VARCHAR→DATE | Parse `MM/DD/YYYY` → DateType |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR→DATE | Parse `MM/DD/YYYY` → DateType |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR→DATE | Parse `MM/DD/YYYY` → DateType |
| `LN_STAT_CD` | `status` | VARCHAR→STRING | Expand: `ACT`→`ACTIVE`, `CLO`→`CLOSED`, `DFT`→`DEFAULT`, `FRB`→`FORBEARANCE` |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR→INT | Parse string → integer |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR→DECIMAL(10,2) | Remove commas, parse to decimal |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR→DECIMAL(5,2) | Parse string → decimal |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR→STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR→STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR→STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR→STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR→STRING | Expand: `SFR`→`Single Family`, `CND`→`Condominium`, `MFR`→`Multi-Family`, `TWN`→`Townhouse` |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR→DECIMAL(12,2) | Remove commas, parse to decimal |
| `LN_CRET_DT` | `created_at` | VARCHAR→TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |
| `LN_UPDT_DT` | `updated_at` | VARCHAR→TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |

### 2.4 CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| `PMT_SEQ_NBR` | `legacy_payment_id` | VARCHAR→STRING | Preserved for audit trail |
| `LN_ACCT_NBR` | `loan_account_id` | VARCHAR→BIGINT | FK lookup: `loan_accounts.account_number` → `loan_accounts.id` |
| `PMT_DT` | `payment_date` | VARCHAR→DATE | Parse `MM/DD/YYYY` → DateType |
| `PMT_AMT` | `total_amount` | VARCHAR→DECIMAL(10,2) | Remove commas, parse to decimal |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR→DECIMAL(10,2) | Remove commas, parse to decimal |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR→DECIMAL(10,2) | Remove commas, parse to decimal |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR→DECIMAL(10,2) | Remove commas, parse to decimal |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR→DECIMAL(10,2) | Remove commas, parse to decimal |
| `PMT_TYP_CD` | `type` | VARCHAR→STRING | Expand: `REG`→`REGULAR`, `EXT`→`EXTRA`, `PRT`→`PARTIAL`, `PRE`→`PREPAYMENT` |
| `PMT_STAT_CD` | `status` | VARCHAR→STRING | Expand: `PST`→`POSTED`, `REV`→`REVERSED`, `NSF`→`NSF`, `PND`→`PENDING` |
| `PMT_RECV_DT` | `received_date` | VARCHAR→DATE | Parse `MM/DD/YYYY` → DateType |
| `PMT_PROC_DT` | `processed_date` | VARCHAR→DATE | Parse `MM/DD/YYYY` → DateType |
| `PMT_CRET_DT` | `created_at` | VARCHAR→TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR→TIMESTAMP | Parse `MM/DD/YYYY` → timestamp |
| _(derived)_ | `payment_year` | — | `YEAR(payment_date)` — partition column |

---

## 3. Transformation Decisions

### 3.1 Date Handling

Legacy dates are stored as `MM/DD/YYYY` VARCHAR strings. Transformation uses PySpark's `to_date()` with format `"MM/dd/yyyy"`. Timestamps for `created_at`/`updated_at` columns default to midnight (`00:00:00`) since the legacy system did not store time components.

**Decision:** Accept midnight default for timestamps. The original time information was never captured in the legacy schema.

### 3.2 Amount Parsing

Amounts are stored as comma-formatted strings (e.g., `"285,000"`, `"1,487.02"`). Transformation strips commas via `regexp_replace` then casts to `DECIMAL`. The `DECIMAL(12,2)` precision matches the modern schema and is sufficient for loan amounts up to $9,999,999,999.99.

**Decision:** Use `DECIMAL(12,2)` for amounts, `DECIMAL(5,3)` for interest rates, `DECIMAL(5,2)` for percentages. These match the existing modern schema in `data/modern-schema/modern_tables.sql`.

### 3.3 Status Code Expansion

All status code abbreviations are expanded to human-readable values per the mapping tables. Unmapped codes are preserved with an `UNKNOWN: <original>` prefix instead of being dropped or nullified. This ensures no data loss while making unmapped codes easy to find in quality reports.

**Decision:** Preserve unmapped codes with prefix rather than dropping. The quality framework flags these as business rule violations.

### 3.4 Denormalization Removal

The legacy `CDW_LN_ACCT` table duplicates borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`). These are dropped in favor of a foreign key reference to `borrowers.id`. The borrower master (`CDW_BORR_MSTR`) is treated as the source of truth.

**Decision:** Trust `CDW_BORR_MSTR` over denormalized copies in `CDW_LN_ACCT`. The data quality framework can cross-validate these if discrepancy detection is needed.

### 3.5 Foreign Key Resolution

Legacy tables use string-based IDs (`BORR_ID`, `PROD_CD`, `LN_ACCT_NBR`) with no FK constraints. The migration resolves these to surrogate `BIGINT` IDs via left-join lookups against the already-loaded dimension tables. Unresolvable FKs result in `null` values which are caught by the quality framework's null checks.

**Decision:** Use left joins (not inner joins) to avoid silently dropping records. Flag unresolved FKs for investigation.

### 3.6 Property Type Expansion

Property type codes are expanded: `SFR`→`Single Family`, `CND`→`Condominium`, `MFR`→`Multi-Family`, `TWN`→`Townhouse`. Unknown codes are preserved with `UNKNOWN:` prefix.

### 3.7 Dropped Columns

- `BORR_REC_TYP` (borrower record type): All seed data shows `PRI` (Primary). No business logic depends on this field in the modern schema.
- `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` in `CDW_LN_ACCT`: Denormalized copies replaced by borrower FK.

---

## 4. Partitioning Rationale

### loan_accounts: Partitioned by `status`

- **Primary access pattern:** Most operational queries filter by active vs. closed loans
- **Cardinality:** Low (4 values: ACTIVE, CLOSED, DEFAULT, FORBEARANCE)
- **Recommendation for large portfolios:** Add `ZORDER BY (origination_date, borrower_id)` within each partition

### payments: Partitioned by `payment_year`

- **Primary access pattern:** Payment queries are almost always date-ranged
- **Alignment:** Matches financial reporting periods and data retention policies
- **Derived column:** `payment_year = YEAR(payment_date)` computed during ingestion

### borrowers & loan_products: No partitioning

- These are small dimension tables where full scans are efficient
- Delta Lake auto-optimize handles compaction

---

## 5. Recommended Execution Order in Databricks

### Prerequisites

1. Databricks workspace with Unity Catalog enabled
2. A compute cluster with Delta Lake support (DBR 12.0+)
3. Legacy data exported as CSV or Parquet files to a landing zone (e.g., `/mnt/landing/cdw/`)

### Step-by-Step Execution

```
Landing zone layout:
/mnt/landing/cdw/
├── cdw_borr_mstr/     (CSV or Parquet extract of CDW_BORR_MSTR)
├── cdw_ln_prod/       (CSV or Parquet extract of CDW_LN_PROD)
├── cdw_ln_acct/       (CSV or Parquet extract of CDW_LN_ACCT)
└── cdw_pmt_hist/      (CSV or Parquet extract of CDW_PMT_HIST)
```

#### Step 1: Create the Database

```sql
-- Run: databricks/ddl/00_create_database.sql
CREATE DATABASE IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse migrated from legacy CDW tables'
LOCATION 'dbfs:/mnt/delta/loan_warehouse';
```

#### Step 2: Create Target Tables (in order)

Run DDL scripts in numbered order:

```
databricks/ddl/01_borrowers.sql
databricks/ddl/02_loan_products.sql
databricks/ddl/03_loan_accounts.sql
databricks/ddl/04_payments.sql
```

#### Step 3: Run Ingestion Pipeline

**Option A — Full pipeline orchestrator (recommended):**

```bash
spark-submit databricks/ingestion/run_full_ingestion.py \
    --base-path /mnt/landing/cdw/ \
    --source-format csv
```

**Option B — Individual table ingestion:**

Must be run in this exact order due to FK dependencies:

```bash
# 1. Borrowers (no dependencies)
spark-submit databricks/ingestion/ingest_borrowers.py \
    --source-path /mnt/landing/cdw/cdw_borr_mstr/ \
    --source-format csv

# 2. Loan Products (no dependencies)
spark-submit databricks/ingestion/ingest_loan_products.py \
    --source-path /mnt/landing/cdw/cdw_ln_prod/ \
    --source-format csv

# 3. Loan Accounts (depends on borrowers + loan_products)
spark-submit databricks/ingestion/ingest_loan_accounts.py \
    --source-path /mnt/landing/cdw/cdw_ln_acct/ \
    --source-format csv

# 4. Payments (depends on loan_accounts)
spark-submit databricks/ingestion/ingest_payments.py \
    --source-path /mnt/landing/cdw/cdw_pmt_hist/ \
    --source-format csv
```

#### Step 4: Run Data Quality Checks

```bash
spark-submit databricks/quality/quality_checks.py \
    --source-base-path /mnt/landing/cdw/ \
    --source-format csv \
    --report-path /dbfs/reports/DATA_QUALITY_REPORT.md
```

Review `DATA_QUALITY_REPORT.md` for pass/fail results. All checks must pass before the migration is considered complete.

#### Step 5: Post-Migration Validation

```sql
-- Verify row counts
SELECT 'borrowers' AS table_name, COUNT(*) AS row_count FROM loan_warehouse.borrowers
UNION ALL
SELECT 'loan_products', COUNT(*) FROM loan_warehouse.loan_products
UNION ALL
SELECT 'loan_accounts', COUNT(*) FROM loan_warehouse.loan_accounts
UNION ALL
SELECT 'payments', COUNT(*) FROM loan_warehouse.payments;

-- Spot-check a borrower
SELECT * FROM loan_warehouse.borrowers WHERE external_id = 'B-10001';

-- Verify FK integrity
SELECT la.account_number, b.first_name, b.last_name, lp.name AS product_name
FROM loan_warehouse.loan_accounts la
JOIN loan_warehouse.borrowers b ON la.borrower_id = b.id
JOIN loan_warehouse.loan_products lp ON la.product_id = lp.id;
```

---

## 6. Idempotency & Reruns

All ingestion scripts use **MERGE (upsert)** operations keyed on natural keys:

| Table | Merge Key |
|---|---|
| `borrowers` | `external_id` |
| `loan_products` | `code` |
| `loan_accounts` | `account_number` |
| `payments` | `legacy_payment_id` |

This means the pipeline can be safely re-run without creating duplicates. Existing records are updated; new records are inserted.

---

## 7. Error Handling Strategy

The pipeline implements a **"flag, don't drop"** strategy:

1. **Malformed values** (e.g., unparseable dates/amounts) result in `null` in the target column. A `_malformed_<column>` boolean flag is added during transformation for debugging.
2. **Unmapped status codes** are preserved with an `UNKNOWN: <original>` prefix.
3. **Unresolvable foreign keys** result in `null` FK values, flagged with `_unresolved_*` columns.
4. **All anomalies are logged** via Python's `logging` module at WARNING level.
5. **No records are silently dropped** — the row count reconciliation check will catch any discrepancy.

---

## 8. Audit Trail

Each target table includes a `_migration_ts` column that records when each row was loaded/updated by the pipeline. The `payments` table also preserves the `legacy_payment_id` (original `PMT_SEQ_NBR`) for cross-referencing with the legacy system.

---

## 9. File Inventory

```
databricks/
├── ddl/
│   ├── 00_create_database.sql      # Database/schema creation
│   ├── 01_borrowers.sql            # Borrowers Delta table DDL
│   ├── 02_loan_products.sql        # Loan products Delta table DDL
│   ├── 03_loan_accounts.sql        # Loan accounts Delta table DDL (partitioned by status)
│   └── 04_payments.sql             # Payments Delta table DDL (partitioned by payment_year)
├── ingestion/
│   ├── __init__.py
│   ├── transform_utils.py          # Shared transformation UDFs and mappings
│   ├── ingest_borrowers.py         # CDW_BORR_MSTR → borrowers
│   ├── ingest_loan_products.py     # CDW_LN_PROD → loan_products
│   ├── ingest_loan_accounts.py     # CDW_LN_ACCT → loan_accounts
│   ├── ingest_payments.py          # CDW_PMT_HIST → payments
│   └── run_full_ingestion.py       # Orchestrator: runs all 4 ingestions in order
└── quality/
    ├── __init__.py
    ├── quality_checks.py           # Data quality validation framework
    └── DATA_QUALITY_REPORT.md      # Auto-generated quality report (placeholder)

docs/
└── DATABRICKS_MIGRATION_RUNBOOK.md # This document
```
