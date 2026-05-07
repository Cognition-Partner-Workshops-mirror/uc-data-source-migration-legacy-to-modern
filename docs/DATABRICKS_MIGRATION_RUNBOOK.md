# Databricks Migration Runbook

## CDW Legacy-to-Modern Loan Data Migration

This runbook documents the complete migration of loan management data from the legacy CDW (Corporate Data Warehouse) schema to a modern Delta Lake schema on Databricks. It covers every transformation decision, the column mapping rationale, type conversions, partitioning strategy, and the recommended execution order.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Source System Analysis](#2-source-system-analysis)
3. [Target Schema Design](#3-target-schema-design)
4. [Column Mapping Reference](#4-column-mapping-reference)
5. [Type Conversion Decisions](#5-type-conversion-decisions)
6. [Status Code Expansion](#6-status-code-expansion)
7. [Partitioning Strategy](#7-partitioning-strategy)
8. [Execution Order](#8-execution-order)
9. [Ingestion Script Reference](#9-ingestion-script-reference)
10. [Data Quality Checks](#10-data-quality-checks)
11. [Error Handling & Quarantine](#11-error-handling--quarantine)
12. [Rollback Procedure](#12-rollback-procedure)
13. [Post-Migration Validation](#13-post-migration-validation)

---

## 1. Architecture Overview

```
┌──────────────────┐     CSV/Parquet     ┌──────────────────────┐
│  Legacy CDW      │ ──── export ──────► │  DBFS / Cloud Store  │
│  (H2 / RDBMS)   │                     │  Landing Zone        │
└──────────────────┘                     └──────────┬───────────┘
                                                    │
                                         PySpark Ingestion
                                                    │
                                                    ▼
                                         ┌──────────────────────┐
                                         │  Delta Lake Tables   │
                                         │  (Unity Catalog)     │
                                         │                      │
                                         │  loan_warehouse.*    │
                                         └──────────┬───────────┘
                                                    │
                                          Data Quality Checks
                                                    │
                                                    ▼
                                         ┌──────────────────────┐
                                         │  Quality Report      │
                                         │  (Markdown / Table)  │
                                         └──────────────────────┘
```

**Pipeline Components:**

| Component | Location | Purpose |
|-----------|----------|---------|
| DDL Scripts | `databricks/ddl/` | Delta Lake table definitions with constraints |
| Ingestion Scripts | `databricks/ingestion/` | PySpark ETL for each legacy table |
| Quality Framework | `databricks/quality/` | Post-ingestion validation and reporting |
| Common Utilities | `databricks/ingestion/common_utils.py` | Shared UDFs, parsers, and helpers |

---

## 2. Source System Analysis

### Legacy CDW Tables

The legacy system stores all data in four tables with the following anti-patterns:

| Table | Rows | Key Issues |
|-------|------|------------|
| `CDW_BORR_MSTR` | 5 borrowers | All VARCHAR columns, dates as `MM/DD/YYYY` strings, amounts with commas |
| `CDW_LN_PROD` | 5 products | Status codes as abbreviations (`ACT`, `INA`) |
| `CDW_LN_ACCT` | 5 accounts | Denormalized — embeds borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`), no FK constraints |
| `CDW_PMT_HIST` | 10 payments | All amounts as comma-formatted strings, no referential integrity |

### Key Problems Addressed

1. **Loose Typing**: Every column is `VARCHAR` — dates, amounts, integers, booleans all stored as strings
2. **Cryptic Names**: `BORR_FST_NM`, `LN_CURR_BAL`, `PMT_ESCROW_AMT` — difficult to understand without documentation
3. **Denormalization**: Borrower data duplicated inside `CDW_LN_ACCT`
4. **No Referential Integrity**: No foreign keys between tables
5. **Abbreviated Codes**: `ACT`, `CLO`, `DFT`, `FRB` instead of readable status values

---

## 3. Target Schema Design

### Unity Catalog Structure

```
loan_catalog
  └── loan_warehouse (schema)
       ├── borrowers            (dimension)
       ├── loan_products        (dimension/reference)
       ├── loan_accounts        (fact)
       └── payments             (fact)
```

### Design Principles

- **Proper data types**: `DATE`, `DECIMAL(p,s)`, `INT`, `BOOLEAN`, `TIMESTAMP` — no more VARCHAR-for-everything
- **Meaningful names**: `first_name` not `BORR_FST_NM`, `current_balance` not `LN_CURR_BAL`
- **Normalized structure**: Borrower data lives only in `borrowers` table; `loan_accounts` references it via FK
- **Delta Lake constraints**: `NOT NULL`, `CHECK`, and `UNIQUE` constraints enforced at the table level
- **Audit columns**: `_ingestion_ts` and `_source_system` on every table for lineage tracking
- **Generated columns**: `origination_year` on loans, `payment_year`/`payment_month` on payments for efficient partitioning

---

## 4. Column Mapping Reference

### CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `BORR_ID` | `external_id` | VARCHAR → STRING | Direct copy (trimmed) |
| `BORR_FST_NM` | `first_name` | VARCHAR → STRING | Direct copy (trimmed) |
| `BORR_LST_NM` | `last_name` | VARCHAR → STRING | Direct copy (trimmed) |
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
| `BORR_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` to midnight timestamp |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` to midnight timestamp |
| `BORR_STAT_CD` | `status` | VARCHAR → STRING | Expand: `ACT`→`ACTIVE`, `INA`→`INACTIVE` |
| `BORR_REC_TYP` | *(dropped)* | — | Not needed in modern schema |

### CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PROD_CD` | `code` | VARCHAR → STRING | Direct copy |
| `PROD_DESC_TXT` | `name` | VARCHAR → STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR → STRING | Direct copy (`FXD`, `ARM`, `FHA`, `VA`) |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | Parse string to integer |
| `PROD_RT_TYP` | `rate_type` | VARCHAR → STRING | Direct copy (`FIXED`, `VARIABLE`) |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `PROD_STAT_CD` | `is_active` | VARCHAR → BOOLEAN | `ACT`→`true`, `INA`→`false` |
| `PROD_EFF_DT` | `effective_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |

### CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `LN_ACCT_NBR` | `account_number` | VARCHAR → STRING | Direct copy |
| `BORR_ID` | `borrower_id` | VARCHAR → BIGINT | FK lookup via `borrowers.external_id` |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_id` | VARCHAR → BIGINT | FK lookup via `loan_products.code` |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | Parse string |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | Parse string |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `LN_ORIG_DT` | `origination_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_MAT_DT` | `maturity_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `LN_STAT_CD` | `status` | VARCHAR → STRING | Expand (see Section 6) |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | Parse string |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | Parse string |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR → STRING | Expand (see Section 6) |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Remove commas, parse |
| `LN_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `LN_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |

### CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PMT_SEQ_NBR` | `legacy_payment_id` | VARCHAR → STRING | Preserved for traceability |
| `LN_ACCT_NBR` | `loan_account_id` | VARCHAR → BIGINT | FK lookup via `loan_accounts.account_number` |
| `PMT_DT` | `payment_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_AMT` | `total_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR → DECIMAL(10,2) | Remove commas, parse |
| `PMT_TYP_CD` | `type` | VARCHAR → STRING | Expand (see Section 6) |
| `PMT_STAT_CD` | `status` | VARCHAR → STRING | Expand (see Section 6) |
| `PMT_RECV_DT` | `received_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_PROC_DT` | `processed_date` | VARCHAR → DATE | Parse `MM/DD/YYYY` |
| `PMT_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | Parse `MM/DD/YYYY` |

---

## 5. Type Conversion Decisions

### Date Parsing

| Pattern | Source Example | Target Type | Rationale |
|---------|--------------|-------------|-----------|
| `MM/DD/YYYY` → `DATE` | `03/15/1978` | `DateType` | Used for business dates (DOB, origination, payment) |
| `MM/DD/YYYY` → `TIMESTAMP` | `01/15/2019` | `TimestampType` | Used for audit fields (`created_at`, `updated_at`); stored as midnight UTC |

**Decision**: Audit timestamps are stored as `TIMESTAMP` rather than `DATE` to allow future migration to actual timestamped audit trails. The legacy system only had date precision, so all timestamps default to midnight.

### Amount Parsing

| Source Format | Target Type | Rationale |
|---------------|-------------|-----------|
| `"285,000"` | `DECIMAL(12,2)` | Large financial amounts (loan amounts, income, appraised values) |
| `"1,487.02"` | `DECIMAL(10,2)` | Payment amounts, escrow balances |
| `"5.250"` | `DECIMAL(5,3)` | Interest rates (up to 99.999%) |
| `"82.5"` | `DECIMAL(5,2)` | LTV percentages (up to 999.99%) |

**Decision**: We strip commas and dollar signs before parsing. The `DECIMAL` precision was chosen to accommodate realistic financial data ranges while minimizing storage overhead.

### Integer Parsing

| Source | Target | Example |
|--------|--------|---------|
| VARCHAR credit score | `INT` | `"745"` → `745` |
| VARCHAR term months | `INT` | `"360"` → `360` |
| VARCHAR delinquency days | `INT` | `"15"` → `15` |

---

## 6. Status Code Expansion

### Loan Status (`LN_STAT_CD`)

| Legacy Code | Modern Value | Description |
|-------------|-------------|-------------|
| `ACT` | `ACTIVE` | Loan is current and active |
| `CLO` | `CLOSED` | Loan has been paid off or closed |
| `DFT` | `DEFAULT` | Loan is in default |
| `FRB` | `FORBEARANCE` | Loan is in forbearance |

### Borrower Status (`BORR_STAT_CD`)

| Legacy Code | Modern Value |
|-------------|-------------|
| `ACT` | `ACTIVE` |
| `INA` | `INACTIVE` |

### Product Status (`PROD_STAT_CD`)

| Legacy Code | Modern Value | Type |
|-------------|-------------|------|
| `ACT` | `true` | BOOLEAN |
| `INA` | `false` | BOOLEAN |

### Payment Type (`PMT_TYP_CD`)

| Legacy Code | Modern Value |
|-------------|-------------|
| `REG` | `REGULAR` |
| `EXT` | `EXTRA` |
| `PRT` | `PARTIAL` |
| `PRE` | `PREPAYMENT` |

### Payment Status (`PMT_STAT_CD`)

| Legacy Code | Modern Value |
|-------------|-------------|
| `PST` | `POSTED` |
| `REV` | `REVERSED` |
| `NSF` | `NSF` |
| `PND` | `PENDING` |

### Property Type (`PROP_TYP_CD`)

| Legacy Code | Modern Value |
|-------------|-------------|
| `SFR` | `Single Family` |
| `CND` | `Condominium` |
| `MFR` | `Multi-Family` |
| `TWN` | `Townhouse` |

---

## 7. Partitioning Strategy

| Table | Partition Column(s) | Rationale |
|-------|-------------------|-----------|
| `borrowers` | `state` | Geographic queries are common in lending analytics; 50 US states provides good partition granularity |
| `loan_products` | *(none)* | Reference table with very low cardinality (~5-20 rows); partitioning would add overhead |
| `loan_accounts` | `status` | Portfolio analytics frequently filters by loan status (active vs. closed); 4 status values provide balanced partitions |
| `payments` | `payment_year`, `payment_month` | Time-series queries dominate payment analytics; year/month partitioning enables efficient range scans and data lifecycle management |

**Additional optimizations:**
- All tables use `delta.autoOptimize.optimizeWrite = true` for automatic file sizing
- All tables use `delta.autoOptimize.autoCompact = true` for automatic small file compaction
- `loan_accounts` includes a generated column `origination_year` for ad-hoc time-based queries without repartitioning
- `payments` includes generated columns `payment_year` and `payment_month` used as partition keys

---

## 8. Execution Order

The pipeline must be executed in dependency order due to FK relationships:

```
Step 0: Create catalog and schema       (00_create_schema.sql)
Step 1: Create all Delta Lake tables     (01-04 DDL scripts)
Step 2: Ingest borrowers                 (no dependencies)
Step 3: Ingest loan_products             (no dependencies)
    ── Steps 2 & 3 can run in parallel ──
Step 4: Ingest loan_accounts             (depends on borrowers + loan_products)
Step 5: Ingest payments                  (depends on loan_accounts)
Step 6: Run data quality checks          (depends on all tables)
Step 7: Review quality report            (manual review)
```

### Databricks Workflow Configuration

```
Job: CDW_Legacy_Migration
├── Task 1: create_schema          (SQL task → 00_create_schema.sql)
├── Task 2: create_tables          (SQL task → 01-04 DDL scripts, depends on Task 1)
├── Task 3: ingest_borrowers       (Python task, depends on Task 2)
├── Task 4: ingest_loan_products   (Python task, depends on Task 2)
├── Task 5: ingest_loan_accounts   (Python task, depends on Tasks 3 & 4)
├── Task 6: ingest_payments        (Python task, depends on Task 5)
└── Task 7: quality_checks         (Python task, depends on Task 6)
```

### Quick Start (Single Notebook)

For development or small datasets, use the orchestrator script:

```bash
spark-submit databricks/ingestion/run_full_pipeline.py \
    --base-path dbfs:/mnt/legacy \
    --format csv
```

---

## 9. Ingestion Script Reference

| Script | Source Table | Target Table | Key Transformations |
|--------|-------------|-------------|---------------------|
| `ingest_borrowers.py` | `CDW_BORR_MSTR` | `borrowers` | Date parsing, income parsing, status expansion, drops `BORR_REC_TYP` |
| `ingest_loan_products.py` | `CDW_LN_PROD` | `loan_products` | Amount parsing, term parsing, status→boolean conversion |
| `ingest_loan_accounts.py` | `CDW_LN_ACCT` | `loan_accounts` | Drops denormalized borrower fields, resolves borrower/product FKs, expands status + property type codes |
| `ingest_payments.py` | `CDW_PMT_HIST` | `payments` | Resolves loan account FK, expands type/status codes, preserves legacy ID |
| `run_full_pipeline.py` | *(all)* | *(all)* | Orchestrates all 4 scripts in dependency order |

### Shared Utilities (`common_utils.py`)

- `parse_date_string()` — MM/DD/YYYY → Python date
- `parse_timestamp_string()` — MM/DD/YYYY → Python datetime (midnight)
- `parse_amount_string()` — Comma-formatted string → Decimal
- `parse_int_string()` — String → int
- `expand_code()` — Abbreviation → expanded value via mapping dict
- `map_status_column()` — DataFrame-level status code expansion
- `quarantine_malformed()` — Splits rows into valid + quarantine sets
- `read_legacy_csv()` / `read_legacy_parquet()` — Source readers with logging
- `write_delta()` — Delta Lake writer with partition support

---

## 10. Data Quality Checks

The quality framework (`databricks/quality/data_quality_checks.py`) runs 25+ checks across four categories:

### Row Count Reconciliation
- Source row count matches target row count for each table
- Quarantine tables have zero rows (all data migrated cleanly)

### Null Checks
- Required fields are never NULL in target tables
- Checked fields per table match the `NOT NULL` constraints in DDL

### Referential Integrity
- `loan_accounts.borrower_id` → `borrowers.borrower_key` (no orphans)
- `loan_accounts.product_id` → `loan_products.product_key` (no orphans)
- `payments.loan_account_id` → `loan_accounts.loan_key` (no orphans)

### Business Rules
| Check | Table | Rule |
|-------|-------|------|
| Credit score range | borrowers | 300 ≤ score ≤ 850 (when present) |
| Borrower status | borrowers | Must be ACTIVE or INACTIVE |
| Annual income positive | borrowers | > 0 when present |
| Active loan balance | loan_accounts | Balance > 0 for ACTIVE loans |
| Date ordering | loan_accounts | maturity_date > origination_date |
| Interest rate | loan_accounts | Rate > 0 |
| LTV range | loan_accounts | 0 ≤ LTV ≤ 200 (when present) |
| Loan status | loan_accounts | Must be in expanded set |
| Property type | loan_accounts | Must be in expanded set (when present) |
| Payment amount | payments | > 0 |
| Payment type | payments | Must be in expanded set |
| Payment status | payments | Must be in expanded set |
| Component sum | payments | principal + interest + escrow + late_fee ≈ total (±$0.01) |
| Processing order | payments | processed_date ≥ received_date |
| Product amount range | loan_products | min_amount ≤ max_amount |
| Product date range | loan_products | expiration_date > effective_date |

---

## 11. Error Handling & Quarantine

The pipeline never silently drops records. Instead:

1. **Malformed values** (unparseable dates, amounts, etc.) are set to `NULL` by the UDFs with a warning log message
2. **Rows with NULL required fields** after transformation are moved to quarantine tables:
   - `_quarantine_borrowers`
   - `_quarantine_loan_products`
   - `_quarantine_loan_accounts`
   - `_quarantine_payments`
3. **Unresolved FK lookups** (borrower ID or product code not found in parent table) result in `NULL` FK values, which are then caught by the quarantine step
4. **Row count reconciliation** verifies: `source_count == target_count + quarantine_count`

### Investigating Quarantined Records

```sql
-- View quarantined loan accounts
SELECT * FROM loan_warehouse._quarantine_loan_accounts;

-- Find which required fields were NULL
SELECT account_number, borrower_id, product_id, original_amount
FROM loan_warehouse._quarantine_loan_accounts
WHERE borrower_id IS NULL OR product_id IS NULL;
```

---

## 12. Rollback Procedure

Delta Lake supports time travel, enabling safe rollback:

```sql
-- View table history
DESCRIBE HISTORY loan_warehouse.borrowers;

-- Rollback to previous version
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF 0;

-- Or rollback to timestamp
RESTORE TABLE loan_warehouse.loan_accounts TO TIMESTAMP AS OF '2025-01-01T00:00:00';
```

To fully reset and re-run:

```sql
-- Drop and recreate (destructive)
DROP TABLE IF EXISTS loan_warehouse.borrowers;
DROP TABLE IF EXISTS loan_warehouse.loan_products;
DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
DROP TABLE IF EXISTS loan_warehouse.payments;

-- Re-run DDL scripts, then re-run ingestion pipeline
```

---

## 13. Post-Migration Validation

After the pipeline and quality checks complete:

1. **Review the quality report** (`DATA_QUALITY_REPORT.md`) — all checks should PASS
2. **Spot-check sample records** against the legacy source:

```sql
-- Compare a borrower
SELECT * FROM loan_warehouse.borrowers WHERE external_id = 'B-10001';
-- Legacy: BORR_FST_NM='James', BORR_ANN_INCM='92,500', BORR_DOB_DT='03/15/1978'
-- Modern: first_name='James', annual_income=92500.00, date_of_birth=1978-03-15

-- Compare a loan account
SELECT * FROM loan_warehouse.loan_accounts WHERE account_number = 'LN-2019-00142';
-- Legacy: LN_CURR_BAL='271,432.56', LN_STAT_CD='ACT', PROP_TYP_CD='SFR'
-- Modern: current_balance=271432.56, status='ACTIVE', property_type='Single Family'

-- Compare a payment
SELECT p.*, la.account_number
FROM loan_warehouse.payments p
JOIN loan_warehouse.loan_accounts la ON p.loan_account_id = la.loan_key
WHERE la.account_number = 'LN-2019-00142'
ORDER BY p.payment_date DESC;
```

3. **Verify FK resolution** — no orphaned records:

```sql
SELECT COUNT(*) AS orphaned_loans
FROM loan_warehouse.loan_accounts la
LEFT JOIN loan_warehouse.borrowers b ON la.borrower_id = b.borrower_key
WHERE b.borrower_key IS NULL;
-- Expected: 0
```

4. **Sign off** and archive the quality report for audit purposes.

---

*Document version: 1.0.0*
*Last updated: 2025-12-01*
*Author: CDW Migration Team*
