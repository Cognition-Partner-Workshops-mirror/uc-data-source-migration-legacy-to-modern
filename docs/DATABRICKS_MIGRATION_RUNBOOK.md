# Databricks Migration Runbook

## CDW Legacy → Delta Lake Modern Schema

This runbook documents every transformation decision, column mapping, type conversion, partitioning rationale, and the recommended execution order for migrating from the legacy CDW (Corporate Data Warehouse) to Delta Lake on Databricks.

---

## Table of Contents

1. [Migration Overview](#migration-overview)
2. [Source System Summary](#source-system-summary)
3. [Target Schema Design](#target-schema-design)
4. [Column Mapping Reference](#column-mapping-reference)
5. [Transformation Decisions](#transformation-decisions)
6. [Partitioning Rationale](#partitioning-rationale)
7. [Execution Order](#execution-order)
8. [Data Quality Validation](#data-quality-validation)
9. [Rollback Procedure](#rollback-procedure)
10. [Known Data Anomalies](#known-data-anomalies)

---

## Migration Overview

| Attribute | Value |
|-----------|-------|
| **Source System** | Legacy CDW (Corporate Data Warehouse) |
| **Source Tables** | `CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Target Platform** | Databricks / Delta Lake |
| **Target Database** | `loan_warehouse` |
| **Target Tables** | `borrowers`, `loan_products`, `loan_accounts`, `payments` |
| **Migration Type** | Full historical load (overwrite), with support for incremental after initial load |
| **Data Format** | Source exported as CSV or Parquet; target is Delta Lake |

### Goals

1. **Type safety**: Replace all-VARCHAR legacy columns with proper Spark SQL types (DATE, DECIMAL, INT, BOOLEAN, TIMESTAMP)
2. **Normalization**: Remove denormalized borrower fields from loan accounts; use FK relationships instead
3. **Readability**: Replace cryptic abbreviated column names (e.g., `BORR_FST_NM`) with descriptive modern names (e.g., `first_name`)
4. **Code expansion**: Expand terse status/type abbreviations into human-readable values (e.g., `ACT` → `ACTIVE`)
5. **Data quality**: Flag and log all parse errors without dropping records; run validation after ingestion
6. **Lineage**: Add pipeline metadata columns (`_ingested_at`, `_source_system`) to every target table

---

## Source System Summary

The legacy CDW uses **all-VARCHAR columns** with no foreign key constraints, cryptic abbreviated names, and inconsistent data quality. Dates are stored as `MM/DD/YYYY` strings, amounts as comma-formatted strings (e.g., `"285,000"`), and status codes as 2-3 character abbreviations.

### Source Tables

| Legacy Table | Description | Row Volume (Seed) | Key Quality Issues |
|-------------|-------------|-------------------|-------------------|
| `CDW_BORR_MSTR` | Borrower master dimension | 5 | Nullable middle initial, credit score as string |
| `CDW_LN_PROD` | Loan product reference | 5 | Amount ranges as comma-formatted strings |
| `CDW_LN_ACCT` | Loan accounts (denormalized) | 5 | Embedded borrower fields, SSN last-4 contains phone suffixes, status codes |
| `CDW_PMT_HIST` | Payment history | 10 | Payment component sums don't match total, late payments with 0-day delinquency |

---

## Target Schema Design

### Entity-Relationship Model

```
borrowers (1) ──────< (N) loan_accounts (1) ──────< (N) payments
                              │
                              │ (N)
                              ▼
                         loan_products (1)
```

### Target Tables

| Modern Table | Source | Surrogate Key | Natural Key | Partition Column |
|-------------|--------|---------------|-------------|-----------------|
| `loan_warehouse.borrowers` | `CDW_BORR_MSTR` | `id` (BIGINT IDENTITY) | `external_id` | `state` |
| `loan_warehouse.loan_products` | `CDW_LN_PROD` | `id` (BIGINT IDENTITY) | `code` | *(none — small table)* |
| `loan_warehouse.loan_accounts` | `CDW_LN_ACCT` | `id` (BIGINT IDENTITY) | `account_number` | `status` |
| `loan_warehouse.payments` | `CDW_PMT_HIST` | `id` (BIGINT IDENTITY) | `legacy_payment_id` | `payment_year` |

---

## Column Mapping Reference

### CDW_BORR_MSTR → borrowers

| Legacy Column | Legacy Type | Modern Column | Modern Type | Transformation |
|---------------|-------------|---------------|-------------|----------------|
| `BORR_ID` | VARCHAR(20) | `external_id` | STRING | Direct copy |
| `BORR_FST_NM` | VARCHAR(50) | `first_name` | STRING | Direct copy |
| `BORR_LST_NM` | VARCHAR(50) | `last_name` | STRING | Direct copy |
| `BORR_MID_INIT` | VARCHAR(1) | `middle_initial` | STRING | Direct copy |
| `BORR_SSN_ENCR` | VARCHAR(100) | `ssn_hash` | STRING | Direct copy (re-encrypt recommended) |
| `BORR_DOB_DT` | VARCHAR(10) | `date_of_birth` | DATE | Parse `MM/dd/yyyy` → DATE |
| `BORR_ADDR_LN1` | VARCHAR(100) | `address_line1` | STRING | Direct copy |
| `BORR_ADDR_LN2` | VARCHAR(100) | `address_line2` | STRING | Direct copy |
| `BORR_CTY_NM` | VARCHAR(50) | `city` | STRING | Direct copy |
| `BORR_ST_CD` | VARCHAR(2) | `state` | STRING | Direct copy |
| `BORR_ZIP_CD` | VARCHAR(10) | `zip_code` | STRING | Direct copy |
| `BORR_PH_NBR` | VARCHAR(15) | `phone` | STRING | Direct copy |
| `BORR_EMAIL_ADDR` | VARCHAR(100) | `email` | STRING | Direct copy |
| `BORR_CRDT_SCR` | VARCHAR(5) | `credit_score` | INT | Parse string → integer; validate range 300-850 |
| `BORR_EMP_STAT` | VARCHAR(20) | `employment_status` | STRING | Direct copy |
| `BORR_ANN_INCM` | VARCHAR(15) | `annual_income` | DECIMAL(12,2) | Remove commas → parse decimal |
| `BORR_CRET_DT` | VARCHAR(10) | `created_at` | TIMESTAMP | Parse `MM/dd/yyyy` → timestamp (midnight) |
| `BORR_UPDT_DT` | VARCHAR(10) | `updated_at` | TIMESTAMP | Parse `MM/dd/yyyy` → timestamp (midnight) |
| `BORR_STAT_CD` | VARCHAR(5) | `status` | STRING | Expand: `ACT`→`ACTIVE`, `INA`→`INACTIVE` |
| `BORR_REC_TYP` | VARCHAR(10) | *(dropped)* | — | Not needed in modern schema |

### CDW_LN_PROD → loan_products

| Legacy Column | Legacy Type | Modern Column | Modern Type | Transformation |
|---------------|-------------|---------------|-------------|----------------|
| `PROD_CD` | VARCHAR(10) | `code` | STRING | Direct copy |
| `PROD_DESC_TXT` | VARCHAR(200) | `name` | STRING | Direct copy |
| `PROD_TYP_CD` | VARCHAR(5) | `type` | STRING | Direct copy |
| `PROD_TERM_MOS` | VARCHAR(5) | `term_months` | INT | Parse string → integer |
| `PROD_RT_TYP` | VARCHAR(10) | `rate_type` | STRING | Direct copy |
| `PROD_MIN_AMT` | VARCHAR(15) | `min_amount` | DECIMAL(12,2) | Remove commas → parse decimal |
| `PROD_MAX_AMT` | VARCHAR(15) | `max_amount` | DECIMAL(12,2) | Remove commas → parse decimal |
| `PROD_STAT_CD` | VARCHAR(5) | `is_active` | BOOLEAN | `ACT`→`true`, `INA`→`false` |
| `PROD_EFF_DT` | VARCHAR(10) | `effective_date` | DATE | Parse `MM/dd/yyyy` → DATE |
| `PROD_EXP_DT` | VARCHAR(10) | `expiration_date` | DATE | Parse `MM/dd/yyyy` → DATE |

### CDW_LN_ACCT → loan_accounts

| Legacy Column | Legacy Type | Modern Column | Modern Type | Transformation |
|---------------|-------------|---------------|-------------|----------------|
| `LN_ACCT_NBR` | VARCHAR(20) | `account_number` | STRING | Direct copy |
| `BORR_ID` | VARCHAR(20) | `borrower_id` | BIGINT | FK lookup: `borrowers.id` by `external_id` |
| `BORR_FST_NM` | VARCHAR(50) | *(dropped)* | — | Denormalized; use borrower FK instead |
| `BORR_LST_NM` | VARCHAR(50) | *(dropped)* | — | Denormalized; use borrower FK instead |
| `BORR_SSN_LST4` | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK instead |
| `PROD_CD` | VARCHAR(10) | `product_id` | BIGINT | FK lookup: `loan_products.id` by `code` |
| `LN_ORIG_AMT` | VARCHAR(15) | `original_amount` | DECIMAL(12,2) | Remove commas → parse decimal |
| `LN_CURR_BAL` | VARCHAR(15) | `current_balance` | DECIMAL(12,2) | Remove commas → parse decimal |
| `LN_INT_RT` | VARCHAR(8) | `interest_rate` | DECIMAL(5,3) | Parse string → decimal |
| `LN_TERM_MOS` | VARCHAR(5) | `term_months` | INT | Parse string → integer |
| `LN_PMT_AMT` | VARCHAR(15) | `monthly_payment` | DECIMAL(10,2) | Remove commas → parse decimal |
| `LN_ORIG_DT` | VARCHAR(10) | `origination_date` | DATE | Parse `MM/dd/yyyy` → DATE |
| `LN_MAT_DT` | VARCHAR(10) | `maturity_date` | DATE | Parse `MM/dd/yyyy` → DATE |
| `LN_1ST_PMT_DT` | VARCHAR(10) | `first_payment_date` | DATE | Parse `MM/dd/yyyy` → DATE |
| `LN_NXT_PMT_DT` | VARCHAR(10) | `next_payment_date` | DATE | Parse `MM/dd/yyyy` → DATE |
| `LN_STAT_CD` | VARCHAR(5) | `status` | STRING | Expand: `ACT`→`ACTIVE`, `CLO`→`CLOSED`, `DFT`→`DEFAULT`, `FRB`→`FORBEARANCE` |
| `LN_DLQ_DAYS` | VARCHAR(5) | `delinquency_days` | INT | Parse string → integer |
| `LN_ESCROW_BAL` | VARCHAR(15) | `escrow_balance` | DECIMAL(10,2) | Remove commas → parse decimal |
| `LN_LTV_PCT` | VARCHAR(8) | `ltv_percent` | DECIMAL(5,2) | Parse string → decimal |
| `PROP_ADDR_LN1` | VARCHAR(100) | `property_address` | STRING | Direct copy |
| `PROP_CTY_NM` | VARCHAR(50) | `property_city` | STRING | Direct copy |
| `PROP_ST_CD` | VARCHAR(2) | `property_state` | STRING | Direct copy |
| `PROP_ZIP_CD` | VARCHAR(10) | `property_zip` | STRING | Direct copy |
| `PROP_TYP_CD` | VARCHAR(10) | `property_type` | STRING | Expand: `SFR`→`Single Family`, `CND`→`Condominium`, `MFR`→`Multi-Family`, `TWN`→`Townhouse` |
| `PROP_APRS_VAL` | VARCHAR(15) | `appraised_value` | DECIMAL(12,2) | Remove commas → parse decimal |
| `LN_CRET_DT` | VARCHAR(10) | `created_at` | TIMESTAMP | Parse `MM/dd/yyyy` → timestamp |
| `LN_UPDT_DT` | VARCHAR(10) | `updated_at` | TIMESTAMP | Parse `MM/dd/yyyy` → timestamp |

### CDW_PMT_HIST → payments

| Legacy Column | Legacy Type | Modern Column | Modern Type | Transformation |
|---------------|-------------|---------------|-------------|----------------|
| `PMT_SEQ_NBR` | VARCHAR(20) | `legacy_payment_id` | STRING | Preserved for traceability |
| `LN_ACCT_NBR` | VARCHAR(20) | `loan_account_id` | BIGINT | FK lookup: `loan_accounts.id` by `account_number` |
| `PMT_DT` | VARCHAR(10) | `payment_date` | DATE | Parse `MM/dd/yyyy` → DATE |
| `PMT_AMT` | VARCHAR(15) | `total_amount` | DECIMAL(10,2) | Remove commas → parse decimal |
| `PMT_PRIN_AMT` | VARCHAR(15) | `principal_amount` | DECIMAL(10,2) | Remove commas → parse decimal |
| `PMT_INT_AMT` | VARCHAR(15) | `interest_amount` | DECIMAL(10,2) | Remove commas → parse decimal |
| `PMT_ESCROW_AMT` | VARCHAR(15) | `escrow_amount` | DECIMAL(10,2) | Remove commas → parse decimal |
| `PMT_LATE_FEE` | VARCHAR(15) | `late_fee` | DECIMAL(10,2) | Remove commas → parse decimal |
| `PMT_TYP_CD` | VARCHAR(5) | `type` | STRING | Expand: `REG`→`REGULAR`, `EXT`→`EXTRA`, `PRT`→`PARTIAL`, `PRE`→`PREPAYMENT` |
| `PMT_STAT_CD` | VARCHAR(5) | `status` | STRING | Expand: `PST`→`POSTED`, `REV`→`REVERSED`, `NSF`→`NSF`, `PND`→`PENDING` |
| `PMT_RECV_DT` | VARCHAR(10) | `received_date` | DATE | Parse `MM/dd/yyyy` → DATE |
| `PMT_PROC_DT` | VARCHAR(10) | `processed_date` | DATE | Parse `MM/dd/yyyy` → DATE |
| `PMT_CRET_DT` | VARCHAR(10) | `created_at` | TIMESTAMP | Parse `MM/dd/yyyy` → timestamp |
| `PMT_UPDT_DT` | VARCHAR(10) | `updated_at` | TIMESTAMP | Parse `MM/dd/yyyy` → timestamp |
| *(derived)* | — | `payment_year` | INT | `YEAR(payment_date)` — partition column |

---

## Transformation Decisions

### 1. Date Conversion: `MM/DD/YYYY` String → DATE / TIMESTAMP

**Decision:** Use `to_date(col, "MM/dd/yyyy")` and `to_timestamp(col, "MM/dd/yyyy")` with PySpark.

**Rationale:** The legacy system stores all dates as `MM/DD/YYYY` strings (e.g., `"03/15/1978"`). Spark's `to_date` with the format pattern handles this reliably. Malformed dates produce `null` rather than exceptions, and we flag these with `_parse_error` columns for quality reporting.

**Edge cases:**
- Null/empty source values → null target (no error flag)
- Invalid dates like `"02/30/2020"` → null with error flag
- Timestamps are set to midnight (`00:00:00`) since legacy only has date precision

### 2. Amount Conversion: Comma-Formatted String → DECIMAL

**Decision:** Strip `$` and `,` characters using `regexp_replace`, then cast to `DecimalType`.

**Rationale:** Legacy amounts are stored with formatting characters (e.g., `"285,000"`, `"1,487.02"`). The regex `[$,]` handles both dollar signs and commas in a single pass. Using `DecimalType` (not `DoubleType`) preserves exact precision for financial calculations.

**Precision choices:**
- Loan amounts, income, appraised values: `DECIMAL(12,2)` — supports up to $9,999,999,999.99
- Monthly payments, escrow, fees: `DECIMAL(10,2)` — supports up to $99,999,999.99
- Interest rates: `DECIMAL(5,3)` — supports rates like `4.750%`
- LTV percentages: `DECIMAL(5,2)` — supports up to `999.99%`

### 3. Status Code Expansion

**Decision:** Expand all abbreviated codes to full human-readable strings using lookup maps.

**Rationale:** The legacy CDW uses terse 2-3 character codes that are not self-documenting. Expanding them improves query readability and reduces the need for users to reference a code table. Unknown codes are mapped to `"UNKNOWN"` and flagged with `_unmapped` columns.

**Lookup maps:**
- Borrower status: `ACT`→`ACTIVE`, `INA`→`INACTIVE`
- Loan status: `ACT`→`ACTIVE`, `CLO`→`CLOSED`, `DFT`→`DEFAULT`, `FRB`→`FORBEARANCE`
- Product status: `ACT`→`true`, `INA`→`false` (boolean for products)
- Payment type: `REG`→`REGULAR`, `EXT`→`EXTRA`, `PRT`→`PARTIAL`, `PRE`→`PREPAYMENT`
- Payment status: `PST`→`POSTED`, `REV`→`REVERSED`, `NSF`→`NSF`, `PND`→`PENDING`
- Property type: `SFR`→`Single Family`, `CND`→`Condominium`, `MFR`→`Multi-Family`, `TWN`→`Townhouse`

### 4. Denormalization Removal

**Decision:** Drop redundant borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) from `loan_accounts` and replace with a `borrower_id` FK.

**Rationale:** The legacy `CDW_LN_ACCT` table embeds borrower data directly (denormalized). This causes data inconsistency — the `BORR_SSN_LST4` field actually contains phone number suffixes in the seed data, not SSN last-4 digits. Normalizing into a proper FK relationship eliminates this class of anomaly.

### 5. Surrogate Key Strategy

**Decision:** Use `BIGINT GENERATED ALWAYS AS IDENTITY` surrogate keys, preserving legacy natural keys as separate columns.

**Rationale:** Legacy IDs are string-based (e.g., `"B-10001"`, `"LN-2019-00142"`) which are inefficient for joins. Surrogate BIGINT keys enable faster joins and are standard in dimensional modeling. Legacy IDs are preserved as `external_id`, `account_number`, `legacy_payment_id` for traceability and reconciliation.

### 6. Error Handling: Flag, Don't Drop

**Decision:** All parse errors produce `null` values with accompanying `_parse_error` boolean flag columns. No records are ever dropped during ingestion.

**Rationale:** In a data warehouse migration, dropping records silently is unacceptable because it makes reconciliation impossible and can hide data quality issues. By flagging errors instead, the quality framework can report them and business stakeholders can decide how to handle them.

---

## Partitioning Rationale

| Table | Partition Column | Rationale |
|-------|-----------------|-----------|
| `borrowers` | `state` | Geographic queries are common in loan servicing (state-level regulatory reporting, regional portfolio analysis). 50 US states produce a manageable number of partitions. |
| `loan_products` | *(none)* | Small reference table (< 100 rows expected). Partitioning would add overhead with no benefit. |
| `loan_accounts` | `status` | Most queries filter by loan status (active portfolio, delinquent accounts, closed loans). 4 status values produce well-balanced partitions for active portfolios. |
| `payments` | `payment_year` | Payment queries are predominantly time-ranged (monthly statements, annual reports, YoY analysis). Year-based partitioning enables efficient partition pruning. |

All tables use Delta Lake auto-optimization:
- `delta.autoOptimize.optimizeWrite = true` — coalesces small files during writes
- `delta.autoOptimize.autoCompact = true` — compacts small files asynchronously

---

## Execution Order

The pipeline must execute in dependency order because of FK resolution requirements.

```
Step 1: Create database
   └── CREATE DATABASE IF NOT EXISTS loan_warehouse

Step 2: Execute DDL (create target tables)
   ├── 01_borrowers.sql
   ├── 02_loan_products.sql
   ├── 03_loan_accounts.sql
   └── 04_payments.sql

Step 3: Ingest dimension tables (no FK dependencies)
   ├── ingest_borrowers.py        ← no dependencies
   └── ingest_loan_products.py    ← no dependencies
   (These two can run in parallel)

Step 4: Ingest loan accounts (depends on borrowers + loan_products)
   └── ingest_loan_accounts.py    ← resolves borrower_id and product_id FKs

Step 5: Ingest payments (depends on loan_accounts)
   └── ingest_payments.py         ← resolves loan_account_id FK

Step 6: Run data quality checks
   └── data_quality_checks.py     ← validates all target tables
```

### Databricks Notebook Execution

```python
# Cell 1: Create database
spark.sql("CREATE DATABASE IF NOT EXISTS loan_warehouse")

# Cell 2: Run DDL scripts
%run ./databricks/ddl/01_borrowers
%run ./databricks/ddl/02_loan_products
%run ./databricks/ddl/03_loan_accounts
%run ./databricks/ddl/04_payments

# Cell 3: Ingest borrowers and loan products (can parallelize)
%run ./databricks/ingestion/ingest_borrowers
%run ./databricks/ingestion/ingest_loan_products

# Cell 4: Ingest loan accounts (depends on Step 3)
%run ./databricks/ingestion/ingest_loan_accounts

# Cell 5: Ingest payments (depends on Step 4)
%run ./databricks/ingestion/ingest_payments

# Cell 6: Run quality checks
%run ./databricks/quality/data_quality_checks
```

### Spark-Submit Execution

```bash
# Full pipeline (handles ordering internally)
spark-submit databricks/ingestion/run_pipeline.py

# Individual tables (must respect dependency order)
spark-submit databricks/ingestion/ingest_borrowers.py
spark-submit databricks/ingestion/ingest_loan_products.py
spark-submit databricks/ingestion/ingest_loan_accounts.py
spark-submit databricks/ingestion/ingest_payments.py

# Quality checks (after all ingestion completes)
spark-submit databricks/quality/data_quality_checks.py
```

---

## Data Quality Validation

After ingestion, the quality framework (`databricks/quality/data_quality_checks.py`) runs these checks:

### Check Categories

| Category | Checks | Description |
|----------|--------|-------------|
| **Row Count Reconciliation** | 4 | Source row count == target row count per table |
| **Null Checks** | 22 | Required fields contain no nulls |
| **Referential Integrity** | 3 | All FKs resolve to valid parent records |
| **Business Rules** | 8 | Domain-specific validation (balances, rates, dates, component sums) |

### Business Rules Validated

1. Active loans must have `current_balance > 0`
2. Active loans must have `delinquency_days >= 0`
3. Active loans must have `monthly_payment > 0`
4. `origination_date` must be before `maturity_date`
5. Interest rates must be in range 0-100
6. LTV percentages must be in range 0-200
7. Credit scores must be in range 300-850
8. Payment component sum (`principal + interest + escrow + late_fee`) must equal `total_amount`

### Expected Output

The quality framework generates `DATA_QUALITY_REPORT.md` with:
- Executive summary (total pass/fail/rate)
- Failed checks summary sorted by severity
- Detailed results grouped by category

---

## Rollback Procedure

Delta Lake's time travel makes rollback straightforward:

```sql
-- Check table history
DESCRIBE HISTORY loan_warehouse.borrowers;

-- Rollback to a specific version
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF <version_number>;

-- Rollback to a timestamp
RESTORE TABLE loan_warehouse.loan_accounts TO TIMESTAMP AS OF '2026-01-15T00:00:00Z';

-- Full rollback: drop all target tables
DROP TABLE IF EXISTS loan_warehouse.payments;
DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
DROP TABLE IF EXISTS loan_warehouse.loan_products;
DROP TABLE IF EXISTS loan_warehouse.borrowers;
```

**Important:** Drop tables in reverse dependency order (payments → loan_accounts → loan_products/borrowers) to avoid orphaned references.

---

## Known Data Anomalies

The following anomalies were identified in the legacy seed data during analysis (see `docs/DATA_ANOMALY_REPORT.md` for the full report):

| # | Anomaly | Severity | Affected Table | Impact on Migration |
|---|---------|----------|---------------|-------------------|
| 1 | `BORR_SSN_LST4` contains phone number suffixes, not SSN last-4 | Critical | `CDW_LN_ACCT` | Dropped during normalization (column not carried to modern schema) |
| 2 | Payment component amounts don't sum to stated total | Critical | `CDW_PMT_HIST` | Detected by quality framework `payment_component_sum` check |
| 3 | Credit score as unparseable string | Critical | `CDW_BORR_MSTR` | Flagged by `credit_score_parse_error`; null in target |
| 4 | Nullable middle initial | Low | `CDW_BORR_MSTR` | Carried through as null (field is optional) |
| 5 | 15-day delinquency on loan with `ACT` status and `0` delinquency days | High | `CDW_LN_ACCT` | Inconsistency preserved; surfaced by quality framework |
| 6 | Late payment fees with zero delinquency days | Medium | `CDW_PMT_HIST` | Preserved as-is; flagged for business review |

These anomalies are **not corrected** during migration — they are faithfully carried through and flagged by the quality framework. Correction should be a separate, business-approved process.
