# Databricks Migration Runbook

## 1. Overview

This runbook documents the migration of loan management data from the legacy CDW (Corporate Data Warehouse) schema to a modern, typed Delta Lake schema on Databricks. The legacy system stores all values as VARCHAR strings with cryptic abbreviated column names, no foreign keys, and denormalized structures. The target schema uses proper Spark SQL types, meaningful names, normalized relationships, and Delta Lake features.

### Source System

| Table | Description | Row Volume (seed) |
|-------|-------------|-------------------|
| `CDW_BORR_MSTR` | Borrower master dimension | 5 |
| `CDW_LN_PROD` | Loan product reference data | 5 |
| `CDW_LN_ACCT` | Loan accounts (denormalized with borrower fields) | 5 |
| `CDW_PMT_HIST` | Payment history transactions | 10 |

### Target System

| Delta Table | Source | Partition Strategy |
|-------------|--------|--------------------|
| `loan_warehouse.borrowers` | `CDW_BORR_MSTR` | By `status` |
| `loan_warehouse.loan_products` | `CDW_LN_PROD` | None (small reference table) |
| `loan_warehouse.loan_accounts` | `CDW_LN_ACCT` | By `status`, `origination_year` |
| `loan_warehouse.payments` | `CDW_PMT_HIST` | By `payment_year` |

---

## 2. Column Mapping Reference

### 2.1 CDW_BORR_MSTR -> borrowers

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `BORR_ID` | `external_id` | VARCHAR -> STRING | Direct copy; unique identifier preserved |
| `BORR_FST_NM` | `first_name` | VARCHAR -> STRING | Direct copy |
| `BORR_LST_NM` | `last_name` | VARCHAR -> STRING | Direct copy |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR -> STRING | Direct copy; nullable |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR -> STRING | Direct copy; re-encryption recommended post-migration |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR -> DATE | Parse `MM/DD/YYYY` string to DateType |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR -> STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR -> STRING | Direct copy; nullable |
| `BORR_CTY_NM` | `city` | VARCHAR -> STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR -> STRING | Direct copy; 2-character state code |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR -> STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR -> STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR -> STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR -> INT | Cast string to integer |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR -> STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR -> DECIMAL(12,2) | Remove commas, parse to decimal |
| `BORR_CRET_DT` | `created_at` | VARCHAR -> TIMESTAMP | Parse `MM/DD/YYYY` to timestamp |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR -> TIMESTAMP | Parse `MM/DD/YYYY` to timestamp |
| `BORR_STAT_CD` | `status` | VARCHAR -> STRING | Expand: ACT->Active, INA->Inactive |
| `BORR_REC_TYP` | *(dropped)* | — | Record type flag not needed in modern schema |

### 2.2 CDW_LN_PROD -> loan_products

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `PROD_CD` | `code` | VARCHAR -> STRING | Direct copy; unique key |
| `PROD_DESC_TXT` | `name` | VARCHAR -> STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR -> STRING | Direct copy (FXD, ARM, FHA, VA) |
| `PROD_TERM_MOS` | `term_months` | VARCHAR -> INT | Cast string to integer |
| `PROD_RT_TYP` | `rate_type` | VARCHAR -> STRING | Direct copy (FIXED, VARIABLE) |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR -> DECIMAL(12,2) | Remove commas, parse |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR -> DECIMAL(12,2) | Remove commas, parse |
| `PROD_STAT_CD` | `is_active` | VARCHAR -> BOOLEAN | ACT->true, INA->false |
| `PROD_EFF_DT` | `effective_date` | VARCHAR -> DATE | Parse `MM/DD/YYYY` |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR -> DATE | Parse `MM/DD/YYYY` |

### 2.3 CDW_LN_ACCT -> loan_accounts

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `LN_ACCT_NBR` | `account_number` | VARCHAR -> STRING | Direct copy; unique key |
| `BORR_ID` | `borrower_id` | VARCHAR -> BIGINT | FK lookup: `borrowers.borrower_id` via `external_id` |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_id` | VARCHAR -> BIGINT | FK lookup: `loan_products.product_id` via `code` |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR -> DECIMAL(12,2) | Remove commas, parse |
| `LN_CURR_BAL` | `current_balance` | VARCHAR -> DECIMAL(12,2) | Remove commas, parse |
| `LN_INT_RT` | `interest_rate` | VARCHAR -> DECIMAL(5,3) | Parse string "5.250" to decimal |
| `LN_TERM_MOS` | `term_months` | VARCHAR -> INT | Cast string to integer |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR -> DECIMAL(10,2) | Remove commas, parse |
| `LN_ORIG_DT` | `origination_date` | VARCHAR -> DATE | Parse `MM/DD/YYYY` |
| `LN_MAT_DT` | `maturity_date` | VARCHAR -> DATE | Parse `MM/DD/YYYY` |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR -> DATE | Parse `MM/DD/YYYY` |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR -> DATE | Parse `MM/DD/YYYY` |
| `LN_STAT_CD` | `status` | VARCHAR -> STRING | Expand: ACT->Active, CLO->Closed, DFT->Default, FRB->Forbearance |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR -> INT | Cast string to integer |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR -> DECIMAL(10,2) | Remove commas, parse |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR -> DECIMAL(5,2) | Parse string to decimal |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR -> STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR -> STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR -> STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR -> STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR -> STRING | Expand: SFR->Single Family, CND->Condominium, MFR->Multi-Family, TWN->Townhouse |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR -> DECIMAL(12,2) | Remove commas, parse |
| `LN_CRET_DT` | `created_at` | VARCHAR -> TIMESTAMP | Parse `MM/DD/YYYY` |
| `LN_UPDT_DT` | `updated_at` | VARCHAR -> TIMESTAMP | Parse `MM/DD/YYYY` |

### 2.4 CDW_PMT_HIST -> payments

| Legacy Column | Modern Column | Type Conversion | Notes |
|---------------|---------------|-----------------|-------|
| `PMT_SEQ_NBR` | `legacy_sequence_nbr` | VARCHAR -> STRING | Preserved for lineage; new `payment_id` auto-generated |
| `LN_ACCT_NBR` | `loan_account_id` | VARCHAR -> BIGINT | FK lookup: `loan_accounts.loan_account_id` via `account_number` |
| `PMT_DT` | `payment_date` | VARCHAR -> DATE | Parse `MM/DD/YYYY` |
| `PMT_AMT` | `total_amount` | VARCHAR -> DECIMAL(10,2) | Remove commas, parse |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR -> DECIMAL(10,2) | Remove commas, parse |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR -> DECIMAL(10,2) | Remove commas, parse |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR -> DECIMAL(10,2) | Remove commas, parse |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR -> DECIMAL(10,2) | Remove commas, parse |
| `PMT_TYP_CD` | `type` | VARCHAR -> STRING | Expand: REG->Regular, EXT->Extra, PRT->Partial, PRE->Prepayment |
| `PMT_STAT_CD` | `status` | VARCHAR -> STRING | Expand: PST->Posted, REV->Reversed, NSF->NSF, PND->Pending |
| `PMT_RECV_DT` | `received_date` | VARCHAR -> DATE | Parse `MM/DD/YYYY` |
| `PMT_PROC_DT` | `processed_date` | VARCHAR -> DATE | Parse `MM/DD/YYYY` |
| `PMT_CRET_DT` | `created_at` | VARCHAR -> TIMESTAMP | Parse `MM/DD/YYYY` |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR -> TIMESTAMP | Parse `MM/DD/YYYY` |

---

## 3. Transformation Decisions

### 3.1 Date Handling

**Decision:** Parse all `MM/DD/YYYY` VARCHAR strings using `to_date(col, "MM/dd/yyyy")`.

**Rationale:** The legacy system stores dates exclusively in US format. Spark's `to_date` returns `null` for unparseable values rather than throwing exceptions, which allows the pipeline to continue and quarantine bad records.

**Columns affected:** `created_at`/`updated_at` fields are promoted to TIMESTAMP (midnight of the parsed date) to align with the modern schema convention. Date-only fields (e.g., `origination_date`, `payment_date`) remain DATE.

### 3.2 Amount Handling

**Decision:** Strip commas via `regexp_replace(col, ",", "")` then cast to `DecimalType`.

**Rationale:** Legacy amounts like `"285,000"` and `"271,432.56"` use US-locale comma-as-thousands-separator. The regex approach handles both whole numbers and decimals. Precision/scale are chosen per column based on expected value ranges:
- Loan amounts: `DECIMAL(12,2)` supports up to $9,999,999,999.99
- Payment amounts: `DECIMAL(10,2)` supports up to $99,999,999.99
- Interest rates: `DECIMAL(5,3)` supports up to 99.999%
- LTV: `DECIMAL(5,2)` supports up to 999.99%

### 3.3 Status Code Expansion

**Decision:** Expand abbreviations to human-readable values using static mapping dictionaries.

| Domain | Code | Expanded Value |
|--------|------|---------------|
| Borrower Status | ACT | Active |
| Borrower Status | INA | Inactive |
| Loan Status | ACT | Active |
| Loan Status | CLO | Closed |
| Loan Status | DFT | Default |
| Loan Status | FRB | Forbearance |
| Payment Type | REG | Regular |
| Payment Type | EXT | Extra |
| Payment Type | PRT | Partial |
| Payment Type | PRE | Prepayment |
| Payment Status | PST | Posted |
| Payment Status | REV | Reversed |
| Payment Status | NSF | NSF |
| Payment Status | PND | Pending |
| Property Type | SFR | Single Family |
| Property Type | CND | Condominium |
| Property Type | MFR | Multi-Family |
| Property Type | TWN | Townhouse |
| Product Status | ACT | true (boolean) |
| Product Status | INA | false (boolean) |

**Rationale:** Expanded values improve readability for downstream BI consumers. The `expand_status_code_preserving` function keeps the original value if no mapping exists, preventing silent data loss for unexpected codes.

### 3.4 Denormalization Removal

**Decision:** Drop `BORR_FST_NM`, `BORR_LST_NM`, and `BORR_SSN_LST4` from `CDW_LN_ACCT`. Replace with a `borrower_id` FK resolved via lookup join on `borrowers.external_id`.

**Rationale:** The legacy schema duplicates borrower data in every loan record. Normalizing into a separate `borrowers` dimension eliminates redundancy and ensures single-source-of-truth for borrower attributes.

### 3.5 Foreign Key Resolution

**Decision:** Use DataFrame left-joins to resolve legacy string identifiers to modern auto-generated BIGINT keys.

| FK Relationship | Join Logic |
|----------------|------------|
| `CDW_LN_ACCT.BORR_ID` -> `borrowers.borrower_id` | Join on `BORR_ID == borrowers.external_id` |
| `CDW_LN_ACCT.PROD_CD` -> `loan_products.product_id` | Join on `PROD_CD == loan_products.code` |
| `CDW_PMT_HIST.LN_ACCT_NBR` -> `loan_accounts.loan_account_id` | Join on `LN_ACCT_NBR == loan_accounts.account_number` |

Unresolved FKs (null after join) are logged and the row is quarantined.

### 3.6 Lineage Columns

**Decision:** Each target table includes `_legacy_*` columns preserving the original primary key and an `_ingestion_ts` timestamp.

**Rationale:** Enables traceability from modern records back to legacy source rows for audit and reconciliation.

---

## 4. Partitioning Rationale

| Table | Partition Column(s) | Rationale |
|-------|---------------------|-----------|
| `borrowers` | `status` | Most queries filter by active/inactive status; low cardinality (2 values) is acceptable for a dimension table |
| `loan_products` | None | Small reference table (~5-50 rows); partitioning adds overhead with no benefit |
| `loan_accounts` | `status`, `origination_year` | Status filters are common (active portfolio vs. closed). Year partitioning enables time-range pruning for vintage analysis |
| `payments` | `payment_year` | Payment queries are almost always scoped to a date range. Year partitioning provides good pruning. Z-ORDER by `loan_account_id` is recommended within partitions |

---

## 5. Execution Order

The pipeline must run in dependency order due to FK resolution joins:

```
Step 1: DDL       - Run 00_create_schema.sql (create catalog + schema)
                  - Run 01_borrowers.sql
                  - Run 02_loan_products.sql
                  - Run 03_loan_accounts.sql
                  - Run 04_payments.sql

Step 2: Ingestion - Run ingest_borrowers.py        (no dependencies)
                  - Run ingest_loan_products.py     (no dependencies)
                    [Steps 2a and 2b can run in parallel]
                  - Run ingest_loan_accounts.py     (depends on borrowers + loan_products)
                  - Run ingest_payments.py           (depends on loan_accounts)

Step 3: Quality   - Run data_quality_checks.py      (depends on all ingestion steps)

Step 4: Review    - Review DATA_QUALITY_REPORT.md
                  - Investigate any quarantine tables
                  - Verify row counts and business rules
```

### Orchestrator Script

For convenience, `databricks/ingestion/run_pipeline.py` runs Steps 2-2 sequentially:

```bash
spark-submit databricks/ingestion/run_pipeline.py \
    --landing-root /mnt/landing \
    --quarantine-root /mnt/quarantine \
    --format csv
```

### Quality Check

```bash
spark-submit databricks/quality/data_quality_checks.py \
    --source-root /mnt/landing \
    --source-format csv \
    --report-path /dbfs/reports/DATA_QUALITY_REPORT.md
```

---

## 6. Error Handling Strategy

| Scenario | Behavior |
|----------|----------|
| Unparseable date string | `to_date` returns `null`; row passes through but may be quarantined if it's a required field |
| Unparseable amount string | `cast` returns `null`; logged as warning, quarantined if required |
| Unresolved FK (no matching parent) | Left join produces `null` FK; logged with source IDs; row quarantined |
| Null in required column | Row sent to quarantine Delta table at `{quarantine_root}/{table_name}` |
| Unexpected status code | `expand_status_code_preserving` keeps original value; `expand_status_code` maps to "Unknown" |
| Duplicate primary key | Delta MERGE or unique constraint violation will surface at write time |

**Quarantine pattern:** Each ingestion script splits the transformed DataFrame into `good` (passes all required-field checks) and `quarantine` (fails at least one). Quarantine records are written to a separate Delta location for manual review. No records are silently dropped.

---

## 7. Delta Lake Table Properties

All tables are configured with:

```sql
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.tier'                     = 'gold'
)
```

- **autoOptimize.optimizeWrite:** Coalesces small files during writes
- **autoOptimize.autoCompact:** Triggers automatic compaction after writes
- **quality.tier = gold:** Metadata tag indicating this is production-quality, validated data

---

## 8. Post-Migration Validation Checklist

- [ ] Row counts match between source and target for all 4 tables
- [ ] No nulls in required columns (see quality check output)
- [ ] All FK references resolve (no orphans in loan_accounts or payments)
- [ ] Active loans have positive `current_balance`
- [ ] Closed loans have `maturity_date` populated
- [ ] LTV percentages are within 0-200% range
- [ ] Origination dates precede maturity dates
- [ ] Posted payments have positive `total_amount`
- [ ] Payment component amounts sum to `total_amount` (within rounding tolerance)
- [ ] Credit scores are within valid FICO range (300-850)
- [ ] Quarantine tables reviewed and any issues resolved

---

## 9. Prerequisites

- Databricks workspace with Unity Catalog enabled
- Cluster with Spark 3.x and Delta Lake support
- Source data exported from legacy CDW to landing zone as CSV or Parquet:
  - `/mnt/landing/cdw_borr_mstr/`
  - `/mnt/landing/cdw_ln_prod/`
  - `/mnt/landing/cdw_ln_acct/`
  - `/mnt/landing/cdw_pmt_hist/`
- Write access to the `loan_migration` catalog
- `CREATE CATALOG` / `CREATE SCHEMA` privileges (for initial DDL)
