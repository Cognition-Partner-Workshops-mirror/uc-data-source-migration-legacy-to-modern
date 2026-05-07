# Databricks Migration Runbook

## Legacy CDW → Modern Delta Lake Loan Data Migration

This runbook documents every transformation decision, column mapping, type conversion, partitioning rationale, and the recommended execution order for migrating loan data from the legacy CDW (Corporate Data Warehouse) tables to modern Delta Lake tables in Databricks.

---

## Table of Contents

1. [Migration Overview](#migration-overview)
2. [Source System Analysis](#source-system-analysis)
3. [Target Schema Design](#target-schema-design)
4. [Column Mapping Reference](#column-mapping-reference)
5. [Transformation Decisions](#transformation-decisions)
6. [Partitioning Strategy](#partitioning-strategy)
7. [Execution Order](#execution-order)
8. [Pre-Migration Checklist](#pre-migration-checklist)
9. [Running the Pipeline](#running-the-pipeline)
10. [Post-Migration Validation](#post-migration-validation)
11. [Rollback Procedure](#rollback-procedure)
12. [Troubleshooting](#troubleshooting)

---

## Migration Overview

| Attribute | Value |
|-----------|-------|
| Source System | CDW (Corporate Data Warehouse) — H2/RDBMS |
| Target System | Databricks / Delta Lake (Unity Catalog) |
| Catalog | `loan_migration` |
| Schema | `loan_warehouse` |
| Source Tables | 4 (`CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST`) |
| Target Tables | 4 (`borrowers`, `loan_products`, `loan_accounts`, `payments`) |
| Pipeline Language | PySpark |
| Data Format | Delta Lake |

### Key Improvements Over Legacy

1. **Proper data types**: VARCHAR-for-everything replaced with DATE, DECIMAL, INT, BOOLEAN, TIMESTAMP
2. **Readable column names**: Cryptic abbreviations (BORR_FST_NM) replaced with clear names (first_name)
3. **Normalized structure**: Denormalized borrower data in loan accounts replaced with FK references
4. **Referential integrity**: Foreign key constraints between tables (informational in Delta Lake)
5. **Status code expansion**: Abbreviations (ACT, CLO, DFT, FRB) expanded to readable values
6. **Partitioning**: Tables partitioned for common query patterns (status, date ranges, geography)
7. **Data lineage**: `_migration_source` and `_migrated_at` audit columns on every table

---

## Source System Analysis

### CDW_BORR_MSTR (Borrower Master)

- **20 columns**, all VARCHAR
- Contains borrower demographics, contact info, employment, and credit data
- Dates stored as `MM/DD/YYYY` strings
- Annual income stored as comma-formatted string (e.g., `"92,500"`)
- Credit score stored as string (e.g., `"745"`)
- Status codes: `ACT` (Active), `INA` (Inactive)
- `BORR_REC_TYP` column dropped in migration (not needed)

### CDW_LN_PROD (Loan Products)

- **10 columns**, all VARCHAR
- Reference table for loan product types (FXD30, FXD15, ARM51, FHA30, VA30)
- Product status is ACT/INA → converted to boolean `is_active`
- Min/max amounts stored as comma-formatted strings

### CDW_LN_ACCT (Loan Accounts)

- **29 columns**, all VARCHAR
- **Denormalized**: Contains 3 redundant borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`)
- Loan status codes: `ACT`, `CLO`, `DFT`, `FRB`
- Property type codes: `SFR`, `CND`, `MFR`, `TWN`
- All monetary amounts are comma-formatted strings
- No foreign key constraints to borrower or product tables

### CDW_PMT_HIST (Payment History)

- **14 columns**, all VARCHAR
- Payment type codes: `REG`, `EXT`, `PRT`, `PRE`
- Payment status codes: `PST`, `REV`, `NSF`, `PND`
- All amounts are comma-formatted strings
- No FK constraint to loan accounts

---

## Target Schema Design

### loan_warehouse.borrowers

| Column | Type | Source | Notes |
|--------|------|--------|-------|
| borrower_id | BIGINT (identity) | — | Auto-generated surrogate key |
| external_id | STRING NOT NULL | BORR_ID | Unique legacy identifier |
| first_name | STRING NOT NULL | BORR_FST_NM | Trimmed |
| last_name | STRING NOT NULL | BORR_LST_NM | Trimmed |
| middle_initial | STRING | BORR_MID_INIT | Direct copy |
| ssn_hash | STRING | BORR_SSN_ENCR | Direct copy (re-encryption recommended) |
| date_of_birth | DATE | BORR_DOB_DT | Parsed from MM/DD/YYYY |
| address_line1 | STRING | BORR_ADDR_LN1 | Direct copy |
| address_line2 | STRING | BORR_ADDR_LN2 | Direct copy |
| city | STRING | BORR_CTY_NM | Direct copy |
| state | STRING | BORR_ST_CD | Direct copy |
| zip_code | STRING | BORR_ZIP_CD | Direct copy |
| phone | STRING | BORR_PH_NBR | Direct copy |
| email | STRING | BORR_EMAIL_ADDR | Direct copy |
| credit_score | INT | BORR_CRDT_SCR | Parsed from string |
| employment_status | STRING | BORR_EMP_STAT | Direct copy |
| annual_income | DECIMAL(12,2) | BORR_ANN_INCM | Commas removed, parsed |
| status | STRING NOT NULL | BORR_STAT_CD | ACT→ACTIVE, INA→INACTIVE |
| created_at | TIMESTAMP | BORR_CRET_DT | Parsed from MM/DD/YYYY |
| updated_at | TIMESTAMP | BORR_UPDT_DT | Parsed from MM/DD/YYYY |
| _migration_source | STRING | — | Lineage: "CDW_BORR_MSTR" |
| _migrated_at | TIMESTAMP | — | Lineage: migration timestamp |

**Dropped column**: `BORR_REC_TYP` — record type indicator not needed in modern schema.

### loan_warehouse.loan_products

| Column | Type | Source | Notes |
|--------|------|--------|-------|
| product_id | BIGINT (identity) | — | Auto-generated surrogate key |
| code | STRING NOT NULL | PROD_CD | Unique product code |
| name | STRING NOT NULL | PROD_DESC_TXT | Product description |
| type | STRING NOT NULL | PROD_TYP_CD | FXD, ARM, FHA, VA |
| term_months | INT NOT NULL | PROD_TERM_MOS | Parsed from string |
| rate_type | STRING NOT NULL | PROD_RT_TYP | FIXED, VARIABLE |
| min_amount | DECIMAL(12,2) | PROD_MIN_AMT | Commas removed, parsed |
| max_amount | DECIMAL(12,2) | PROD_MAX_AMT | Commas removed, parsed |
| is_active | BOOLEAN NOT NULL | PROD_STAT_CD | ACT→true, INA→false |
| effective_date | DATE | PROD_EFF_DT | Parsed from MM/DD/YYYY |
| expiration_date | DATE | PROD_EXP_DT | Parsed from MM/DD/YYYY |

### loan_warehouse.loan_accounts

| Column | Type | Source | Notes |
|--------|------|--------|-------|
| loan_account_id | BIGINT (identity) | — | Auto-generated surrogate key |
| account_number | STRING NOT NULL | LN_ACCT_NBR | Unique loan number |
| borrower_id | BIGINT NOT NULL | BORR_ID | FK resolved via borrowers.external_id |
| product_id | BIGINT NOT NULL | PROD_CD | FK resolved via loan_products.code |
| original_amount | DECIMAL(12,2) NOT NULL | LN_ORIG_AMT | Commas removed |
| current_balance | DECIMAL(12,2) NOT NULL | LN_CURR_BAL | Commas removed |
| interest_rate | DECIMAL(5,3) NOT NULL | LN_INT_RT | Parsed from string |
| term_months | INT NOT NULL | LN_TERM_MOS | Parsed from string |
| monthly_payment | DECIMAL(10,2) NOT NULL | LN_PMT_AMT | Commas removed |
| origination_date | DATE NOT NULL | LN_ORIG_DT | Parsed from MM/DD/YYYY |
| maturity_date | DATE NOT NULL | LN_MAT_DT | Parsed from MM/DD/YYYY |
| first_payment_date | DATE | LN_1ST_PMT_DT | Parsed from MM/DD/YYYY |
| next_payment_date | DATE | LN_NXT_PMT_DT | Parsed from MM/DD/YYYY |
| status | STRING NOT NULL | LN_STAT_CD | ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| delinquency_days | INT | LN_DLQ_DAYS | Parsed from string |
| escrow_balance | DECIMAL(10,2) | LN_ESCROW_BAL | Commas removed |
| ltv_percent | DECIMAL(5,2) | LN_LTV_PCT | Parsed from string |
| property_address | STRING | PROP_ADDR_LN1 | Direct copy |
| property_city | STRING | PROP_CTY_NM | Direct copy |
| property_state | STRING | PROP_ST_CD | Direct copy |
| property_zip | STRING | PROP_ZIP_CD | Direct copy |
| property_type | STRING | PROP_TYP_CD | SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| appraised_value | DECIMAL(12,2) | PROP_APRS_VAL | Commas removed |
| origination_year | INT NOT NULL | LN_ORIG_DT | Derived: year(origination_date) |

**Dropped columns**: `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` — denormalized borrower data replaced by `borrower_id` FK.

### loan_warehouse.payments

| Column | Type | Source | Notes |
|--------|------|--------|-------|
| payment_id | BIGINT (identity) | — | Auto-generated surrogate key |
| legacy_sequence_id | STRING | PMT_SEQ_NBR | Preserved for traceability |
| loan_account_id | BIGINT NOT NULL | LN_ACCT_NBR | FK resolved via loan_accounts.account_number |
| payment_date | DATE NOT NULL | PMT_DT | Parsed from MM/DD/YYYY |
| total_amount | DECIMAL(10,2) NOT NULL | PMT_AMT | Commas removed |
| principal_amount | DECIMAL(10,2) | PMT_PRIN_AMT | Commas removed |
| interest_amount | DECIMAL(10,2) | PMT_INT_AMT | Commas removed |
| escrow_amount | DECIMAL(10,2) | PMT_ESCROW_AMT | Commas removed |
| late_fee | DECIMAL(10,2) | PMT_LATE_FEE | Commas removed |
| type | STRING NOT NULL | PMT_TYP_CD | REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| status | STRING NOT NULL | PMT_STAT_CD | PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| received_date | DATE | PMT_RECV_DT | Parsed from MM/DD/YYYY |
| processed_date | DATE | PMT_PROC_DT | Parsed from MM/DD/YYYY |
| payment_year | INT NOT NULL | PMT_DT | Derived: year(payment_date) |
| payment_month | INT NOT NULL | PMT_DT | Derived: month(payment_date) |

---

## Transformation Decisions

### 1. Date Parsing: MM/DD/YYYY → DATE / TIMESTAMP

**Decision**: Use Spark's `to_date(col, "MM/dd/yyyy")` and `to_timestamp(col, "MM/dd/yyyy")`.

**Rationale**: The legacy system stores all dates as `MM/DD/YYYY` VARCHAR strings. Spark's built-in format parsing handles this reliably. Unparseable values become `NULL` rather than causing job failures.

**Audit/created/updated dates**: Converted to `TIMESTAMP` (at midnight) rather than `DATE` because these represent point-in-time events. Business dates (origination, maturity, payment) remain `DATE`.

### 2. Amount Parsing: Comma-Formatted Strings → DECIMAL

**Decision**: `regexp_replace(col, ",", "").cast(DecimalType(p, s))`.

**Rationale**: Legacy amounts like `"285,000"` and `"271,432.56"` contain commas as thousands separators. Stripping commas before casting is the most reliable approach. Precision/scale chosen per column:
- Loan amounts: `DECIMAL(12,2)` — supports values up to 9,999,999,999.99
- Payment amounts: `DECIMAL(10,2)` — supports values up to 99,999,999.99
- Interest rates: `DECIMAL(5,3)` — supports rates up to 99.999%
- LTV percent: `DECIMAL(5,2)` — supports values up to 999.99%

### 3. Status Code Expansion

**Decision**: Use PySpark `create_map` for in-memory lookup; unmapped codes pass through unchanged.

| Table | Legacy Code | Modern Value |
|-------|-------------|--------------|
| Borrowers | ACT | ACTIVE |
| Borrowers | INA | INACTIVE |
| Loan Accounts | ACT | ACTIVE |
| Loan Accounts | CLO | CLOSED |
| Loan Accounts | DFT | DEFAULT |
| Loan Accounts | FRB | FORBEARANCE |
| Payments (type) | REG | REGULAR |
| Payments (type) | EXT | EXTRA |
| Payments (type) | PRT | PARTIAL |
| Payments (type) | PRE | PREPAYMENT |
| Payments (status) | PST | POSTED |
| Payments (status) | REV | REVERSED |
| Payments (status) | NSF | NSF |
| Payments (status) | PND | PENDING |
| Products | ACT | true (boolean) |
| Products | INA | false (boolean) |
| Properties | SFR | Single Family |
| Properties | CND | Condominium |
| Properties | MFR | Multi-Family |
| Properties | TWN | Townhouse |

**Rationale for passthrough on unknown codes**: If the legacy system contains codes not in our mapping, we preserve them rather than silently dropping data. The data quality framework flags these for review.

### 4. Denormalization Removal

**Decision**: Drop `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` from loan_accounts. Replace with `borrower_id` FK.

**Rationale**: These fields are redundant copies of data already in `CDW_BORR_MSTR`. The modern schema uses a proper foreign key relationship. The FK is resolved by joining `CDW_LN_ACCT.BORR_ID` to `borrowers.external_id` to get the auto-generated `borrower_id`.

### 5. Foreign Key Resolution

**Decision**: Resolve string-based legacy IDs to auto-generated BIGINT keys via left joins during ingestion.

- `CDW_LN_ACCT.BORR_ID` → join `borrowers` on `external_id` → get `borrower_id`
- `CDW_LN_ACCT.PROD_CD` → join `loan_products` on `code` → get `product_id`
- `CDW_PMT_HIST.LN_ACCT_NBR` → join `loan_accounts` on `account_number` → get `loan_account_id`

**Rationale**: Left joins ensure no records are silently dropped. Unresolved FKs are flagged and quarantined for investigation.

### 6. Quarantine Strategy

**Decision**: Records that fail parsing or FK resolution are written to separate Delta tables at `dbfs:/mnt/migration-quarantine/{table}/`.

**Rationale**: Never silently drop records. Bad records are preserved with the original legacy data plus parse-failure flags so they can be investigated and manually corrected if needed.

### 7. Lineage Columns

**Decision**: Add `_migration_source` (source table name) and `_migrated_at` (timestamp) to every target table.

**Rationale**: Provides traceability for auditing. Useful for identifying which batch a record came from and supporting incremental migration runs.

---

## Partitioning Strategy

| Table | Partition Columns | Rationale |
|-------|-------------------|-----------|
| `borrowers` | `state` | Regional queries are common in loan servicing (regulatory reporting, branch-level analytics). 50 states keeps partition count manageable. |
| `loan_products` | *(none)* | Small reference table (~10s of rows). Partitioning would create unnecessary overhead. |
| `loan_accounts` | `status`, `origination_year` | Most queries filter by loan status (active vs. closed) and/or origination vintage. Composite partition enables efficient pruning for portfolio analysis. |
| `payments` | `payment_year`, `payment_month` | Payment queries are overwhelmingly time-based (monthly reporting, cash-flow analysis). Year+month partitioning aligns with business reporting cadence. |

### Z-ORDER Recommendations

After initial load and periodically thereafter:

```sql
OPTIMIZE loan_warehouse.borrowers ZORDER BY (external_id, last_name, email);
OPTIMIZE loan_warehouse.loan_accounts ZORDER BY (account_number, borrower_id, origination_date);
OPTIMIZE loan_warehouse.payments ZORDER BY (loan_account_id, payment_date);
```

### Delta Lake Table Properties

All tables use:
- `delta.autoOptimize.optimizeWrite = true` — automatic bin-packing
- `delta.autoOptimize.autoCompact = true` — automatic small file compaction
- `delta.columnMapping.mode = name` — enables column rename/drop without rewrite

---

## Execution Order

The pipeline must run in strict dependency order due to FK resolution:

```
Step 1: Create catalog and schema
        └── databricks/ddl/create_schema.sql

Step 2: Create tables (can run in parallel)
        ├── databricks/ddl/borrowers.sql
        ├── databricks/ddl/loan_products.sql
        ├── databricks/ddl/loan_accounts.sql
        └── databricks/ddl/payments.sql

Step 3: Ingest dimension tables (can run in parallel)
        ├── databricks/ingestion/ingest_borrowers.py
        └── databricks/ingestion/ingest_loan_products.py

Step 4: Ingest loan accounts (depends on Step 3)
        └── databricks/ingestion/ingest_loan_accounts.py

Step 5: Ingest payments (depends on Step 4)
        └── databricks/ingestion/ingest_payments.py

Step 6: Run data quality checks
        └── databricks/quality/data_quality_checks.py

Step 7: Review DATA_QUALITY_REPORT.md
        └── Investigate any failures before promoting to production
```

The orchestrator script `databricks/ingestion/run_full_pipeline.py` automates Steps 3-5 in the correct order.

---

## Pre-Migration Checklist

- [ ] **Export legacy data**: Export CDW tables to CSV/Parquet files in cloud storage
  - `CDW_BORR_MSTR` → `dbfs:/mnt/legacy-exports/CDW_BORR_MSTR/`
  - `CDW_LN_PROD` → `dbfs:/mnt/legacy-exports/CDW_LN_PROD/`
  - `CDW_LN_ACCT` → `dbfs:/mnt/legacy-exports/CDW_LN_ACCT/`
  - `CDW_PMT_HIST` → `dbfs:/mnt/legacy-exports/CDW_PMT_HIST/`
- [ ] **Verify CSV headers** match the legacy column names exactly
- [ ] **Create Unity Catalog** resources: Run `databricks/ddl/create_schema.sql`
- [ ] **Create Delta tables**: Run all DDL scripts in `databricks/ddl/`
- [ ] **Verify cluster configuration**: DBR 13.3+ recommended, Unity Catalog enabled
- [ ] **Set up mount points** for `dbfs:/mnt/legacy-exports/` and `dbfs:/mnt/migration-quarantine/`
- [ ] **Take a snapshot** of legacy data for rollback purposes

---

## Running the Pipeline

### Option A: Full Pipeline (Recommended)

```python
# In a Databricks notebook:
%run ./databricks/ingestion/run_full_pipeline
```

Or via spark-submit:

```bash
spark-submit --master local[*] databricks/ingestion/run_full_pipeline.py
```

### Option B: Individual Table Ingestion

```python
# Run each step individually for debugging
%run ./databricks/ingestion/ingest_borrowers
%run ./databricks/ingestion/ingest_loan_products
%run ./databricks/ingestion/ingest_loan_accounts
%run ./databricks/ingestion/ingest_payments
```

### Option C: Databricks Workflow

Create a Databricks Workflow with the following task graph:

```
ingest_borrowers ──────┐
                       ├──→ ingest_loan_accounts ──→ ingest_payments ──→ data_quality_checks
ingest_loan_products ──┘
```

---

## Post-Migration Validation

### Run Data Quality Checks

```python
%run ./databricks/quality/data_quality_checks
```

The framework validates:

1. **Row count reconciliation** — source count == target count + quarantined count
2. **Null checks** — required fields have no nulls
3. **Referential integrity** — all FKs resolve to valid parent records
4. **Business rules**:
   - Active loans have balance > 0
   - Interest rates are in range 0-25%
   - LTV percent is in range 0-200%
   - Origination date < maturity date
   - Delinquency days >= 0
   - Status values are in expected sets
   - Payment amounts > 0
   - Credit scores in range 300-850
   - Annual income >= 0

### Manual Spot Checks

```sql
-- Verify borrower count matches
SELECT COUNT(*) FROM loan_warehouse.borrowers;
-- Expected: 5

-- Verify loan account count
SELECT COUNT(*) FROM loan_warehouse.loan_accounts;
-- Expected: 5

-- Verify payment count
SELECT COUNT(*) FROM loan_warehouse.payments;
-- Expected: 10

-- Verify status expansion worked
SELECT DISTINCT status FROM loan_warehouse.loan_accounts;
-- Expected: ACTIVE, CLOSED, DEFAULT, FORBEARANCE (subset based on data)

-- Verify FK resolution
SELECT la.account_number, b.first_name, b.last_name, lp.name as product
FROM loan_warehouse.loan_accounts la
JOIN loan_warehouse.borrowers b ON la.borrower_id = b.borrower_id
JOIN loan_warehouse.loan_products lp ON la.product_id = lp.product_id;

-- Verify amount parsing
SELECT account_number, original_amount, current_balance, monthly_payment
FROM loan_warehouse.loan_accounts;

-- Check quarantine tables
SELECT COUNT(*) FROM delta.`dbfs:/mnt/migration-quarantine/borrowers/`;
SELECT COUNT(*) FROM delta.`dbfs:/mnt/migration-quarantine/loan_accounts/`;
```

---

## Rollback Procedure

Delta Lake supports time travel, making rollback straightforward:

```sql
-- Restore a table to its state before migration
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.loan_products TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF 0;
RESTORE TABLE loan_warehouse.payments TO VERSION AS OF 0;

-- Or drop and recreate from the DDL scripts
DROP TABLE IF EXISTS loan_warehouse.payments;
DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
DROP TABLE IF EXISTS loan_warehouse.loan_products;
DROP TABLE IF EXISTS loan_warehouse.borrowers;
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Resolution |
|-------|-------|------------|
| "Table not found" during FK resolution | Dimension tables not loaded yet | Ensure borrowers and loan_products are loaded before loan_accounts |
| High quarantine count | Malformed dates or amounts in legacy data | Inspect quarantine tables, fix source data, re-run |
| Duplicate key errors | Re-running ingestion without overwrite | Pipeline uses `mode("overwrite")` by default; check for manual inserts |
| Partition skew | Uneven distribution across partition keys | Run `OPTIMIZE` with Z-ORDER after loading |
| "AnalysisException: Column X not found" | CSV header mismatch | Verify CSV exports have correct column names matching legacy schema |

### Monitoring

- Check Spark UI for job progress and stage details
- Review quarantine paths for rejected records: `dbfs:/mnt/migration-quarantine/`
- Review `DATA_QUALITY_REPORT.md` after each run
- Delta Lake history: `DESCRIBE HISTORY loan_warehouse.<table>` for audit trail
