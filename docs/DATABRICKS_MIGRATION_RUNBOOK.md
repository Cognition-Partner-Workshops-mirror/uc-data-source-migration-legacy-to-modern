# Databricks Migration Runbook — Legacy CDW to Delta Lake

> **Scope:** Migrate 4 legacy CDW tables (`CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST`) to a modern normalized Delta Lake schema in Databricks.

---

## 1. Architecture Overview

```
Legacy CDW (VARCHAR everything)     →     Modern Delta Lake (typed, normalized)
─────────────────────────────────         ──────────────────────────────────────
CDW_BORR_MSTR (borrower master)    →     loan_warehouse.borrowers
CDW_LN_PROD   (loan products)     →     loan_warehouse.loan_products
CDW_LN_ACCT   (loan accounts)     →     loan_warehouse.loan_accounts (partitioned by status)
CDW_PMT_HIST  (payment history)   →     loan_warehouse.payments (partitioned by status)
```

**Key improvements:**
- Proper data types (DATE, DECIMAL, INT, BOOLEAN) replace all-VARCHAR
- Foreign keys replace denormalized data (borrower fields removed from loan_accounts)
- Status codes expanded to readable labels
- Delta Lake with auto-optimize and auto-compact enabled

---

## 2. Execution Order

The tables must be loaded in dependency order because FK resolution requires parent tables to exist first:

| Step | Script | Table | Depends On |
|------|--------|-------|------------|
| 1 | `databricks/ddl/01_borrowers.sql` | Create `borrowers` table | — |
| 2 | `databricks/ddl/02_loan_products.sql` | Create `loan_products` table | — |
| 3 | `databricks/ddl/03_loan_accounts.sql` | Create `loan_accounts` table | — |
| 4 | `databricks/ddl/04_payments.sql` | Create `payments` table | — |
| 5 | `databricks/ingestion/ingest_borrowers.py` | Load borrowers | DDL step 1 |
| 6 | `databricks/ingestion/ingest_loan_products.py` | Load loan products | DDL step 2 |
| 7 | `databricks/ingestion/ingest_loan_accounts.py` | Load loan accounts | Steps 5, 6 |
| 8 | `databricks/ingestion/ingest_payments.py` | Load payments | Step 7 |
| 9 | `databricks/quality/data_quality_checks.py` | Run quality checks | Steps 5–8 |

**In Databricks Workflows**, create a job with tasks in this order, each depending on the previous. Steps 1–4 (DDL) can be a single SQL notebook. Steps 5–6 can run in parallel since they have no mutual dependency.

---

## 3. Column Mapping Reference

### 3.1 CDW_BORR_MSTR → borrowers

| Legacy Column | Legacy Type | Modern Column | Modern Type | Transformation |
|---------------|-------------|---------------|-------------|----------------|
| `BORR_ID` | VARCHAR(20) | `external_id` | STRING | Direct copy |
| `BORR_FST_NM` | VARCHAR(50) | `first_name` | STRING | Direct copy |
| `BORR_LST_NM` | VARCHAR(50) | `last_name` | STRING | Direct copy |
| `BORR_MID_INIT` | VARCHAR(1) | `middle_initial` | STRING | Direct copy (nullable) |
| `BORR_SSN_ENCR` | VARCHAR(100) | `ssn_hash` | STRING | Direct copy |
| `BORR_DOB_DT` | VARCHAR(10) | `date_of_birth` | DATE | `to_date(col, "MM/dd/yyyy")` |
| `BORR_ADDR_LN1` | VARCHAR(100) | `address_line1` | STRING | Direct copy |
| `BORR_ADDR_LN2` | VARCHAR(100) | `address_line2` | STRING | Direct copy (nullable) |
| `BORR_CTY_NM` | VARCHAR(50) | `city` | STRING | Direct copy |
| `BORR_ST_CD` | VARCHAR(2) | `state` | STRING | Direct copy |
| `BORR_ZIP_CD` | VARCHAR(10) | `zip_code` | STRING | Direct copy |
| `BORR_PH_NBR` | VARCHAR(15) | `phone` | STRING | Direct copy |
| `BORR_EMAIL_ADDR` | VARCHAR(100) | `email` | STRING | Direct copy |
| `BORR_CRDT_SCR` | VARCHAR(5) | `credit_score` | INT | `cast(trim(col) as INT)` |
| `BORR_EMP_STAT` | VARCHAR(20) | `employment_status` | STRING | Direct copy |
| `BORR_ANN_INCM` | VARCHAR(15) | `annual_income` | DECIMAL(12,2) | Strip commas, cast |
| `BORR_CRET_DT` | VARCHAR(10) | `created_at` | TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| `BORR_UPDT_DT` | VARCHAR(10) | `updated_at` | TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| `BORR_STAT_CD` | VARCHAR(5) | `status` | STRING | ACT→ACTIVE, INA→INACTIVE |
| `BORR_REC_TYP` | VARCHAR(10) | *(dropped)* | — | Not needed in modern schema |

### 3.2 CDW_LN_PROD → loan_products

| Legacy Column | Legacy Type | Modern Column | Modern Type | Transformation |
|---------------|-------------|---------------|-------------|----------------|
| `PROD_CD` | VARCHAR(10) | `code` | STRING | Direct copy |
| `PROD_DESC_TXT` | VARCHAR(200) | `name` | STRING | Direct copy |
| `PROD_TYP_CD` | VARCHAR(5) | `type` | STRING | Direct copy |
| `PROD_TERM_MOS` | VARCHAR(5) | `term_months` | INT | `cast(trim(col) as INT)` |
| `PROD_RT_TYP` | VARCHAR(10) | `rate_type` | STRING | Direct copy |
| `PROD_MIN_AMT` | VARCHAR(15) | `min_amount` | DECIMAL(12,2) | Strip commas, cast |
| `PROD_MAX_AMT` | VARCHAR(15) | `max_amount` | DECIMAL(12,2) | Strip commas, cast |
| `PROD_STAT_CD` | VARCHAR(5) | `is_active` | BOOLEAN | ACT→true, else→false |
| `PROD_EFF_DT` | VARCHAR(10) | `effective_date` | DATE | `to_date(col, "MM/dd/yyyy")` |
| `PROD_EXP_DT` | VARCHAR(10) | `expiration_date` | DATE | `to_date(col, "MM/dd/yyyy")` |

### 3.3 CDW_LN_ACCT → loan_accounts

| Legacy Column | Legacy Type | Modern Column | Modern Type | Transformation |
|---------------|-------------|---------------|-------------|----------------|
| `LN_ACCT_NBR` | VARCHAR(20) | `account_number` | STRING | Direct copy |
| `BORR_ID` | VARCHAR(20) | `borrower_id` | BIGINT | FK lookup: `borrowers.borrower_id WHERE external_id = BORR_ID` |
| `BORR_FST_NM` | VARCHAR(50) | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | VARCHAR(50) | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK. **WARNING: known PII corruption (ANM-001)** |
| `PROD_CD` | VARCHAR(10) | `product_id` | BIGINT | FK lookup: `loan_products.product_id WHERE code = PROD_CD` |
| `LN_ORIG_AMT` | VARCHAR(15) | `original_amount` | DECIMAL(12,2) | Strip commas, cast |
| `LN_CURR_BAL` | VARCHAR(15) | `current_balance` | DECIMAL(12,2) | Strip commas, cast |
| `LN_INT_RT` | VARCHAR(8) | `interest_rate` | DECIMAL(5,3) | `cast(trim(col) as DECIMAL(5,3))` |
| `LN_TERM_MOS` | VARCHAR(5) | `term_months` | INT | `cast(trim(col) as INT)` |
| `LN_PMT_AMT` | VARCHAR(15) | `monthly_payment` | DECIMAL(10,2) | Strip commas, cast |
| `LN_ORIG_DT` | VARCHAR(10) | `origination_date` | DATE | `to_date(col, "MM/dd/yyyy")` |
| `LN_MAT_DT` | VARCHAR(10) | `maturity_date` | DATE | `to_date(col, "MM/dd/yyyy")` |
| `LN_1ST_PMT_DT` | VARCHAR(10) | `first_payment_date` | DATE | `to_date(col, "MM/dd/yyyy")` |
| `LN_NXT_PMT_DT` | VARCHAR(10) | `next_payment_date` | DATE | `to_date(col, "MM/dd/yyyy")` |
| `LN_STAT_CD` | VARCHAR(5) | `status` | STRING | ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| `LN_DLQ_DAYS` | VARCHAR(5) | `delinquency_days` | INT | `cast(trim(col) as INT)`, default 0 |
| `LN_ESCROW_BAL` | VARCHAR(15) | `escrow_balance` | DECIMAL(10,2) | Strip commas, cast |
| `LN_LTV_PCT` | VARCHAR(8) | `ltv_percent` | DECIMAL(5,2) | `cast(trim(col) as DECIMAL(5,2))` |
| `PROP_ADDR_LN1` | VARCHAR(100) | `property_address` | STRING | Direct copy |
| `PROP_CTY_NM` | VARCHAR(50) | `property_city` | STRING | Direct copy |
| `PROP_ST_CD` | VARCHAR(2) | `property_state` | STRING | Direct copy |
| `PROP_ZIP_CD` | VARCHAR(10) | `property_zip` | STRING | Direct copy |
| `PROP_TYP_CD` | VARCHAR(10) | `property_type` | STRING | SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| `PROP_APRS_VAL` | VARCHAR(15) | `appraised_value` | DECIMAL(12,2) | Strip commas, cast |
| `LN_CRET_DT` | VARCHAR(10) | `created_at` | TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| `LN_UPDT_DT` | VARCHAR(10) | `updated_at` | TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |

### 3.4 CDW_PMT_HIST → payments

| Legacy Column | Legacy Type | Modern Column | Modern Type | Transformation |
|---------------|-------------|---------------|-------------|----------------|
| `PMT_SEQ_NBR` | VARCHAR(20) | `legacy_payment_id` | STRING | Preserved for audit trail |
| `LN_ACCT_NBR` | VARCHAR(20) | `loan_account_id` | BIGINT | FK lookup: `loan_accounts.loan_account_id WHERE account_number = LN_ACCT_NBR` |
| `PMT_DT` | VARCHAR(10) | `payment_date` | DATE | `to_date(col, "MM/dd/yyyy")` |
| `PMT_AMT` | VARCHAR(15) | `total_amount` | DECIMAL(10,2) | Strip commas, cast |
| `PMT_PRIN_AMT` | VARCHAR(15) | `principal_amount` | DECIMAL(10,2) | Strip commas, cast |
| `PMT_INT_AMT` | VARCHAR(15) | `interest_amount` | DECIMAL(10,2) | Strip commas, cast |
| `PMT_ESCROW_AMT` | VARCHAR(15) | `escrow_amount` | DECIMAL(10,2) | Strip commas, cast; default 0.00 |
| `PMT_LATE_FEE` | VARCHAR(15) | `late_fee` | DECIMAL(10,2) | Strip commas, cast; default 0.00 |
| `PMT_TYP_CD` | VARCHAR(5) | `type` | STRING | REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| `PMT_STAT_CD` | VARCHAR(5) | `status` | STRING | PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| `PMT_RECV_DT` | VARCHAR(10) | `received_date` | DATE | `to_date(col, "MM/dd/yyyy")` |
| `PMT_PROC_DT` | VARCHAR(10) | `processed_date` | DATE | `to_date(col, "MM/dd/yyyy")` |
| `PMT_CRET_DT` | VARCHAR(10) | `created_at` | TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| `PMT_UPDT_DT` | VARCHAR(10) | `updated_at` | TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |

---

## 4. Transformation Decisions

### 4.1 Type Conversions

| Pattern | Legacy | Modern | PySpark Function |
|---------|--------|--------|-----------------|
| Dates | VARCHAR `"03/15/1978"` | DATE | `F.to_date(col, "MM/dd/yyyy")` |
| Timestamps | VARCHAR `"01/15/2019"` | TIMESTAMP | `F.to_timestamp(col, "MM/dd/yyyy")` |
| Amounts | VARCHAR `"285,000"` or `"1,487.02"` | DECIMAL | `regexp_replace(col, ",", "").cast(DecimalType)` |
| Integers | VARCHAR `"360"` | INT | `trim(col).cast(IntegerType())` |
| Booleans | VARCHAR `"ACT"` / `"INA"` | BOOLEAN | `when(col == "ACT", True).otherwise(False)` |

**Decision rationale:** All legacy columns are VARCHAR, so the migration must parse every non-string field. The `transforms.py` module centralizes these conversions to ensure consistency across all ingestion scripts.

### 4.2 Status Code Expansion

| Table | Legacy Code | Modern Label |
|-------|------------|--------------|
| Borrowers | ACT | ACTIVE |
| Borrowers | INA | INACTIVE |
| Loans | ACT | ACTIVE |
| Loans | CLO | CLOSED |
| Loans | DFT | DEFAULT |
| Loans | FRB | FORBEARANCE |
| Payments (type) | REG | REGULAR |
| Payments (type) | EXT | EXTRA |
| Payments (type) | PRT | PARTIAL |
| Payments (type) | PRE | PREPAYMENT |
| Payments (status) | PST | POSTED |
| Payments (status) | REV | REVERSED |
| Payments (status) | NSF | NSF |
| Payments (status) | PND | PENDING |
| Products | ACT → true | (boolean) |
| Products | INA → false | (boolean) |
| Properties | SFR | Single Family |
| Properties | CND | Condominium |
| Properties | MFR | Multi-Family |
| Properties | TWN | Townhouse |

**Decision:** Unknown codes are preserved as-is (not mapped to null) so they are visible in the target for investigation.

### 4.3 Denormalization Removal

`CDW_LN_ACCT` contains redundant borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`). These are **dropped** during migration:
- Borrower data is sourced exclusively from `CDW_BORR_MSTR` (the master record)
- `BORR_SSN_LST4` is known to contain corrupted data (matches phone last-4 digits — see ANM-001 in `docs/DATA_ANOMALY_REPORT.md`)
- The modern schema uses a `borrower_id` FK for join-based access

### 4.4 FK Resolution Strategy

| Child Table | Legacy Reference | Lookup Table | Join Key |
|-------------|-----------------|--------------|----------|
| loan_accounts | `BORR_ID` (string) | borrowers | `borrowers.external_id = CDW_LN_ACCT.BORR_ID` → `borrowers.borrower_id` |
| loan_accounts | `PROD_CD` (string) | loan_products | `loan_products.code = CDW_LN_ACCT.PROD_CD` → `loan_products.product_id` |
| payments | `LN_ACCT_NBR` (string) | loan_accounts | `loan_accounts.account_number = CDW_PMT_HIST.LN_ACCT_NBR` → `loan_accounts.loan_account_id` |

Records with unresolvable FKs (null after join) are quarantined, not silently dropped.

### 4.5 Partitioning Strategy

| Table | Partition Column | Rationale |
|-------|-----------------|-----------|
| `loan_accounts` | `status` | Most loan queries filter by status (active vs closed). Low cardinality (4 values) makes for efficient partitions. |
| `payments` | `status` | Payment queries typically filter by posted vs pending. Low cardinality (4 values). |
| `borrowers` | *(none)* | Small dimension table; partitioning adds overhead with no benefit. |
| `loan_products` | *(none)* | Reference table with < 100 rows; partitioning not needed. |

**Alternative considered:** Partitioning loan_accounts by `origination_year` was evaluated but rejected because (a) the current dataset is small and (b) status-based queries are more common in mortgage servicing than date-range queries. For larger datasets, consider Z-ORDER on `origination_date` within the status partition.

---

## 5. Error Handling Strategy

### 5.1 Quarantine Pattern

Records that fail validation are written to quarantine Delta tables at `/mnt/migration/quarantine/<table>` instead of being dropped. This ensures:
- No silent data loss
- Quarantined records can be inspected and re-processed after fixing upstream data
- Row count reconciliation accounts for quarantined records

### 5.2 Null Handling

| Scenario | Behavior |
|----------|----------|
| Null in required field | Record quarantined |
| Null in optional field | Preserved as null in target |
| Unparseable amount (e.g., "$285,000") | Cast returns null → triggers quarantine if required field |
| Unparseable date (e.g., "1978-03-15") | `to_date` returns null → preserved if optional, quarantined if required |
| Unknown status code | Preserved as-is (not null) |

### 5.3 Logging

All ingestion scripts print:
- Source record count
- Target record count
- Quarantine count
- Reconciliation summary

In Databricks, these appear in the notebook output and can be captured by Workflows for alerting.

---

## 6. Pre-Migration Checklist

- [ ] Create the `loan_warehouse` database in Databricks: `CREATE DATABASE IF NOT EXISTS loan_warehouse`
- [ ] Upload legacy data exports to `/mnt/legacy-data/` (CSV or Parquet format)
- [ ] Verify file headers match legacy column names (`BORR_ID`, `PROD_CD`, etc.)
- [ ] Upload `databricks/ingestion/transforms.py` to a shared location accessible by all notebooks
- [ ] Run DDL scripts (steps 1–4) to create empty target tables
- [ ] Run ingestion scripts in dependency order (steps 5–8)
- [ ] Run quality checks (step 9) and review the generated report
- [ ] Investigate and resolve any quarantined records
- [ ] Re-run quality checks to confirm all checks pass

---

## 7. Post-Migration Validation

After ingestion completes, run `databricks/quality/data_quality_checks.py` which validates:

1. **Row count reconciliation** — source count matches target + quarantine
2. **Null checks** — 28 required fields across 4 tables have no nulls
3. **FK integrity** — all borrower_id, product_id, and loan_account_id references resolve
4. **Business rules** — active loans have positive balances, credit scores in range, payment components reconcile, origination precedes maturity

### Known Expected Failures

Two quality checks will fail due to legacy data quality issues (not ingestion bugs):
- **ANM-002:** Mitchell's payments have a $400 component/total discrepancy
- **ANM-005:** Torres's loan has 15 delinquency days with ACTIVE status

See `docs/DATA_ANOMALY_REPORT.md` for full details and recommended upstream fixes.
