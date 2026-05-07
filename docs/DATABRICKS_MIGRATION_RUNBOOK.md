# Databricks Migration Runbook

> Legacy CDW (Corporate Data Warehouse) to Delta Lake on Databricks

---

## 1. Overview

This runbook documents the migration of four legacy CDW tables from an all-VARCHAR, denormalized H2 database to a properly typed, normalized Delta Lake schema on Databricks.

| Legacy Table | Modern Table | Record Type |
|---|---|---|
| `CDW_BORR_MSTR` | `loan_warehouse.borrowers` | Borrower master |
| `CDW_LN_PROD` | `loan_warehouse.loan_products` | Loan product catalog |
| `CDW_LN_ACCT` | `loan_warehouse.loan_accounts` | Loan accounts (denormalized) |
| `CDW_PMT_HIST` | `loan_warehouse.payments` | Payment history |

---

## 2. Column Mappings

### 2.1 CDW_BORR_MSTR -> borrowers

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `BORR_ID` | `external_id` | VARCHAR -> STRING | Direct copy |
| `BORR_FST_NM` | `first_name` | VARCHAR -> STRING | Direct copy |
| `BORR_LST_NM` | `last_name` | VARCHAR -> STRING | Direct copy |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR -> STRING | Nullable; default empty string for display |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR -> STRING | Re-encryption recommended post-migration |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR -> DATE | Parse `MM/DD/YYYY` via `to_date()` |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR -> STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR -> STRING | Nullable |
| `BORR_CTY_NM` | `city` | VARCHAR -> STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR -> STRING | 2-letter code |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR -> STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR -> STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR -> STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR -> INT | `cast(IntegerType())`, validate 300-850 |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR -> STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR -> DECIMAL(12,2) | Strip commas via `regexp_replace` |
| `BORR_CRET_DT` | `created_at` | VARCHAR -> TIMESTAMP | Parse `MM/DD/YYYY` then cast |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR -> TIMESTAMP | Parse `MM/DD/YYYY` then cast |
| `BORR_STAT_CD` | `status` | VARCHAR -> STRING | Expand: `ACT`->`ACTIVE`, `INA`->`INACTIVE` |
| `BORR_REC_TYP` | *(dropped)* | — | Not needed in modern schema |

### 2.2 CDW_LN_PROD -> loan_products

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `PROD_CD` | `code` | VARCHAR -> STRING | Direct copy |
| `PROD_DESC_TXT` | `name` | VARCHAR -> STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR -> STRING | FXD, ARM, FHA, VA |
| `PROD_TERM_MOS` | `term_months` | VARCHAR -> INT | `cast(IntegerType())` |
| `PROD_RT_TYP` | `rate_type` | VARCHAR -> STRING | FIXED, VARIABLE |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR -> DECIMAL(12,2) | Strip commas |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR -> DECIMAL(12,2) | Strip commas |
| `PROD_STAT_CD` | `is_active` | VARCHAR -> BOOLEAN | `ACT`->true, else false |
| `PROD_EFF_DT` | `effective_date` | VARCHAR -> DATE | Parse `MM/DD/YYYY` |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR -> DATE | Parse `MM/DD/YYYY` |

### 2.3 CDW_LN_ACCT -> loan_accounts

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `LN_ACCT_NBR` | `account_number` | VARCHAR -> STRING | Direct copy |
| `BORR_ID` | `borrower_id` | VARCHAR -> BIGINT | FK lookup via `borrowers.external_id` |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_id` | VARCHAR -> BIGINT | FK lookup via `loan_products.code` |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR -> DECIMAL(12,2) | Strip commas |
| `LN_CURR_BAL` | `current_balance` | VARCHAR -> DECIMAL(12,2) | Strip commas |
| `LN_INT_RT` | `interest_rate` | VARCHAR -> DECIMAL(5,3) | Direct cast |
| `LN_TERM_MOS` | `term_months` | VARCHAR -> INT | Direct cast |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR -> DECIMAL(10,2) | Strip commas |
| `LN_ORIG_DT` | `origination_date` | VARCHAR -> DATE | Parse `MM/DD/YYYY` |
| `LN_MAT_DT` | `maturity_date` | VARCHAR -> DATE | Parse `MM/DD/YYYY` |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR -> DATE | Parse `MM/DD/YYYY` |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR -> DATE | Parse `MM/DD/YYYY` |
| `LN_STAT_CD` | `status` | VARCHAR -> STRING | Expand: ACT/CLO/DFT/FRB |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR -> INT | Default 0 for null |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR -> DECIMAL(10,2) | Strip commas |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR -> DECIMAL(5,2) | Direct cast |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR -> STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR -> STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR -> STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR -> STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR -> STRING | Expand: SFR/CND/MFR/TWN |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR -> DECIMAL(12,2) | Strip commas |
| `LN_CRET_DT` | `created_at` | VARCHAR -> TIMESTAMP | Parse then cast |
| `LN_UPDT_DT` | `updated_at` | VARCHAR -> TIMESTAMP | Parse then cast |

### 2.4 CDW_PMT_HIST -> payments

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `PMT_SEQ_NBR` | `legacy_sequence_id` | VARCHAR -> STRING | Retained for audit trail |
| `LN_ACCT_NBR` | `loan_account_id` | VARCHAR -> BIGINT | FK lookup via `loan_accounts.account_number` |
| `PMT_DT` | `payment_date` | VARCHAR -> DATE | Parse `MM/DD/YYYY` |
| `PMT_AMT` | `total_amount` | VARCHAR -> DECIMAL(10,2) | Strip commas |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR -> DECIMAL(10,2) | Strip commas |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR -> DECIMAL(10,2) | Strip commas |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR -> DECIMAL(10,2) | Default 0 |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR -> DECIMAL(10,2) | Default 0 |
| `PMT_TYP_CD` | `type` | VARCHAR -> STRING | Expand: REG/EXT/PRT/PRE |
| `PMT_STAT_CD` | `status` | VARCHAR -> STRING | Expand: PST/REV/NSF/PND |
| `PMT_RECV_DT` | `received_date` | VARCHAR -> DATE | Parse `MM/DD/YYYY` |
| `PMT_PROC_DT` | `processed_date` | VARCHAR -> DATE | Parse `MM/DD/YYYY` |
| `PMT_CRET_DT` | `created_at` | VARCHAR -> TIMESTAMP | Parse then cast |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR -> TIMESTAMP | Parse then cast |
| *(computed)* | `component_sum` | — | `principal + interest + escrow + late_fee` |
| *(computed)* | `reconciled` | — | `abs(total - component_sum) <= 0.02` |

---

## 3. Transformation Decisions

### 3.1 Date Parsing
- **Pattern:** `MM/dd/yyyy` via Spark's `to_date()` function
- **Rationale:** All legacy dates use this US-locale format. `to_date()` returns null for unparseable values (logged, not dropped).
- **Edge case:** Invalid dates (month > 12, day > 31) return null. Dates in alternate formats (e.g., `YYYY-MM-DD`) also return null and are quarantined.

### 3.2 Amount Parsing
- **Pattern:** `regexp_replace(col, r"[^0-9.\-]", "")` then cast to `DecimalType`
- **Rationale:** Legacy amounts contain commas as thousands separators. The regex approach also handles unexpected characters (`$`, spaces) that `replace(",", "")` would miss.
- **Edge case:** Completely non-numeric strings (e.g., `"N/A"`) produce null after cast, which is caught by required-field null checks.

### 3.3 Status Code Expansion
- **Borrower:** `ACT` -> `ACTIVE`, `INA` -> `INACTIVE`
- **Loan:** `ACT` -> `ACTIVE`, `CLO` -> `CLOSED`, `DFT` -> `DEFAULT`, `FRB` -> `FORBEARANCE`
- **Payment type:** `REG` -> `REGULAR`, `EXT` -> `EXTRA`, `PRT` -> `PARTIAL`, `PRE` -> `PREPAYMENT`
- **Payment status:** `PST` -> `POSTED`, `REV` -> `REVERSED`, `NSF` -> `NSF`, `PND` -> `PENDING`
- **Unknown codes:** Prefixed with `UNKNOWN:` and logged, not dropped.

### 3.4 Denormalization Removal
- `CDW_LN_ACCT` contains embedded borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`).
- These are **dropped** in the modern schema. The `borrower_id` FK replaces them.
- During migration, the denormalized names are cross-checked against `CDW_BORR_MSTR` for consistency before being dropped.

### 3.5 Foreign Key Resolution
- Legacy uses string IDs (`B-10001`, `FXD30`, `LN-2019-00142`).
- Modern uses auto-increment `BIGINT` IDs with the legacy ID stored as `external_id`/`code`/`account_number`.
- FK resolution is done via left joins during ingestion. Unresolvable FKs (orphaned records) are quarantined.

### 3.6 Payment Reconciliation
- Legacy data has known reconciliation issues (component sum != total for some records).
- The modern schema adds two computed columns: `component_sum` and `reconciled` (boolean).
- This preserves the original data while flagging discrepancies for audit.

---

## 4. Partitioning Strategy

| Table | Partition Column | Rationale |
|---|---|---|
| `loan_accounts` | `status` | Most queries filter by active/closed status. Partitioning by status provides efficient pruning (typically 80%+ records are ACTIVE). |
| `payments` | `status` | Separates posted payments (historical, rarely queried) from pending/reversed (actively monitored). |
| `borrowers` | *(none)* | Small dimension table (< 1M rows typically). Partitioning would add overhead without benefit. |
| `loan_products` | *(none)* | Tiny reference table (< 100 rows). No partitioning needed. |

**Alternative considered:** Partitioning `loan_accounts` by `origination_year` (extracted from `origination_date`). This would benefit time-range queries but requires a computed partition column. Status-based partitioning was chosen as the primary strategy because operational queries (active loans, defaulted loans) are more common than historical range queries.

---

## 5. Execution Order

The pipeline must be executed in this exact order due to FK dependencies:

```
Step 1: create_schema.sql          -- Create loan_warehouse schema
Step 2: create_borrowers.sql       -- No FK dependencies
Step 3: create_loan_products.sql   -- No FK dependencies
Step 4: create_loan_accounts.sql   -- Depends on borrowers + loan_products
Step 5: create_payments.sql        -- Depends on loan_accounts
Step 6: ingest_borrowers.py        -- No FK dependencies
Step 7: ingest_loan_products.py    -- No FK dependencies
Step 8: ingest_loan_accounts.py    -- Depends on borrowers + products being loaded
Step 9: ingest_payments.py         -- Depends on loan_accounts being loaded
Step 10: data_quality_checks.py    -- Validates all tables post-load
```

Steps 2-3 and 6-7 can be run in parallel within their respective groups.

**Orchestrator:** `databricks/quality/run_pipeline.py` executes the full pipeline in the correct order.

---

## 6. Quarantine Strategy

Records that fail critical validation are **not silently dropped**. Instead:

1. They are written to a quarantine table (e.g., `loan_warehouse._quarantine_borrowers`)
2. Each quarantine record includes:
   - All original columns
   - `_quarantine_reason` — human-readable explanation of why it failed
   - `_quarantine_ts` — timestamp of when it was quarantined
3. Row count reconciliation in the quality framework accounts for quarantined records: `target_count + quarantine_count == source_count`

---

## 7. Known Data Quality Issues

See `docs/DATA_ANOMALY_REPORT.md` for the full catalog. Key issues to monitor:

| Issue | Impact | Mitigation |
|---|---|---|
| Payment reconciliation failures | 3/10 seed records have mismatched totals | `reconciled` flag in payments table |
| All-VARCHAR source typing | Parse failures on malformed data | Robust regex-based parsing with null fallback |
| No FK constraints in legacy | Orphaned records possible | FK validation + quarantine during ingestion |
| Credit scores as strings | Out-of-range values undetected | Range validation (300-850) in quality checks |
| Denormalized borrower data | Name drift between tables | Cross-check during migration, then drop |

---

## 8. Post-Migration Verification

After running the pipeline:

1. Review the generated `DATA_QUALITY_REPORT.md` for any failed checks
2. Query quarantine tables for any rejected records:
   ```sql
   SELECT * FROM loan_warehouse._quarantine_borrowers;
   SELECT * FROM loan_warehouse._quarantine_loan_accounts;
   SELECT * FROM loan_warehouse._quarantine_payments;
   ```
3. Verify record counts match expectations
4. Spot-check a sample of records by joining modern tables back to legacy source
5. Validate that the Spring Boot service can read from modern tables (dual-read mode)
