# Databricks Migration Runbook

## Legacy CDW → Modern Delta Lake Loan Warehouse

This document describes the complete migration pipeline that transforms the legacy CDW
(Corporate Data Warehouse) loan management schema into a modern, properly typed Delta Lake
data warehouse on Databricks.

---

## 1. Legacy Schema Overview

The legacy system stores **all columns as VARCHAR** with no foreign key constraints, cryptic
abbreviated column names, denormalized structures, and status codes stored as short
abbreviations.

### Source Tables

| Legacy Table | Description | Row Scope |
|---|---|---|
| `CDW_BORR_MSTR` | Borrower master dimension | All borrowers |
| `CDW_LN_PROD` | Loan product reference data | All product types |
| `CDW_LN_ACCT` | Loan accounts (denormalized — embeds borrower fields) | All loan accounts |
| `CDW_PMT_HIST` | Payment transaction history | All payment records |

### Key Legacy Problems Addressed

1. **All-VARCHAR typing** — dates stored as `MM/DD/YYYY` strings, amounts with embedded
   commas (`"285,000"`), integers as strings
2. **Cryptic column names** — e.g. `BORR_FST_NM`, `LN_CURR_BAL`, `PMT_ESCROW_AMT`
3. **No foreign keys** — `CDW_LN_ACCT.BORR_ID` has no constraint to `CDW_BORR_MSTR`
4. **Denormalized data** — borrower name and SSN duplicated inside `CDW_LN_ACCT`
5. **Abbreviated status codes** — `ACT`, `CLO`, `DFT`, `FRB` without documentation

---

## 2. Modern Target Schema

### Target Tables (Delta Lake)

| Modern Table | Source | Partitioning | Rationale |
|---|---|---|---|
| `loan_warehouse.borrowers` | `CDW_BORR_MSTR` | None | Small dimension; full scans are fast |
| `loan_warehouse.loan_products` | `CDW_LN_PROD` | None | Small reference table (~10s of rows) |
| `loan_warehouse.loan_accounts` | `CDW_LN_ACCT` | `origination_year` | Enables efficient vintage analysis and time-range queries |
| `loan_warehouse.payments` | `CDW_PMT_HIST` | `payment_year` | High-volume table; year partitioning optimises monthly/quarterly reporting |

### Partitioning Rationale

- **`loan_accounts` by `origination_year`**: Loan vintage analysis is a primary analytics
  use case. Partitioning by origination year allows Databricks to skip irrelevant partitions
  when filtering by loan cohort (e.g., "all 2020 originations"). The generated column
  `origination_year = YEAR(origination_date)` is computed automatically.

- **`payments` by `payment_year`**: Payment history is the highest-volume table and most
  queries filter by date range (monthly statements, quarterly reports). Year-based
  partitioning provides a good balance between partition count and skip efficiency.

- **`borrowers` and `loan_products`**: Not partitioned. These are low-cardinality
  dimension/reference tables where full scans are negligible.

---

## 3. Column Mapping Reference

### 3.1 CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `BORR_ID` | `external_id` | VARCHAR → STRING | Direct copy; used for FK resolution |
| `BORR_FST_NM` | `first_name` | VARCHAR → STRING | Direct copy |
| `BORR_LST_NM` | `last_name` | VARCHAR → STRING | Direct copy |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR → STRING | Direct copy |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR → STRING | Direct copy (re-encryption recommended) |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR → STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR → STRING | Direct copy |
| `BORR_CTY_NM` | `city` | VARCHAR → STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR → STRING | Direct copy |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR → STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR → STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR → STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR → INT | Parse string to integer |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR → STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `BORR_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` to midnight |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` to midnight |
| `BORR_STAT_CD` | `status` | VARCHAR → STRING | `ACT`→`Active`, `INA`→`Inactive` |
| `BORR_REC_TYP` | *(dropped)* | — | Not needed in modern schema |

### 3.2 CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `PROD_CD` | `code` | VARCHAR → STRING | Direct copy |
| `PROD_DESC_TXT` | `name` | VARCHAR → STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR → STRING | Direct copy (FXD, ARM, FHA, VA) |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | Parse string |
| `PROD_RT_TYP` | `rate_type` | VARCHAR → STRING | Direct copy (FIXED, VARIABLE) |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `PROD_STAT_CD` | `is_active` | VARCHAR → BOOLEAN | `ACT`→`true`, `INA`→`false` |
| `PROD_EFF_DT` | `effective_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |

### 3.3 CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `LN_ACCT_NBR` | `account_number` | VARCHAR → STRING | Direct copy |
| `BORR_ID` | `borrower_id` | VARCHAR → BIGINT | FK lookup via `borrowers.external_id` |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_id` | VARCHAR → BIGINT | FK lookup via `loan_products.code` |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | Parse string (e.g. "4.750") |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | Parse string |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `LN_ORIG_DT` | `origination_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_MAT_DT` | `maturity_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_STAT_CD` | `status` | VARCHAR → STRING | See status code table below |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | Parse string |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | Parse string |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR → STRING | See property type table below |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `LN_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| *(generated)* | `origination_year` | — | `YEAR(origination_date)`, partition key |

### 3.4 CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Conversion | Notes |
|---|---|---|---|
| `PMT_SEQ_NBR` | `legacy_payment_id` | VARCHAR → STRING | Preserved for traceability |
| `LN_ACCT_NBR` | `loan_account_id` | VARCHAR → BIGINT | FK lookup via `loan_accounts.account_number` |
| `PMT_DT` | `payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_AMT` | `total_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_TYP_CD` | `type` | VARCHAR → STRING | See payment type table below |
| `PMT_STAT_CD` | `status` | VARCHAR → STRING | See payment status table below |
| `PMT_RECV_DT` | `received_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_PROC_DT` | `processed_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| *(generated)* | `payment_year` | — | `YEAR(payment_date)`, partition key |

---

## 4. Status Code Expansion Reference

### Loan Status (`LN_STAT_CD`)

| Legacy Code | Modern Value |
|---|---|
| `ACT` | `Active` |
| `CLO` | `Closed` |
| `DFT` | `Default` |
| `FRB` | `Forbearance` |

### Borrower Status (`BORR_STAT_CD`)

| Legacy Code | Modern Value |
|---|---|
| `ACT` | `Active` |
| `INA` | `Inactive` |

### Product Status (`PROD_STAT_CD`)

| Legacy Code | Modern Value |
|---|---|
| `ACT` | `true` (boolean) |
| `INA` | `false` (boolean) |

### Payment Type (`PMT_TYP_CD`)

| Legacy Code | Modern Value |
|---|---|
| `REG` | `Regular` |
| `EXT` | `Extra` |
| `PRT` | `Partial` |
| `PRE` | `Prepayment` |

### Payment Status (`PMT_STAT_CD`)

| Legacy Code | Modern Value |
|---|---|
| `PST` | `Posted` |
| `REV` | `Reversed` |
| `NSF` | `NSF` |
| `PND` | `Pending` |

### Property Type (`PROP_TYP_CD`)

| Legacy Code | Modern Value |
|---|---|
| `SFR` | `Single Family` |
| `CND` | `Condominium` |
| `MFR` | `Multi-Family` |
| `TWN` | `Townhouse` |

---

## 5. Type Conversion Decisions

| Conversion | Approach | Rationale |
|---|---|---|
| Date strings → `DATE` | `to_date(col, "MM/dd/yyyy")` | Standard Spark SQL date parsing; flags parse failures |
| Date strings → `TIMESTAMP` | `to_timestamp(col, "MM/dd/yyyy")` | Sets time to midnight; used for audit columns |
| Amount strings → `DECIMAL` | `regexp_replace(col, ",", "").cast(DecimalType)` | Removes comma thousands separators before numeric cast |
| Integer strings → `INT` | `col.cast(IntegerType())` | Direct cast; flags non-numeric values |
| Status codes → expanded | `create_map` lookup with fallback to original value | Unknown codes preserved (not silently dropped) and flagged |
| Legacy string IDs → BIGINT FK | Left join to target dimension table | Unresolved FKs are logged and flagged, rows retained |

### Error Handling Strategy

- **No records are silently dropped.** Every transformation that could fail (date parse, numeric
  cast, status lookup, FK resolution) adds a `_flag_*` boolean column.
- Flag columns are logged via `log_parse_errors()` before being stripped prior to Delta write.
- Unresolved foreign keys result in `NULL` FK values that are caught by the data quality
  null checks.

---

## 6. Execution Order

The pipeline must be run in strict dependency order because downstream tables reference
upstream tables via foreign key lookups.

```
Step 1: Run DDL scripts          (create empty Delta tables)
Step 2: Ingest borrowers         (no dependencies)
Step 3: Ingest loan_products     (no dependencies)
Step 4: Ingest loan_accounts     (depends on borrowers + loan_products)
Step 5: Ingest payments          (depends on loan_accounts)
Step 6: Run data quality checks  (depends on all tables being populated)
```

### 6.1 Recommended Databricks Execution

**Option A: Single Notebook (Sequential)**

```python
# Cell 1 — DDL
for ddl_file in ["01_borrowers", "02_loan_products", "03_loan_accounts", "04_payments"]:
    spark.sql(open(f"databricks/ddl/{ddl_file}.sql").read())

# Cell 2 — Ingestion (run_pipeline.py handles ordering)
from databricks.ingestion.run_pipeline import run_all
results = run_all(spark)

# Cell 3 — Quality checks
from databricks.quality.generate_report import run_quality_checks
source_counts = {
    "cdw_borr_mstr": results["borrowers"]["source_rows"],
    "cdw_ln_prod": results["loan_products"]["source_rows"],
    "cdw_ln_acct": results["loan_accounts"]["source_rows"],
    "cdw_pmt_hist": results["payments"]["source_rows"],
}
report = run_quality_checks(spark, source_counts)
```

**Option B: Databricks Workflow (Job Tasks)**

```
Task 1: databricks/ddl/01_borrowers.sql         (SQL task)
Task 2: databricks/ddl/02_loan_products.sql      (SQL task)
Task 3: databricks/ddl/03_loan_accounts.sql       (SQL task, depends on 1, 2)
Task 4: databricks/ddl/04_payments.sql             (SQL task, depends on 3)
Task 5: databricks/ingestion/ingest_borrowers.py   (Python task, depends on 1)
Task 6: databricks/ingestion/ingest_loan_products.py (Python task, depends on 2)
Task 7: databricks/ingestion/ingest_loan_accounts.py (Python task, depends on 5, 6, 3)
Task 8: databricks/ingestion/ingest_payments.py     (Python task, depends on 7, 4)
Task 9: databricks/quality/generate_report.py       (Python task, depends on 5–8)
```

Tasks 5 and 6 can run in parallel since they have no mutual dependency.

---

## 7. Source Data Configuration

Each ingestion script reads from a configurable source path. Update these constants at the
top of each script (or pass via Databricks widgets/job parameters):

| Script | `SOURCE_PATH` Default | `SOURCE_FORMAT` |
|---|---|---|
| `ingest_borrowers.py` | `dbfs:/mnt/landing/legacy/cdw_borr_mstr` | csv |
| `ingest_loan_products.py` | `dbfs:/mnt/landing/legacy/cdw_ln_prod` | csv |
| `ingest_loan_accounts.py` | `dbfs:/mnt/landing/legacy/cdw_ln_acct` | csv |
| `ingest_payments.py` | `dbfs:/mnt/landing/legacy/cdw_pmt_hist` | csv |

To use Parquet sources instead, change `SOURCE_FORMAT = "parquet"` in each script.

### Preparing Source Files

Export each legacy table to CSV with headers matching the legacy column names:

```sql
-- Example: export from legacy database
SELECT * FROM CDW_BORR_MSTR;
-- Save as: cdw_borr_mstr/part-00000.csv (with header row)
```

Upload to the DBFS landing zone:
```bash
databricks fs cp ./cdw_borr_mstr dbfs:/mnt/landing/legacy/cdw_borr_mstr --recursive
```

---

## 8. Data Quality Checks

The quality framework (`databricks/quality/`) runs four categories of checks after ingestion:

| Category | Checks | Severity |
|---|---|---|
| **Row Count Reconciliation** | Source count = target count per table | FAIL on mismatch |
| **Null Checks** | Required fields (PKs, FKs, status, amounts) are non-null | FAIL on any NULL |
| **Referential Integrity** | All FK values exist in parent tables | FAIL on orphans |
| **Business Rules** | Domain logic: active balance > 0, date ordering, score ranges | FAIL or WARN |

### Business Rules Validated

| Rule | Severity | Description |
|---|---|---|
| Active loan positive balance | FAIL | `status = 'Active'` requires `current_balance > 0` |
| Closed loan has date | WARN | `status = 'Closed'` should have non-null `updated_at` |
| Payment non-negative | FAIL | `total_amount >= 0` for all payments |
| Origination before maturity | FAIL | `origination_date < maturity_date` |
| Credit score range | WARN | `credit_score` between 300 and 850 |
| LTV range | WARN | `ltv_percent` between 0 and 200 |

The output is written to `DATA_QUALITY_REPORT.md` with a summary table and per-check details.

---

## 9. Delta Lake Table Properties

All tables are created with:

| Property | Value | Rationale |
|---|---|---|
| `delta.autoOptimize.optimizeWrite` | `true` | Automatic file sizing for better read performance |
| `delta.autoOptimize.autoCompact` | `true` | Automatic small-file compaction |
| `delta.columnMapping.mode` | `name` | Enables column rename/drop without rewriting data |
| `delta.minReaderVersion` | `2` | Required for column mapping |
| `delta.minWriterVersion` | `5` | Required for column mapping and generated columns |

---

## 10. Post-Migration Checklist

- [ ] Upload legacy CSV/Parquet exports to DBFS landing zone
- [ ] Run DDL scripts to create target Delta tables
- [ ] Run ingestion pipeline (`run_pipeline.py`)
- [ ] Review `DATA_QUALITY_REPORT.md` — all checks should PASS
- [ ] Validate row counts match legacy system reports
- [ ] Spot-check 5-10 records across each table against legacy source
- [ ] Run `OPTIMIZE` on `loan_accounts` and `payments` tables for query performance
- [ ] Configure Delta Lake retention policies (`VACUUM` schedule)
- [ ] Update downstream dashboards/reports to point to new `loan_warehouse` schema
- [ ] Archive legacy source files after successful validation
