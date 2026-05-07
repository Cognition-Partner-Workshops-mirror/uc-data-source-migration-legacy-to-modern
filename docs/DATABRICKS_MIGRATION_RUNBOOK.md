# Databricks Migration Runbook

## CDW Legacy → Delta Lake Modern Schema

This runbook documents every transformation decision, column mapping, type
conversion choice, partitioning rationale, and the recommended execution order
for migrating loan data from the legacy CDW (Core Data Warehouse) tables to a
modern Delta Lake schema on Databricks.

---

## Table of Contents

1. [Overview](#overview)
2. [Source System Profile](#source-system-profile)
3. [Target Architecture](#target-architecture)
4. [Column Mapping Reference](#column-mapping-reference)
5. [Transformation Decisions](#transformation-decisions)
6. [Partitioning Strategy](#partitioning-strategy)
7. [Execution Order](#execution-order)
8. [Data Quality Validation](#data-quality-validation)
9. [Rollback Procedure](#rollback-procedure)
10. [Operational Notes](#operational-notes)

---

## 1. Overview

| Attribute | Value |
|-----------|-------|
| Source system | CDW (Corporate Data Warehouse) — H2/RDBMS |
| Source tables | `CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| Target platform | Databricks (Unity Catalog + Delta Lake) |
| Target tables | `borrowers`, `loan_products`, `loan_accounts`, `payments` |
| Catalog | `loan_catalog` |
| Schema | `loan_warehouse` |
| Pipeline engine | PySpark |
| Source format | CSV or Parquet files extracted from legacy DB |

### Key Problems Solved

| Legacy Issue | Modern Resolution |
|-------------|-------------------|
| All columns VARCHAR | Proper Spark SQL types (DATE, DECIMAL, INT, BOOLEAN, TIMESTAMP) |
| Cryptic names (`BORR_FST_NM`, `LN_CURR_BAL`) | Readable names (`first_name`, `current_balance`) |
| No foreign keys | FK relationships enforced at ingestion + quality checks |
| Status abbreviations (`ACT`, `CLO`) | Expanded human-readable values (`Active`, `Closed`) |
| Denormalized borrower data in loans | Separate borrower dimension table with FK reference |
| String dates (`MM/DD/YYYY`) | Native DATE / TIMESTAMP types |
| String amounts (`"285,000"`) | DECIMAL with specified precision |

---

## 2. Source System Profile

### CDW_BORR_MSTR (Borrower Master)

- **Record count (seed):** 5
- **Primary key:** `BORR_ID` (VARCHAR, e.g., `B-10001`)
- **Notable quirks:**
  - `BORR_DOB_DT` stored as `MM/DD/YYYY` string
  - `BORR_ANN_INCM` stored with commas (`"92,500"`)
  - `BORR_CRDT_SCR` stored as string (`"745"`)
  - `BORR_REC_TYP` column is dropped in modern schema (not business-relevant)
  - `BORR_MID_INIT` can be NULL

### CDW_LN_PROD (Loan Products)

- **Record count (seed):** 5
- **Primary key:** `PROD_CD` (VARCHAR, e.g., `FXD30`)
- **Notable quirks:**
  - `PROD_STAT_CD` maps to a boolean (`ACT` → true, `INA` → false)
  - Amount fields stored with commas
  - `PROD_EXP_DT` uses `12/31/2099` as "no expiry" sentinel

### CDW_LN_ACCT (Loan Accounts)

- **Record count (seed):** 5
- **Primary key:** `LN_ACCT_NBR` (VARCHAR, e.g., `LN-2019-00142`)
- **Notable quirks:**
  - Contains denormalized borrower columns (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) — these are dropped
  - `BORR_ID` and `PROD_CD` are resolved to modern surrogate keys via lookup joins
  - `LN_INT_RT` stored as string (`"4.750"`)
  - `PROP_TYP_CD` abbreviations (`SFR`, `CND`, `MFR`, `TWN`) are expanded

### CDW_PMT_HIST (Payment History)

- **Record count (seed):** 10
- **Primary key:** `PMT_SEQ_NBR` (VARCHAR, e.g., `PMT-2025120001`)
- **Notable quirks:**
  - `PMT_SEQ_NBR` preserved as `legacy_sequence_nbr` for audit; modern table uses auto-generated ID
  - `LN_ACCT_NBR` resolved to `loan_account_id` FK
  - All amount fields stored with commas
  - Both type and status codes are expanded

---

## 3. Target Architecture

```
loan_catalog
└── loan_warehouse
    ├── borrowers          (DELTA, partitioned by status)
    ├── loan_products      (DELTA, unpartitioned)
    ├── loan_accounts      (DELTA, partitioned by origination_year)
    └── payments           (DELTA, partitioned by payment_year)
```

### Table Properties

All tables use:
- `delta.autoOptimize.optimizeWrite = true` — automatic file sizing
- `delta.autoOptimize.autoCompact = true` — automatic small-file compaction
- `quality.tier = gold` — marks tables as curated/production-ready

### Metadata Columns

Every table includes:
- `_ingestion_ts` (TIMESTAMP) — pipeline execution timestamp for lineage tracking

Additional audit columns:
- `borrowers._legacy_record_type` — original `BORR_REC_TYP` preserved for audit
- `payments.legacy_sequence_nbr` — original `PMT_SEQ_NBR` preserved for traceability

---

## 4. Column Mapping Reference

### CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `BORR_ID` | `external_id` | VARCHAR → STRING | Direct copy |
| `BORR_FST_NM` | `first_name` | VARCHAR → STRING | Direct copy |
| `BORR_LST_NM` | `last_name` | VARCHAR → STRING | Direct copy |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR → STRING | Direct copy |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR → STRING | Direct copy |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR → STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR → STRING | Direct copy |
| `BORR_CTY_NM` | `city` | VARCHAR → STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR → STRING | Direct copy |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR → STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR → STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR → STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR → INT | `.cast(IntegerType())` |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR → STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR → DECIMAL(12,2) | Strip commas, cast |
| `BORR_STAT_CD` | `status` | VARCHAR → STRING | `ACT→Active`, `INA→Inactive` |
| `BORR_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| `BORR_REC_TYP` | `_legacy_record_type` | VARCHAR → STRING | Preserved for audit |

### CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PROD_CD` | `code` | VARCHAR → STRING | Direct copy |
| `PROD_DESC_TXT` | `name` | VARCHAR → STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR → STRING | Direct copy |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | `.cast(IntegerType())` |
| `PROD_RT_TYP` | `rate_type` | VARCHAR → STRING | Direct copy |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) | Strip commas, cast |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) | Strip commas, cast |
| `PROD_STAT_CD` | `is_active` | VARCHAR → BOOLEAN | `ACT→true`, `INA→false` |
| `PROD_EFF_DT` | `effective_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |

### CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `LN_ACCT_NBR` | `account_number` | VARCHAR → STRING | Direct copy |
| `BORR_ID` | `borrower_id` | VARCHAR → BIGINT | FK lookup join on `borrowers.external_id` |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use FK |
| `PROD_CD` | `product_id` | VARCHAR → BIGINT | FK lookup join on `loan_products.code` |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) | Strip commas, cast |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) | Strip commas, cast |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | `.cast(DecimalType(5,3))` |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | `.cast(IntegerType())` |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) | Strip commas, cast |
| `LN_ORIG_DT` | `origination_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `LN_MAT_DT` | `maturity_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `LN_STAT_CD` | `status` | VARCHAR → STRING | `ACT→Active`, `CLO→Closed`, `DFT→Default`, `FRB→Forbearance` |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | `.cast(IntegerType())` |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Strip commas, cast |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | `.cast(DecimalType(5,2))` |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR → STRING | `SFR→Single Family`, `CND→Condominium`, `MFR→Multi-Family`, `TWN→Townhouse` |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Strip commas, cast |
| `LN_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| `LN_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| *(derived)* | `origination_year` | — → INT | `year(origination_date)` partition key |

### CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PMT_SEQ_NBR` | `legacy_sequence_nbr` | VARCHAR → STRING | Preserved for audit |
| `LN_ACCT_NBR` | `loan_account_id` | VARCHAR → BIGINT | FK lookup join on `loan_accounts.account_number` |
| `PMT_DT` | `payment_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `PMT_AMT` | `total_amount` | VARCHAR → DECIMAL(10,2) | Strip commas, cast |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR → DECIMAL(10,2) | Strip commas, cast |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR → DECIMAL(10,2) | Strip commas, cast |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR → DECIMAL(10,2) | Strip commas, cast |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR → DECIMAL(10,2) | Strip commas, cast |
| `PMT_TYP_CD` | `type` | VARCHAR → STRING | `REG→Regular`, `EXT→Extra`, `PRT→Partial`, `PRE→Prepayment` |
| `PMT_STAT_CD` | `status` | VARCHAR → STRING | `PST→Posted`, `REV→Reversed`, `NSF→NSF`, `PND→Pending` |
| `PMT_RECV_DT` | `received_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `PMT_PROC_DT` | `processed_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `PMT_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| *(derived)* | `payment_year` | — → INT | `year(payment_date)` partition key |

---

## 5. Transformation Decisions

### 5.1 Date Parsing

**Decision:** Use `to_date(col, "MM/dd/yyyy")` for DATE and `to_timestamp(col, "MM/dd/yyyy")` for TIMESTAMP.

**Rationale:** All legacy date strings use the `MM/DD/YYYY` format consistently (verified against seed data). PySpark's `to_date` returns NULL for unparseable strings rather than throwing exceptions, allowing the pipeline to log issues without dropping rows.

**Edge case handling:** Rows with NULL dates after parsing are logged as warnings. No records are dropped — they remain in the target with NULL date fields for manual review.

### 5.2 Amount Parsing

**Decision:** Use `regexp_replace(col, ",", "").cast(DecimalType(p, s))`.

**Rationale:** Legacy amounts contain comma-formatted strings (e.g., `"285,000"`, `"271,432.56"`). Stripping commas before casting is the simplest, most reliable approach. We use DECIMAL rather than DOUBLE to avoid floating-point precision issues on financial data.

**Precision choices:**
- `DECIMAL(12, 2)` — for loan amounts and incomes (up to $9,999,999,999.99)
- `DECIMAL(10, 2)` — for payment amounts and escrow (up to $99,999,999.99)
- `DECIMAL(5, 3)` — for interest rates (up to 99.999%)
- `DECIMAL(5, 2)` — for LTV percentages (up to 999.99%)

### 5.3 Status Code Expansion

**Decision:** Map abbreviations to full English words, keeping the original value if no mapping match is found.

| Domain | Abbreviation | Expanded |
|--------|-------------|----------|
| Borrower status | `ACT` | `Active` |
| Borrower status | `INA` | `Inactive` |
| Loan status | `ACT` | `Active` |
| Loan status | `CLO` | `Closed` |
| Loan status | `DFT` | `Default` |
| Loan status | `FRB` | `Forbearance` |
| Payment type | `REG` | `Regular` |
| Payment type | `EXT` | `Extra` |
| Payment type | `PRT` | `Partial` |
| Payment type | `PRE` | `Prepayment` |
| Payment status | `PST` | `Posted` |
| Payment status | `REV` | `Reversed` |
| Payment status | `NSF` | `NSF` |
| Payment status | `PND` | `Pending` |
| Product status | `ACT` | `true` (BOOLEAN) |
| Product status | `INA` | `false` (BOOLEAN) |
| Property type | `SFR` | `Single Family` |
| Property type | `CND` | `Condominium` |
| Property type | `MFR` | `Multi-Family` |
| Property type | `TWN` | `Townhouse` |

**Fallback behavior:** If a code is encountered that isn't in the map, the trimmed original value is preserved and a warning is logged. This prevents silent data loss from unexpected codes.

### 5.4 Denormalization Removal

**Decision:** Drop `BORR_FST_NM`, `BORR_LST_NM`, and `BORR_SSN_LST4` from `CDW_LN_ACCT`. Use `borrower_id` FK instead.

**Rationale:** The borrower fields in the loan table are redundant copies of data in `CDW_BORR_MSTR`. In the modern schema, `loan_accounts.borrower_id` references `borrowers.borrower_id`, eliminating update anomalies.

### 5.5 Foreign Key Resolution

**Decision:** Use left outer joins to resolve legacy string IDs to modern surrogate BIGINT keys.

- `CDW_LN_ACCT.BORR_ID` → join `borrowers` on `external_id` → get `borrower_id`
- `CDW_LN_ACCT.PROD_CD` → join `loan_products` on `code` → get `product_id`
- `CDW_PMT_HIST.LN_ACCT_NBR` → join `loan_accounts` on `account_number` → get `loan_account_id`

**Orphan handling:** Rows with unresolved FKs are retained with NULL FK values. The pipeline logs a warning with the count of orphaned records. The data quality framework flags these as referential integrity failures.

### 5.6 Legacy ID Preservation

**Decision:** Preserve original IDs in dedicated columns for audit/traceability.

- `CDW_BORR_MSTR.BORR_ID` → `borrowers.external_id`
- `CDW_PMT_HIST.PMT_SEQ_NBR` → `payments.legacy_sequence_nbr`
- `CDW_BORR_MSTR.BORR_REC_TYP` → `borrowers._legacy_record_type`

---

## 6. Partitioning Strategy

| Table | Partition Column | Rationale |
|-------|-----------------|-----------|
| `borrowers` | `status` | Low cardinality (Active/Inactive). Most queries filter by status. Enables partition pruning for active-borrower dashboards. |
| `loan_products` | *(none)* | Very small reference table (~10s of rows). Partitioning would cause excessive small files. |
| `loan_accounts` | `origination_year` | Natural time dimension for vintage/cohort analysis. Moderate cardinality (years span ~10-30). Supports efficient time-range scans. |
| `payments` | `payment_year` | High-volume table that grows over time. Year partitioning supports monthly/quarterly reconciliation queries with partition pruning. |

### Why Not Partition by Status on Loans?

While `status` is a common filter, it has only 4 values and loan status changes over time (Active → Closed). This would cause frequent partition-level updates. `origination_year` is immutable once set, making it a more stable partition key.

---

## 7. Execution Order

The pipeline must run in dependency order because fact tables depend on dimension tables for FK resolution.

```
Step 1 (parallel):
  ├── databricks/ddl/00_create_schema.sql     → Create catalog + schema
  │
Step 2 (parallel - no FK dependencies):
  ├── databricks/ddl/01_borrowers.sql         → Create borrowers table
  ├── databricks/ddl/02_loan_products.sql     → Create loan_products table
  │
Step 3 (sequential - depends on Step 2):
  ├── databricks/ddl/03_loan_accounts.sql     → Create loan_accounts table
  ├── databricks/ddl/04_payments.sql          → Create payments table
  │
Step 4 (parallel - dimension ingestion):
  ├── ingest_borrowers.py                     → Load borrowers
  ├── ingest_loan_products.py                 → Load loan_products
  │
Step 5 (sequential - depends on Step 4):
  ├── ingest_loan_accounts.py                 → Load loan_accounts (FK → borrowers, products)
  │
Step 6 (sequential - depends on Step 5):
  ├── ingest_payments.py                      → Load payments (FK → loan_accounts)
  │
Step 7:
  └── data_quality_checks.py                  → Validate all tables
```

### Using the Orchestrator

For convenience, `run_full_pipeline.py` executes Steps 4–6 in the correct order:

```bash
spark-submit --master local[*] databricks/ingestion/run_full_pipeline.py \
    --landing-path /mnt/landing \
    --source-format csv
```

### Databricks Workflow (Recommended)

Create a Databricks Workflow with the following task DAG:

```
[create_schema] → [create_dim_tables] → [create_fact_tables]
                                              ↓
[ingest_borrowers] ──┐
                     ├→ [ingest_loan_accounts] → [ingest_payments] → [quality_checks]
[ingest_products] ───┘
```

---

## 8. Data Quality Validation

Run the quality framework after ingestion completes:

```bash
spark-submit --master local[*] databricks/quality/data_quality_checks.py \
    --landing-path /mnt/landing \
    --source-format csv \
    --report-path /mnt/reports/DATA_QUALITY_REPORT.md
```

### Checks Performed

| Category | Check | Severity |
|----------|-------|----------|
| Row Count | Source vs. target count for each table | ERROR |
| Null Check | Required columns have no NULLs | ERROR |
| Referential Integrity | loan_accounts.borrower_id exists in borrowers | ERROR |
| Referential Integrity | loan_accounts.product_id exists in loan_products | ERROR |
| Referential Integrity | payments.loan_account_id exists in loan_accounts | ERROR |
| Business Rule | Active loans have current_balance > 0 | ERROR |
| Business Rule | Interest rate between 0 and 100 | ERROR |
| Business Rule | Maturity date after origination date | ERROR |
| Business Rule | LTV percent between 0 and 200 | WARNING |
| Business Rule | Delinquency days non-negative | ERROR |
| Business Rule | Loan status is a known value | ERROR |
| Business Rule | Payment component sum equals total | WARNING |
| Business Rule | Payment status is a known value | ERROR |

### Expected Results (Seed Data)

With the provided seed data (5 borrowers, 5 products, 5 loans, 10 payments), all checks should PASS.

---

## 9. Rollback Procedure

Delta Lake supports time travel, making rollback straightforward:

```sql
-- View table history
DESCRIBE HISTORY loan_catalog.loan_warehouse.borrowers;

-- Restore to a specific version
RESTORE TABLE loan_catalog.loan_warehouse.borrowers TO VERSION AS OF 0;

-- Or restore to a timestamp
RESTORE TABLE loan_catalog.loan_warehouse.borrowers
    TO TIMESTAMP AS OF '2025-01-01T00:00:00';
```

To fully remove migrated data and start over:

```sql
-- Truncate all tables in reverse dependency order
TRUNCATE TABLE loan_catalog.loan_warehouse.payments;
TRUNCATE TABLE loan_catalog.loan_warehouse.loan_accounts;
TRUNCATE TABLE loan_catalog.loan_warehouse.loan_products;
TRUNCATE TABLE loan_catalog.loan_warehouse.borrowers;
```

---

## 10. Operational Notes

### Source File Preparation

Before running the pipeline, extract legacy data to CSV or Parquet files in the landing zone:

```
/mnt/landing/
  ├── cdw_borr_mstr.csv     (header row required for CSV)
  ├── cdw_ln_prod.csv
  ├── cdw_ln_acct.csv
  └── cdw_pmt_hist.csv
```

CSV files must use the original CDW column names as headers.

### Idempotency

The pipeline uses `overwrite` mode by default, meaning it can be safely re-run without creating duplicates. For incremental loads, use `--mode append` and implement deduplication logic upstream.

### Error Handling Philosophy

- **No silent drops:** The pipeline never silently discards records. Unparseable values become NULL; the row remains in the target.
- **Log everything:** All parse failures, NULL counts, and FK resolution misses are logged with WARNING level.
- **Post-hoc validation:** The data quality framework runs after ingestion and produces a structured report. A non-zero exit code from the quality check script signals failures.

### Monitoring

- Check Spark UI for job/stage progress during ingestion
- Review the `_ingestion_ts` column to verify when data was last loaded
- Schedule `data_quality_checks.py` as a downstream task in your Databricks Workflow
- Set up alerts on the quality check job's exit code (0 = pass, 1 = fail)

### Future Enhancements

1. **Incremental CDC:** Replace full-load `overwrite` with Delta Lake `MERGE` for change data capture
2. **Schema evolution:** Enable `delta.columnMapping.mode = 'name'` for safe column adds/renames
3. **Data lineage:** Integrate with Unity Catalog lineage tracking
4. **Streaming ingestion:** Convert batch jobs to Structured Streaming for near-real-time updates
5. **Re-encryption:** The `ssn_hash` column carries the legacy encryption; consider re-encrypting with a modern key management solution
