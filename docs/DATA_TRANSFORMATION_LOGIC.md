# Data Transformation Logic

<!-- Documents all transformation logic implemented in the PySpark/Databricks
     migration pipelines (pipelines/ directory). Each section traces one legacy
     CDW table through Bronze → Silver → Gold, listing every column-level
     transformation, data quality check, and fallback behavior. -->

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Shared Transformation Functions](#shared-transformation-functions)
3. [Data Quality Framework](#data-quality-framework)
4. [Table-by-Table Transformations](#table-by-table-transformations)
   - [Borrowers (CDW_BORR_MSTR)](#borrowers-cdw_borr_mstr)
   - [Loan Products (CDW_LN_PROD)](#loan-products-cdw_ln_prod)
   - [Loan Accounts (CDW_LN_ACCT)](#loan-accounts-cdw_ln_acct)
   - [Payments (CDW_PMT_HIST)](#payments-cdw_pmt_hist)
5. [Gold Layer: FK Resolution & Surrogate Keys](#gold-layer-fk-resolution--surrogate-keys)
6. [Status Code Expansion Maps](#status-code-expansion-maps)
7. [Fallback & Default Behaviors](#fallback--default-behaviors)
8. [Configuration Reference](#configuration-reference)

---

## Architecture Overview

The pipeline follows a **medallion architecture** with three layers:

```
Legacy CDW (JDBC)
    │
    ▼
┌──────────────────────────────────────────────────┐
│  BRONZE  –  Raw Ingestion (01_bronze_ingestion)  │
│  1:1 copy of legacy tables, all types preserved  │
│  + lineage metadata columns                      │
└──────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────┐
│  SILVER  –  Cleansed & Typed                     │
│  02_silver_borrowers                             │
│  03_silver_loan_products                         │
│  04_silver_loan_accounts                         │
│  05_silver_payments                              │
│                                                  │
│  • Type coercion (VARCHAR → DATE, DECIMAL, INT)  │
│  • Status code expansion                         │
│  • Denormalized field removal                    │
│  • Data quality validation (non-blocking)        │
└──────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────┐
│  GOLD  –  Normalized & FK-Resolved               │
│  06_gold_final_tables                            │
│                                                  │
│  • Surrogate BIGINT key assignment               │
│  • Foreign key resolution via lookup joins       │
│  • Default coalescing (delinquency, escrow, fee) │
└──────────────────────────────────────────────────┘
```

Each layer writes Delta tables to Unity Catalog under the `loan_migration` catalog:
- `loan_migration.bronze.*` — raw copies
- `loan_migration.silver.*` — cleansed/typed
- `loan_migration.gold.*` — final normalized schema

---

## Shared Transformation Functions

All reusable column-level transformations live in `pipelines/utils/transformations.py`.

### `parse_legacy_date(col)`

Converts legacy `MM/dd/yyyy` VARCHAR strings to Spark `DateType`.

| Input | Output | Notes |
|-------|--------|-------|
| `"03/15/1978"` | `1978-03-15` | Standard conversion |
| `NULL` | `NULL` | Null passthrough |
| `""` (empty) | `NULL` | Trimmed, yields null on parse |
| `"1978-03-15"` | `NULL` | Wrong format → parse failure → null |
| `"02/30/2020"` | `NULL` | Impossible date → null |

**Implementation:** `F.to_date(F.trim(col), "MM/dd/yyyy")`

### `parse_legacy_timestamp(col)`

Same as `parse_legacy_date` but returns `TimestampType` with midnight (`00:00:00`) as the time component. Used for `created_at` and `updated_at` audit fields where the legacy system stored only dates.

**Implementation:** `F.to_timestamp(F.trim(col), "MM/dd/yyyy")`

### `parse_legacy_amount(col)`

Parses financial amount strings stored with commas and optional dollar signs into `DecimalType(12,2)`.

| Input | Output | Notes |
|-------|--------|-------|
| `"285,000"` | `285000.00` | Comma removal |
| `"$1,487.02"` | `1487.02` | Dollar sign + comma removal |
| `"1234.56"` | `1234.56` | Plain decimal passthrough |
| `NULL` | `0.00` | Null → fallback to zero |
| `"N/A"` | `0.00` | Unparseable → fallback to zero |
| `"0"` | `0.00` | Zero value |

**Implementation:**
1. `COALESCE(col, "0")` — replace null with "0"
2. `REGEXP_REPLACE(TRIM(...), '[$,]', '')` — strip `$` and `,`
3. `CAST(... AS DECIMAL(12,2))` — type cast
4. `COALESCE(..., 0.00)` — if cast fails, default to 0.00

### `parse_legacy_integer(col)`

Parses VARCHAR integer fields to `IntegerType`. Returns `NULL` for non-numeric values (no fallback default).

| Input | Output |
|-------|--------|
| `"720"` | `720` |
| `NULL` | `NULL` |
| `"N/A"` | `NULL` |
| `"  360  "` | `360` (trimmed) |

**Implementation:** `F.trim(col).cast(IntegerType())`

### `parse_legacy_rate(col)`

Parses interest rate strings to `DecimalType(5,3)`. Preserves 3 decimal places for rate precision.

| Input | Output |
|-------|--------|
| `"4.750"` | `4.750` |
| `"3.250"` | `3.250` |

**Implementation:** `F.trim(col).cast(DecimalType(5, 3))`

### `parse_legacy_percent(col)`

Parses percentage strings to `DecimalType(5,2)`. Used for LTV (loan-to-value) percent.

| Input | Output |
|-------|--------|
| `"82.5"` | `82.50` |

**Implementation:** `F.trim(col).cast(DecimalType(5, 2))`

### `expand_status_code(col, mapping)`

Maps legacy short status codes to human-readable expanded values using a dictionary lookup. Falls back to the trimmed original value if the code is not found in the mapping.

**Behavior:**
- Matching is case-insensitive (`F.upper(F.trim(col))`)
- Unknown codes pass through unchanged (e.g., `"XYZ"` → `"XYZ"`)
- Builds a chained `CASE WHEN` expression at query planning time

### `status_to_boolean(col, active_code="ACT")`

Converts a status code column to a boolean. Returns `true` if the trimmed, uppercased value equals the `active_code`, `false` otherwise (including null).

| Input | Output |
|-------|--------|
| `"ACT"` | `true` |
| `"INA"` | `false` |
| `NULL` | `false` |

### `null_safe_concat(*cols, separator=" ")`

Concatenates multiple columns with a separator, replacing nulls with empty strings so partial values still produce output. Used for building full names from first/middle/last components.

**Implementation:** `F.concat_ws(separator, *[COALESCE(c, "") for c in cols])`

---

## Data Quality Framework

All validation functions live in `pipelines/utils/data_quality.py`. Each returns a DataFrame of issue records conforming to `QUALITY_ISSUE_SCHEMA`:

```
table_name  STRING    — source table
record_id   STRING    — primary key of the offending record
field       STRING    — column(s) with the issue
severity    STRING    — CRITICAL | HIGH | MEDIUM | LOW
issue_type  STRING    — classification code
message     STRING    — human-readable description
raw_value   STRING    — the original value that failed validation
```

Quality checks run at the **Silver layer boundary** (pre-transformation) and are **non-blocking** — they log issues for auditing but do not halt the pipeline. This allows downstream quarantine table integration.

### Check Functions

| Function | Issue Type | Severity | What It Catches | Anomaly Ref |
|----------|-----------|----------|-----------------|-------------|
| `check_null_required_fields()` | `NULL_REQUIRED` | CRITICAL | Null or blank values in mandatory columns | ANO-008 |
| `check_date_parseable()` | `PARSE_FAILURE` | HIGH | Dates that don't match `MM/dd/yyyy` or are impossible (e.g., Feb 30) | ANO-006 |
| `check_numeric_parseable()` | `PARSE_FAILURE` | HIGH | Values that remain non-numeric after `$` / `,` removal | ANO-005 |
| `check_valid_status_codes()` | `INVALID_CODE` | MEDIUM | Status codes not in the allowed set | ANO-004 |
| `check_credit_score_range()` | `OUT_OF_RANGE` | MEDIUM | Credit scores outside [300, 850] | — |
| `check_payment_reconciliation()` | `RECONCILIATION_MISMATCH` | CRITICAL | `principal + interest + escrow + late_fee ≠ total` beyond $0.02 tolerance | ANO-001 |
| `check_delinquency_status_consistency()` | `STATUS_INCONSISTENCY` | CRITICAL | `delinquency_days > 0` with status `ACT` (should be DFT/DLQ/FRB) | ANO-003 |
| `check_referential_integrity()` | `ORPHANED_RECORD` | HIGH | Child FK values with no matching parent record | ANO-009 |

### Quality Check Summary Logging

`log_quality_summary(issues_df, pipeline_stage)` prints an aggregated count of issues by severity and type, plus a sample of the first 10 issues. In production, this would write to a monitoring/alerting table.

---

## Table-by-Table Transformations

### Borrowers (`CDW_BORR_MSTR`)

**Pipeline:** `02_silver_borrowers.py`  
**Source:** `bronze.cdw_borr_mstr` → **Target:** `silver.borrowers`

#### Pre-Transformation Quality Checks

| Check | Fields | Severity |
|-------|--------|----------|
| Null required fields | `BORR_ID`, `BORR_FST_NM`, `BORR_LST_NM` | CRITICAL |
| Date parseable | `BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT` | HIGH |
| Numeric parseable | `BORR_ANN_INCM` | HIGH |
| Credit score range | `BORR_CRDT_SCR` ∈ [300, 850] | MEDIUM |

#### Column Transformations

| Legacy Column | Modern Column | Transformation | Function |
|---------------|--------------|----------------|----------|
| `BORR_ID` | `external_id` | Direct copy | — |
| `BORR_FST_NM` | `first_name` | Trim whitespace | `F.trim()` |
| `BORR_LST_NM` | `last_name` | Trim whitespace | `F.trim()` |
| `BORR_MID_INIT` | `middle_initial` | Trim whitespace | `F.trim()` |
| `BORR_SSN_ENCR` | `ssn_hash` | Direct copy | — |
| `BORR_DOB_DT` | `date_of_birth` | `MM/dd/yyyy` → DATE | `parse_legacy_date()` |
| `BORR_ADDR_LN1` | `address_line1` | Trim whitespace | `F.trim()` |
| `BORR_ADDR_LN2` | `address_line2` | Trim whitespace | `F.trim()` |
| `BORR_CTY_NM` | `city` | Trim whitespace | `F.trim()` |
| `BORR_ST_CD` | `state` | Trim whitespace | `F.trim()` |
| `BORR_ZIP_CD` | `zip_code` | Trim whitespace | `F.trim()` |
| `BORR_PH_NBR` | `phone` | Trim whitespace | `F.trim()` |
| `BORR_EMAIL_ADDR` | `email` | Trim whitespace | `F.trim()` |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR → INT | `parse_legacy_integer()` |
| `BORR_EMP_STAT` | `employment_status` | Trim whitespace | `F.trim()` |
| `BORR_ANN_INCM` | `annual_income` | Remove commas → DECIMAL(12,2) | `parse_legacy_amount()` |
| `BORR_STAT_CD` | `status` | ACT→ACTIVE, INA→INACTIVE, etc. | `expand_status_code(BORROWER_STATUS_MAP)` |
| `BORR_CRET_DT` | `created_at` | `MM/dd/yyyy` → TIMESTAMP | `parse_legacy_timestamp()` |
| `BORR_UPDT_DT` | `updated_at` | `MM/dd/yyyy` → TIMESTAMP | `parse_legacy_timestamp()` |
| `BORR_REC_TYP` | *(dropped)* | Not needed in modern schema | — |

---

### Loan Products (`CDW_LN_PROD`)

**Pipeline:** `03_silver_loan_products.py`  
**Source:** `bronze.cdw_ln_prod` → **Target:** `silver.loan_products`

#### Pre-Transformation Quality Checks

| Check | Fields | Severity |
|-------|--------|----------|
| Null required fields | `PROD_CD`, `PROD_DESC_TXT`, `PROD_TYP_CD`, `PROD_TERM_MOS`, `PROD_RT_TYP` | CRITICAL |
| Numeric parseable | `PROD_TERM_MOS`, `PROD_MIN_AMT`, `PROD_MAX_AMT` | HIGH |
| Date parseable | `PROD_EFF_DT`, `PROD_EXP_DT` | HIGH |

#### Column Transformations

| Legacy Column | Modern Column | Transformation | Function |
|---------------|--------------|----------------|----------|
| `PROD_CD` | `code` | Trim | `F.trim()` |
| `PROD_DESC_TXT` | `name` | Trim | `F.trim()` |
| `PROD_TYP_CD` | `type` | Trim | `F.trim()` |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | `parse_legacy_integer()` |
| `PROD_RT_TYP` | `rate_type` | Trim | `F.trim()` |
| `PROD_MIN_AMT` | `min_amount` | Remove commas → DECIMAL(12,2) | `parse_legacy_amount()` |
| `PROD_MAX_AMT` | `max_amount` | Remove commas → DECIMAL(12,2) | `parse_legacy_amount()` |
| `PROD_STAT_CD` | `is_active` | ACT → `true`, else `false` | `status_to_boolean()` |
| `PROD_EFF_DT` | `effective_date` | `MM/dd/yyyy` → DATE | `parse_legacy_date()` |
| `PROD_EXP_DT` | `expiration_date` | `MM/dd/yyyy` → DATE | `parse_legacy_date()` |

---

### Loan Accounts (`CDW_LN_ACCT`)

**Pipeline:** `04_silver_loan_accounts.py`  
**Source:** `bronze.cdw_ln_acct` → **Target:** `silver.loan_accounts`

This table has the most complex transformations due to denormalized borrower fields, multiple amount/date columns, and cross-table quality checks.

#### Pre-Transformation Quality Checks

| Check | Fields | Severity |
|-------|--------|----------|
| Null required fields | `LN_ACCT_NBR`, `BORR_ID`, `PROD_CD`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_TERM_MOS`, `LN_PMT_AMT`, `LN_ORIG_DT`, `LN_MAT_DT` | CRITICAL |
| Date parseable | `LN_ORIG_DT`, `LN_MAT_DT`, `LN_1ST_PMT_DT`, `LN_NXT_PMT_DT`, `LN_CRET_DT`, `LN_UPDT_DT` | HIGH |
| Numeric parseable | `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_PMT_AMT`, `LN_ESCROW_BAL`, `PROP_APRS_VAL` | HIGH |
| Valid status codes | `LN_STAT_CD` ∈ {ACT, CLO, DFT, FRB, DLQ} | MEDIUM |
| Delinquency/status consistency | `LN_DLQ_DAYS > 0` with `LN_STAT_CD = ACT` | CRITICAL |
| Referential integrity | `BORR_ID` → `CDW_BORR_MSTR.BORR_ID` | HIGH |
| Referential integrity | `PROD_CD` → `CDW_LN_PROD.PROD_CD` | HIGH |

#### Column Transformations

| Legacy Column | Modern Column | Transformation | Function |
|---------------|--------------|----------------|----------|
| `LN_ACCT_NBR` | `account_number` | Trim | `F.trim()` |
| `BORR_ID` | `borrower_external_id` | Trim (FK resolved in gold) | `F.trim()` |
| `PROD_CD` | `product_code` | Trim (FK resolved in gold) | `F.trim()` |
| `LN_ORIG_AMT` | `original_amount` | Remove commas → DECIMAL(12,2) | `parse_legacy_amount()` |
| `LN_CURR_BAL` | `current_balance` | Remove commas → DECIMAL(12,2) | `parse_legacy_amount()` |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | `parse_legacy_rate()` |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | `parse_legacy_integer()` |
| `LN_PMT_AMT` | `monthly_payment` | Remove commas → DECIMAL(12,2) | `parse_legacy_amount()` |
| `LN_ORIG_DT` | `origination_date` | `MM/dd/yyyy` → DATE | `parse_legacy_date()` |
| `LN_MAT_DT` | `maturity_date` | `MM/dd/yyyy` → DATE | `parse_legacy_date()` |
| `LN_1ST_PMT_DT` | `first_payment_date` | `MM/dd/yyyy` → DATE | `parse_legacy_date()` |
| `LN_NXT_PMT_DT` | `next_payment_date` | `MM/dd/yyyy` → DATE | `parse_legacy_date()` |
| `LN_STAT_CD` | `status` | ACT→ACTIVE, CLO→CLOSED, etc. | `expand_status_code(LOAN_STATUS_MAP)` |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | `parse_legacy_integer()` |
| `LN_ESCROW_BAL` | `escrow_balance` | Remove commas → DECIMAL | `parse_legacy_amount()` |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | `parse_legacy_percent()` |
| `PROP_ADDR_LN1` | `property_address` | Trim | `F.trim()` |
| `PROP_CTY_NM` | `property_city` | Trim | `F.trim()` |
| `PROP_ST_CD` | `property_state` | Trim | `F.trim()` |
| `PROP_ZIP_CD` | `property_zip` | Trim | `F.trim()` |
| `PROP_TYP_CD` | `property_type` | SFR→Single Family, etc. | `expand_status_code(PROPERTY_TYPE_MAP)` |
| `PROP_APRS_VAL` | `appraised_value` | Remove commas → DECIMAL(12,2) | `parse_legacy_amount()` |
| `LN_CRET_DT` | `created_at` | `MM/dd/yyyy` → TIMESTAMP | `parse_legacy_timestamp()` |
| `LN_UPDT_DT` | `updated_at` | `MM/dd/yyyy` → TIMESTAMP | `parse_legacy_timestamp()` |
| `BORR_FST_NM` | *(dropped)* | Denormalized; use borrower FK | — |
| `BORR_LST_NM` | *(dropped)* | Denormalized; use borrower FK | — |
| `BORR_SSN_LST4` | *(dropped)* | Denormalized; use borrower FK | — |

---

### Payments (`CDW_PMT_HIST`)

**Pipeline:** `05_silver_payments.py`  
**Source:** `bronze.cdw_pmt_hist` → **Target:** `silver.payments`

#### Pre-Transformation Quality Checks

| Check | Fields | Severity |
|-------|--------|----------|
| Null required fields | `PMT_SEQ_NBR`, `LN_ACCT_NBR`, `PMT_DT`, `PMT_AMT`, `PMT_TYP_CD`, `PMT_STAT_CD` | CRITICAL |
| Date parseable | `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`, `PMT_CRET_DT`, `PMT_UPDT_DT` | HIGH |
| Numeric parseable | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` | HIGH |
| Valid status codes (type) | `PMT_TYP_CD` ∈ {REG, EXT, PRT, PRE} | MEDIUM |
| Valid status codes (status) | `PMT_STAT_CD` ∈ {PST, REV, NSF, PND} | MEDIUM |
| Payment reconciliation (ANO-001) | `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE ≈ PMT_AMT` (±$0.02) | CRITICAL |
| Referential integrity | `LN_ACCT_NBR` → `CDW_LN_ACCT.LN_ACCT_NBR` | HIGH |

#### Column Transformations

| Legacy Column | Modern Column | Transformation | Function |
|---------------|--------------|----------------|----------|
| `PMT_SEQ_NBR` | `legacy_payment_id` | Trim (PK assigned in gold) | `F.trim()` |
| `LN_ACCT_NBR` | `loan_account_number` | Trim (FK resolved in gold) | `F.trim()` |
| `PMT_DT` | `payment_date` | `MM/dd/yyyy` → DATE | `parse_legacy_date()` |
| `PMT_AMT` | `total_amount` | Remove commas → DECIMAL(10,2) | `parse_legacy_amount()` |
| `PMT_PRIN_AMT` | `principal_amount` | Remove commas → DECIMAL(10,2) | `parse_legacy_amount()` |
| `PMT_INT_AMT` | `interest_amount` | Remove commas → DECIMAL(10,2) | `parse_legacy_amount()` |
| `PMT_ESCROW_AMT` | `escrow_amount` | Remove commas → DECIMAL(10,2) | `parse_legacy_amount()` |
| `PMT_LATE_FEE` | `late_fee` | Remove commas → DECIMAL(10,2) | `parse_legacy_amount()` |
| `PMT_TYP_CD` | `type` | REG→REGULAR, EXT→EXTRA, etc. | `expand_status_code(PAYMENT_TYPE_MAP)` |
| `PMT_STAT_CD` | `status` | PST→POSTED, REV→REVERSED, etc. | `expand_status_code(PAYMENT_STATUS_MAP)` |
| `PMT_RECV_DT` | `received_date` | `MM/dd/yyyy` → DATE | `parse_legacy_date()` |
| `PMT_PROC_DT` | `processed_date` | `MM/dd/yyyy` → DATE | `parse_legacy_date()` |
| `PMT_CRET_DT` | `created_at` | `MM/dd/yyyy` → TIMESTAMP | `parse_legacy_timestamp()` |
| `PMT_UPDT_DT` | `updated_at` | `MM/dd/yyyy` → TIMESTAMP | `parse_legacy_timestamp()` |

---

## Gold Layer: FK Resolution & Surrogate Keys

**Pipeline:** `06_gold_final_tables.py`

The Gold layer performs two operations that cannot be done at the Silver level:

### 1. Surrogate Key Assignment

Each table receives an auto-increment `id` column via `monotonically_increasing_id() + 1`. This produces unique BIGINT primary keys within a single pipeline run.

```python
# Example: Gold borrowers
gold_borrowers = silver_borrowers.withColumn(
    "id", F.monotonically_increasing_id() + 1
)
```

> **Note:** `monotonically_increasing_id()` generates unique-but-not-sequential IDs across partitions. For production, consider Delta identity columns or UUID generation.

### 2. Foreign Key Resolution

Silver tables retain natural/business keys as strings (`borrower_external_id`, `product_code`, `loan_account_number`). The Gold layer resolves these to BIGINT foreign keys via lookup joins:

**Loan Accounts FK resolution:**
```
silver.loan_accounts.borrower_external_id  →  gold.borrowers.id    (via external_id match)
silver.loan_accounts.product_code          →  gold.loan_products.id (via code match)
```

**Payments FK resolution:**
```
silver.payments.loan_account_number  →  gold.loan_accounts.id  (via account_number match)
```

All FK joins use `LEFT JOIN` to preserve records even if the parent is missing (orphaned records). The pipeline logs a warning if any FK resolves to `NULL`.

### 3. Default Coalescing

The Gold layer applies final defaults for nullable numeric fields:

| Column | Default | Rationale |
|--------|---------|-----------|
| `loan_accounts.delinquency_days` | `0` | No delinquency by default |
| `loan_accounts.escrow_balance` | `0.00` | Zero escrow balance |
| `payments.late_fee` | `0.00` | No late fee by default |

---

## Status Code Expansion Maps

### Borrower Status (`BORROWER_STATUS_MAP`)

| Legacy Code | Expanded Value |
|-------------|---------------|
| `ACT` | `ACTIVE` |
| `INA` | `INACTIVE` |
| `DEC` | `DECEASED` |
| `SUS` | `SUSPENDED` |

### Loan Status (`LOAN_STATUS_MAP`)

| Legacy Code | Expanded Value |
|-------------|---------------|
| `ACT` | `ACTIVE` |
| `CLO` | `CLOSED` |
| `DFT` | `DEFAULT` |
| `FRB` | `FORBEARANCE` |
| `DLQ` | `DELINQUENT` |

### Payment Type (`PAYMENT_TYPE_MAP`)

| Legacy Code | Expanded Value |
|-------------|---------------|
| `REG` | `REGULAR` |
| `EXT` | `EXTRA` |
| `PRT` | `PARTIAL` |
| `PRE` | `PREPAYMENT` |

### Payment Status (`PAYMENT_STATUS_MAP`)

| Legacy Code | Expanded Value |
|-------------|---------------|
| `PST` | `POSTED` |
| `REV` | `REVERSED` |
| `NSF` | `NSF` |
| `PND` | `PENDING` |

### Property Type (`PROPERTY_TYPE_MAP`)

| Legacy Code | Expanded Value |
|-------------|---------------|
| `SFR` | `Single Family` |
| `CND` | `Condominium` |
| `MFR` | `Multi-Family` |
| `TWN` | `Townhouse` |

---

## Fallback & Default Behaviors

The pipeline is designed to be lenient — records with quality issues are transformed with safe defaults rather than rejected:

| Scenario | Behavior | Function |
|----------|----------|----------|
| Null or unparseable amount | Falls back to `0.00` | `parse_legacy_amount()` |
| Null or unparseable integer | Returns `NULL` | `parse_legacy_integer()` |
| Null or unparseable date | Returns `NULL` | `parse_legacy_date()` |
| Unknown status code | Passes through original trimmed value | `expand_status_code()` |
| Null status for boolean | Returns `false` | `status_to_boolean()` |
| Missing parent for FK join | FK column is `NULL` (left join) | Gold layer join |
| Null delinquency_days (Gold) | Coalesced to `0` | `COALESCE(..., 0)` |
| Null escrow_balance (Gold) | Coalesced to `0.00` | `COALESCE(..., 0.00)` |
| Null late_fee (Gold) | Coalesced to `0.00` | `COALESCE(..., 0.00)` |

**Spark configuration:** `spark.sql.ansi.enabled=false` is set in test fixtures to enable lenient casting (invalid casts return `NULL` instead of throwing exceptions).

---

## Configuration Reference

All configuration values are centralized in `pipelines/config/pipeline_config.py`:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `BRONZE_CATALOG` | `loan_migration` | Unity Catalog for bronze tables |
| `BRONZE_SCHEMA` | `bronze` | Schema for raw ingestion tables |
| `SILVER_CATALOG` | `loan_migration` | Unity Catalog for silver tables |
| `SILVER_SCHEMA` | `silver` | Schema for cleansed/typed tables |
| `GOLD_CATALOG` | `loan_migration` | Unity Catalog for gold tables |
| `GOLD_SCHEMA` | `gold` | Schema for final normalized tables |
| `LEGACY_JDBC_URL` | `jdbc:h2:mem:legacydb` | Placeholder; override in Databricks secrets |
| `LEGACY_JDBC_DRIVER` | `org.h2.Driver` | JDBC driver class |
| `LEGACY_DATE_FORMAT` | `MM/dd/yyyy` | Expected date format in legacy CDW |
| `PAYMENT_RECONCILIATION_TOLERANCE` | `$0.02` | Max allowed discrepancy for payment component sum |
| `CREDIT_SCORE_MIN` | `300` | Minimum valid FICO score |
| `CREDIT_SCORE_MAX` | `850` | Maximum valid FICO score |
| `MAX_NULL_PERCENT_CRITICAL` | `0.0%` | No nulls allowed in critical fields |
| `MAX_NULL_PERCENT_HIGH` | `5.0%` | Up to 5% nulls in high-priority fields |
| `MAX_NULL_PERCENT_MEDIUM` | `20.0%` | Up to 20% nulls in medium-priority fields |

### Bronze Metadata Columns

Every bronze table receives these lineage columns during ingestion:

| Column | Type | Value |
|--------|------|-------|
| `_ingested_at` | TIMESTAMP | `current_timestamp()` at ingestion |
| `_source_system` | STRING | `"CDW_LEGACY"` |
| `_source_table` | STRING | Original legacy table name |
| `_batch_id` | STRING | `YYYYMMdd_HHmmss` formatted batch timestamp |
