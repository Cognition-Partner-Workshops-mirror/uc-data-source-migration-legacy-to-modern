# Databricks Migration Runbook

## CDW Legacy Data Warehouse to Modern Delta Lake

### Overview

This runbook documents the complete migration of the legacy CDW (Corporate Data Warehouse) loan management system to a modern Delta Lake architecture on Databricks. The legacy system stores all data as VARCHAR columns with cryptic abbreviated names, no enforced relationships, and inconsistent data formats.

---

## 1. Source System Analysis

### Legacy Tables

| Table | Purpose | Row Estimate | Key Issues |
|-------|---------|-------------|------------|
| `CDW_BORR_MSTR` | Borrower master data | Dimension | All VARCHAR, dates as strings |
| `CDW_LN_PROD` | Loan product catalog | Small dimension | Amounts stored with commas |
| `CDW_LN_ACCT` | Loan accounts | Fact table | Denormalized borrower data embedded |
| `CDW_PMT_HIST` | Payment history | Large fact | No FK constraints |

### Legacy Schema Characteristics

- **All columns are VARCHAR** — no type safety
- **Cryptic column names** — 3-4 character abbreviations (e.g., `BORR_FST_NM`, `LN_CURR_BAL`)
- **Dates stored as strings** — format `MM/DD/YYYY`
- **Amounts stored as strings** — with embedded commas (e.g., `"285,000"`, `"271,432.56"`)
- **Status codes are abbreviations** — `ACT`, `CLO`, `DFT`, `FRB`
- **No foreign key constraints** — relationships implied but not enforced
- **Denormalized design** — borrower data duplicated in loan accounts table

---

## 2. Target Schema Design

### Modern Delta Lake Tables

| Target Table | Source | Partitioning | Rationale |
|-------------|--------|--------------|-----------|
| `loan_warehouse.borrowers` | `CDW_BORR_MSTR` | `state` | Geographic query patterns for compliance reporting |
| `loan_warehouse.loan_products` | `CDW_LN_PROD` | None | Small reference table (~10 rows) |
| `loan_warehouse.loan_accounts` | `CDW_LN_ACCT` | `origination_year` | Time-series analytics, data lifecycle management |
| `loan_warehouse.payments` | `CDW_PMT_HIST` | `payment_year`, `payment_month` | High-volume time-range queries |

### Partitioning Strategy

1. **`borrowers` → Partitioned by `state`**
   - Regulatory compliance queries often filter by state jurisdiction
   - Moderate cardinality (50 states) avoids small-file problem
   - Enables efficient geographic analytics

2. **`loan_products` → No partitioning**
   - Very small table (< 100 rows typically)
   - Partitioning would create unnecessary overhead

3. **`loan_accounts` → Partitioned by `origination_year`**
   - Natural time-series dimension for loan lifecycle reporting
   - Enables efficient retention policies (archive loans > 10 years)
   - Generated column automatically derived from `origination_date`

4. **`payments` → Partitioned by `payment_year`, `payment_month`**
   - Highest volume table; monthly reporting is primary access pattern
   - Two-level partitioning balances query performance with file sizes
   - Supports efficient monthly statement generation and reconciliation

---

## 3. Column Mapping Reference

### CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `BORR_ID` | `external_id` | VARCHAR → STRING | Direct copy |
| `BORR_FST_NM` | `first_name` | VARCHAR → STRING | Direct copy |
| `BORR_LST_NM` | `last_name` | VARCHAR → STRING | Direct copy |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR → STRING | Direct copy |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR → STRING | Direct copy |
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
| `BORR_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `BORR_STAT_CD` | `status` | VARCHAR → STRING | `ACT`→`ACTIVE`, `INA`→`INACTIVE` |
| `BORR_REC_TYP` | *(dropped)* | — | Not needed in modern schema |

### CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PROD_CD` | `code` | VARCHAR → STRING | Direct copy |
| `PROD_DESC_TXT` | `name` | VARCHAR → STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR → STRING | Direct copy |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | Parse string |
| `PROD_RT_TYP` | `rate_type` | VARCHAR → STRING | Direct copy |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `PROD_STAT_CD` | `is_active` | VARCHAR → BOOLEAN | `ACT`→`true`, `INA`→`false` |
| `PROD_EFF_DT` | `effective_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |

### CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `LN_ACCT_NBR` | `account_number` | VARCHAR → STRING | Direct copy |
| `BORR_ID` | `borrower_id` | VARCHAR → STRING | FK to borrowers.external_id |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use FK |
| `PROD_CD` | `product_code` | VARCHAR → STRING | FK to loan_products.code |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | Parse string |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | Parse string |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `LN_ORIG_DT` | `origination_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_MAT_DT` | `maturity_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_STAT_CD` | `status` | VARCHAR → STRING | `ACT`→`ACTIVE`, `CLO`→`CLOSED`, `DFT`→`DEFAULT`, `FRB`→`FORBEARANCE` |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | Parse string |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | Parse string |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR → STRING | `SFR`→`Single Family`, `CND`→`Condominium`, `MFR`→`Multi-Family`, `TWN`→`Townhouse` |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `LN_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |

### CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PMT_SEQ_NBR` | `legacy_payment_id` | VARCHAR → STRING | Preserved for traceability |
| `LN_ACCT_NBR` | `loan_account_number` | VARCHAR → STRING | FK to loan_accounts.account_number |
| `PMT_DT` | `payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_AMT` | `total_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_TYP_CD` | `type` | VARCHAR → STRING | `REG`→`REGULAR`, `EXT`→`EXTRA`, `PRT`→`PARTIAL`, `PRE`→`PREPAYMENT` |
| `PMT_STAT_CD` | `status` | VARCHAR → STRING | `PST`→`POSTED`, `REV`→`REVERSED`, `NSF`→`NSF`, `PND`→`PENDING` |
| `PMT_RECV_DT` | `received_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_PROC_DT` | `processed_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |

---

## 4. Type Conversion Decisions

### Date/Timestamp Handling

| Scenario | Source Format | Target Type | Rationale |
|----------|-------------|-------------|-----------|
| Birth date, origination date, payment date | `MM/DD/YYYY` | `DATE` | Pure date without time component |
| Created/updated timestamps | `MM/DD/YYYY` | `TIMESTAMP` | Audit fields benefit from full precision; midnight assumed for legacy data |

**Edge Cases:**
- Invalid date strings (e.g., `02/30/2020`) → NULL with record logged to error table
- Empty strings → treated as NULL
- Future dates in historical fields → retained but flagged in quality checks

### Amount Handling

| Pattern | Example | Target Type | Conversion |
|---------|---------|-------------|------------|
| Whole numbers with commas | `"285,000"` | DECIMAL(12,2) | Remove commas, cast |
| Decimals with commas | `"271,432.56"` | DECIMAL(12,2) | Remove commas, cast |
| Rate values | `"5.250"` | DECIMAL(5,3) | Direct cast |
| Percentage values | `"82.5"` | DECIMAL(5,2) | Direct cast |
| Zero amounts | `"0"` or `"0.00"` | DECIMAL | Direct cast |

**Precision choices:**
- `DECIMAL(12,2)` for balances/amounts — supports up to $9,999,999,999.99
- `DECIMAL(10,2)` for payments — supports up to $99,999,999.99
- `DECIMAL(5,3)` for interest rates — supports up to 99.999%
- `DECIMAL(5,2)` for LTV/percentages — supports up to 999.99%

### Status Code Expansion

| Domain | Code | Expanded Value |
|--------|------|---------------|
| Loan Status | `ACT` | `ACTIVE` |
| Loan Status | `CLO` | `CLOSED` |
| Loan Status | `DFT` | `DEFAULT` |
| Loan Status | `FRB` | `FORBEARANCE` |
| Borrower Status | `ACT` | `ACTIVE` |
| Borrower Status | `INA` | `INACTIVE` |
| Payment Type | `REG` | `REGULAR` |
| Payment Type | `EXT` | `EXTRA` |
| Payment Type | `PRT` | `PARTIAL` |
| Payment Type | `PRE` | `PREPAYMENT` |
| Payment Status | `PST` | `POSTED` |
| Payment Status | `REV` | `REVERSED` |
| Payment Status | `NSF` | `NSF` |
| Payment Status | `PND` | `PENDING` |
| Property Type | `SFR` | `Single Family` |
| Property Type | `CND` | `Condominium` |
| Property Type | `MFR` | `Multi-Family` |
| Property Type | `TWN` | `Townhouse` |
| Product Status | `ACT` | `true` (boolean) |
| Product Status | `INA` | `false` (boolean) |

---

## 5. Transformation Decisions

### Denormalization Removal

The legacy `CDW_LN_ACCT` table embeds borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) directly. In the modern schema:
- These columns are **dropped** from `loan_accounts`
- `borrower_id` references `borrowers.external_id` for proper normalization
- Eliminates data inconsistency risk from duplicate storage

### ID Strategy

- Legacy string IDs (`B-10001`, `LN-2019-00142`) are preserved as business keys (`external_id`, `account_number`)
- Modern tables use `BIGINT GENERATED ALWAYS AS IDENTITY` for surrogate keys
- Relationships use natural/business keys for simplicity during migration

### Metadata Columns

Every target table includes:
- `_ingestion_ts` — timestamp of when the record was ingested
- `_source_system` — identifies the source (`CDW_LEGACY`)

These support:
- Data lineage tracking
- Incremental load detection
- Audit requirements

### Error Handling

- Malformed records are **never silently dropped**
- Records failing validation are written to `loan_warehouse._migration_errors`
- Error table includes: source table name, timestamp, and the full original record
- Pipeline logs warnings but continues processing valid records

---

## 6. Execution Order

### Prerequisites

1. Databricks workspace with Unity Catalog configured
2. Source data exported from legacy CDW as CSV/Parquet to cloud storage
3. Mount point configured: `/mnt/legacy-cdw/exports/`
4. Cluster with Delta Lake runtime (DBR 13.0+)

### Step-by-Step Execution

```
Step 1: Create Database
─────────────────────────────────────
spark.sql("CREATE DATABASE IF NOT EXISTS loan_warehouse")

Step 2: Execute DDL Scripts (in order)
─────────────────────────────────────
databricks/ddl/01_borrowers.sql
databricks/ddl/02_loan_products.sql
databricks/ddl/03_loan_accounts.sql
databricks/ddl/04_payments.sql

Step 3: Run Ingestion Pipeline (dependency order)
─────────────────────────────────────
3a. databricks/ingestion/ingest_borrowers.py      (no deps)
3b. databricks/ingestion/ingest_loan_products.py  (no deps)
3c. databricks/ingestion/ingest_loan_accounts.py  (depends on 3a, 3b)
3d. databricks/ingestion/ingest_payments.py       (depends on 3c)

Step 4: Run Data Quality Validation
─────────────────────────────────────
databricks/quality/run_validation.py
→ Generates DATA_QUALITY_REPORT.md

Step 5: Review and Promote
─────────────────────────────────────
Review DATA_QUALITY_REPORT.md
If all checks pass → promote to production catalog
If checks fail → investigate, fix source, re-run
```

### Orchestration Script

For convenience, `databricks/ingestion/run_pipeline.py` executes all steps in sequence with proper error handling and timing.

```bash
# Run the full pipeline
spark-submit databricks/ingestion/run_pipeline.py

# Run quality validation separately
spark-submit databricks/quality/run_validation.py
```

---

## 7. Data Quality Checks

The validation framework (`databricks/quality/`) performs:

| Category | Check | Severity |
|----------|-------|----------|
| Row Count | Source count = target count + error count | Critical |
| Null Check | Required fields not null | Critical |
| Referential Integrity | loan_accounts.borrower_id → borrowers.external_id | Critical |
| Referential Integrity | loan_accounts.product_code → loan_products.code | Critical |
| Referential Integrity | payments.loan_account_number → loan_accounts.account_number | Critical |
| Business Rule | Active loans must have balance > 0 | High |
| Business Rule | Closed loans must have updated_at date | Medium |
| Business Rule | Payment components sum to total | High |
| Business Rule | Origination date before maturity date | High |
| Business Rule | Credit score in range 300-850 | Medium |
| Business Rule | LTV percent in range 0-200% | Medium |

---

## 8. Rollback Plan

Delta Lake provides time-travel for safe rollback:

```sql
-- View table history
DESCRIBE HISTORY loan_warehouse.borrowers;

-- Rollback to previous version
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF 0;

-- Or rollback to timestamp
RESTORE TABLE loan_warehouse.loan_accounts TO TIMESTAMP AS OF '2024-01-15T00:00:00';
```

### Full Rollback

```sql
DROP TABLE IF EXISTS loan_warehouse.payments;
DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
DROP TABLE IF EXISTS loan_warehouse.loan_products;
DROP TABLE IF EXISTS loan_warehouse.borrowers;
DROP TABLE IF EXISTS loan_warehouse._migration_errors;
DROP DATABASE IF EXISTS loan_warehouse;
```

---

## 9. Post-Migration Optimization

After successful migration:

```sql
-- Optimize file sizes
OPTIMIZE loan_warehouse.loan_accounts ZORDER BY (status, borrower_id);
OPTIMIZE loan_warehouse.payments ZORDER BY (loan_account_number, payment_date);

-- Analyze tables for query optimizer
ANALYZE TABLE loan_warehouse.borrowers COMPUTE STATISTICS FOR ALL COLUMNS;
ANALYZE TABLE loan_warehouse.loan_accounts COMPUTE STATISTICS FOR ALL COLUMNS;
ANALYZE TABLE loan_warehouse.payments COMPUTE STATISTICS FOR ALL COLUMNS;

-- Vacuum old files (after confirming no active readers)
VACUUM loan_warehouse.loan_accounts RETAIN 168 HOURS;
VACUUM loan_warehouse.payments RETAIN 168 HOURS;
```

---

## 10. Monitoring and Alerting

### Key Metrics to Monitor

- Ingestion row counts per run
- Error table growth rate
- Data quality check pass rate over time
- Delta Lake file sizes and partition skew
- Query performance on partitioned columns

### Recommended Databricks Jobs

| Job | Schedule | Purpose |
|-----|----------|---------|
| Incremental Ingestion | Daily | Load new/changed records |
| Data Quality Validation | After each ingestion | Verify data integrity |
| OPTIMIZE | Weekly | Compact small files |
| VACUUM | Weekly | Remove old file versions |
