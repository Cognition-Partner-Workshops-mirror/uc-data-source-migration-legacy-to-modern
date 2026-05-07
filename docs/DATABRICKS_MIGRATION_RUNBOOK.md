# Databricks Migration Runbook

## CDW Legacy → Modern Delta Lake

This runbook documents every transformation decision, column mapping, type conversion,
partitioning rationale, and the recommended execution order for migrating the legacy
CDW (Corporate Data Warehouse) loan management tables to a modern Delta Lake schema
on Databricks.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Source System Profile](#2-source-system-profile)
3. [Target Schema Design](#3-target-schema-design)
4. [Column Mapping Reference](#4-column-mapping-reference)
5. [Transformation Decisions](#5-transformation-decisions)
6. [Partitioning Rationale](#6-partitioning-rationale)
7. [Execution Order](#7-execution-order)
8. [Data Quality Checks](#8-data-quality-checks)
9. [Rollback Procedure](#9-rollback-procedure)
10. [Known Data Quality Issues](#10-known-data-quality-issues)

---

## 1. Overview

| Attribute | Value |
|-----------|-------|
| **Source** | CDW legacy data warehouse (4 tables) |
| **Target** | Databricks Delta Lake (`loan_warehouse` schema) |
| **Tables** | `CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Target tables** | `borrowers`, `loan_products`, `loan_accounts`, `payments`, `migration_audit_log` |
| **Key challenge** | All source columns are VARCHAR — every value requires parsing |
| **Pipeline scripts** | `databricks/ingestion/` (PySpark) |
| **DDL scripts** | `databricks/ddl/` (Spark SQL) |
| **Quality checks** | `databricks/quality/checks.py` |

---

## 2. Source System Profile

### CDW_BORR_MSTR (Borrower Master)
- **Row count (seed):** 5
- **Primary key:** `BORR_ID` (VARCHAR)
- **Characteristics:** All fields VARCHAR including dates (`MM/DD/YYYY` strings),
  monetary amounts (strings with commas like `"92,500"`), and credit scores (string integers).
- **Known issues:** `BORR_MID_INIT` can be NULL; `BORR_REC_TYP` is dropped in modern schema.

### CDW_LN_PROD (Loan Products)
- **Row count (seed):** 5
- **Primary key:** `PROD_CD` (VARCHAR)
- **Characteristics:** Product min/max amounts stored as comma-formatted strings.
  Term months stored as string. Status is `ACT`/`INA` abbreviation.

### CDW_LN_ACCT (Loan Accounts)
- **Row count (seed):** 5
- **Primary key:** `LN_ACCT_NBR` (VARCHAR)
- **Characteristics:** **Denormalized** — contains borrower fields (`BORR_FST_NM`,
  `BORR_LST_NM`, `BORR_SSN_LST4`) that duplicate `CDW_BORR_MSTR`. No foreign key
  constraints enforced. Status codes: `ACT`, `CLO`, `DFT`, `FRB`.
- **Known issues:** `LN-2018-00089` has 15 delinquency days but `ACT` status.
  SSN last-4 values appear derived from phone numbers, not SSNs.

### CDW_PMT_HIST (Payment History)
- **Row count (seed):** 10
- **Primary key:** `PMT_SEQ_NBR` (VARCHAR)
- **Characteristics:** All amounts are comma-formatted strings. Payment dates stored
  as `MM/DD/YYYY` strings causing lexicographic sort issues.
- **Known issues:** `PMT-2025120001` has component sum exceeding total by $400.
  `PMT-2025110003` has $47.50 late fee not included in stated total.

---

## 3. Target Schema Design

### loan_warehouse.borrowers
Normalized borrower dimension table. Uses `BIGINT` auto-increment primary key
with the legacy `BORR_ID` preserved in `_legacy_borr_id` for lineage.

### loan_warehouse.loan_products
Product reference table. `PROD_STAT_CD` converted from abbreviation to boolean
`is_active` field (ACT → true, INA → false).

### loan_warehouse.loan_accounts
Fact table for loan accounts. **Denormalized borrower fields are dropped** —
replaced with `borrower_id` FK. Product reference via `product_id` FK.
Partitioned by `status` for efficient filtering of active vs. closed loans.

### loan_warehouse.payments
Payment history fact table. FK to `loan_accounts`. Partitioned by `payment_year`
(extracted from `payment_date`) for efficient time-range queries.

### loan_warehouse.migration_audit_log
Tracks every ingestion run with row counts, timing, and pass/fail status
for post-migration reconciliation.

---

## 4. Column Mapping Reference

### CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `BORR_ID` | `external_id` | VARCHAR → STRING | Direct copy, trimmed |
| `BORR_FST_NM` | `first_name` | VARCHAR → STRING | Direct copy, trimmed |
| `BORR_LST_NM` | `last_name` | VARCHAR → STRING | Direct copy, trimmed |
| `BORR_MID_INIT` | `middle_initial` | VARCHAR → STRING | Direct copy |
| `BORR_SSN_ENCR` | `ssn_hash` | VARCHAR → STRING | Direct copy (re-encrypt recommended) |
| `BORR_DOB_DT` | `date_of_birth` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `BORR_ADDR_LN1` | `address_line1` | VARCHAR → STRING | Direct copy |
| `BORR_ADDR_LN2` | `address_line2` | VARCHAR → STRING | Direct copy (nullable) |
| `BORR_CTY_NM` | `city` | VARCHAR → STRING | Direct copy |
| `BORR_ST_CD` | `state` | VARCHAR → STRING | Direct copy |
| `BORR_ZIP_CD` | `zip_code` | VARCHAR → STRING | Direct copy |
| `BORR_PH_NBR` | `phone` | VARCHAR → STRING | Direct copy |
| `BORR_EMAIL_ADDR` | `email` | VARCHAR → STRING | Direct copy |
| `BORR_CRDT_SCR` | `credit_score` | VARCHAR → INT | `cast(trim(col) as INT)` |
| `BORR_EMP_STAT` | `employment_status` | VARCHAR → STRING | Direct copy |
| `BORR_ANN_INCM` | `annual_income` | VARCHAR → DECIMAL(12,2) | Remove commas, cast |
| `BORR_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| `BORR_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| `BORR_STAT_CD` | `status` | VARCHAR → STRING | ACT→ACTIVE, INA→INACTIVE |
| `BORR_REC_TYP` | *(dropped)* | — | Not needed in modern schema |

### CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PROD_CD` | `code` | VARCHAR → STRING | Direct copy |
| `PROD_DESC_TXT` | `name` | VARCHAR → STRING | Direct copy |
| `PROD_TYP_CD` | `type` | VARCHAR → STRING | Direct copy |
| `PROD_TERM_MOS` | `term_months` | VARCHAR → INT | Cast after comma removal |
| `PROD_RT_TYP` | `rate_type` | VARCHAR → STRING | Direct copy |
| `PROD_MIN_AMT` | `min_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, cast |
| `PROD_MAX_AMT` | `max_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, cast |
| `PROD_STAT_CD` | `is_active` | VARCHAR → BOOLEAN | ACT→true, else→false |
| `PROD_EFF_DT` | `effective_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `PROD_EXP_DT` | `expiration_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |

### CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `LN_ACCT_NBR` | `account_number` | VARCHAR → STRING | Direct copy |
| `BORR_ID` | `borrower_id` | VARCHAR → BIGINT | FK lookup via `borrowers.external_id` |
| `BORR_FST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | `product_id` | VARCHAR → BIGINT | FK lookup via `loan_products.code` |
| `LN_ORIG_AMT` | `original_amount` | VARCHAR → DECIMAL(12,2) | Remove commas, cast |
| `LN_CURR_BAL` | `current_balance` | VARCHAR → DECIMAL(12,2) | Remove commas, cast |
| `LN_INT_RT` | `interest_rate` | VARCHAR → DECIMAL(5,3) | Cast (no commas expected) |
| `LN_TERM_MOS` | `term_months` | VARCHAR → INT | Cast |
| `LN_PMT_AMT` | `monthly_payment` | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| `LN_ORIG_DT` | `origination_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `LN_MAT_DT` | `maturity_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `LN_1ST_PMT_DT` | `first_payment_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `LN_NXT_PMT_DT` | `next_payment_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `LN_STAT_CD` | `status` | VARCHAR → STRING | ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| `LN_DLQ_DAYS` | `delinquency_days` | VARCHAR → INT | Cast |
| `LN_ESCROW_BAL` | `escrow_balance` | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| `LN_LTV_PCT` | `ltv_percent` | VARCHAR → DECIMAL(5,2) | Cast |
| `PROP_ADDR_LN1` | `property_address` | VARCHAR → STRING | Direct copy |
| `PROP_CTY_NM` | `property_city` | VARCHAR → STRING | Direct copy |
| `PROP_ST_CD` | `property_state` | VARCHAR → STRING | Direct copy |
| `PROP_ZIP_CD` | `property_zip` | VARCHAR → STRING | Direct copy |
| `PROP_TYP_CD` | `property_type` | VARCHAR → STRING | SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| `PROP_APRS_VAL` | `appraised_value` | VARCHAR → DECIMAL(12,2) | Remove commas, cast |
| `LN_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| `LN_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |

### CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| `PMT_SEQ_NBR` | `_legacy_pmt_seq` | VARCHAR → STRING | Preserved for lineage; new BIGINT `payment_id` is PK |
| `LN_ACCT_NBR` | `loan_account_id` | VARCHAR → BIGINT | FK lookup via `loan_accounts.account_number` |
| `PMT_DT` | `payment_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| *(derived)* | `payment_year` | — → INT | `year(payment_date)` — partition key |
| `PMT_AMT` | `total_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| `PMT_PRIN_AMT` | `principal_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| `PMT_INT_AMT` | `interest_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| `PMT_ESCROW_AMT` | `escrow_amount` | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| `PMT_LATE_FEE` | `late_fee` | VARCHAR → DECIMAL(10,2) | Remove commas, cast |
| `PMT_TYP_CD` | `type` | VARCHAR → STRING | REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| `PMT_STAT_CD` | `status` | VARCHAR → STRING | PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| `PMT_RECV_DT` | `received_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `PMT_PROC_DT` | `processed_date` | VARCHAR → DATE | `to_date(col, "MM/dd/yyyy")` |
| `PMT_CRET_DT` | `created_at` | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |
| `PMT_UPDT_DT` | `updated_at` | VARCHAR → TIMESTAMP | `to_timestamp(col, "MM/dd/yyyy")` |

---

## 5. Transformation Decisions

### 5.1 Date Parsing Strategy
**Decision:** Use Spark's `to_date(col, "MM/dd/yyyy")` which returns `null` for unparseable values.

**Rationale:** The legacy system stores all dates as `MM/DD/YYYY` strings. Rather than
rejecting rows with bad dates, we parse what we can and leave nulls for manual review.
The quality framework flags any null dates post-ingestion.

### 5.2 Amount Parsing Strategy
**Decision:** Strip `$`, `,` characters using `regexp_replace`, then cast to `DecimalType`.

**Rationale:** Legacy amounts contain commas as thousands separators (e.g., `"285,000"`,
`"1,487.02"`). Some may contain dollar signs. The regex approach handles both gracefully.
Unparseable values become null and are logged.

### 5.3 Status Code Expansion
**Decision:** Map abbreviations to full-length readable strings using explicit CASE expressions.
Unknown codes are prefixed with `"UNKNOWN:"` rather than being set to null.

**Rationale:** Preserving unknown codes (instead of nulling them) allows operators to
identify and investigate new/unexpected status codes without data loss.

| Domain | Abbreviation | Expanded Value |
|--------|-------------|----------------|
| Loan Status | ACT | ACTIVE |
| Loan Status | CLO | CLOSED |
| Loan Status | DFT | DEFAULT |
| Loan Status | FRB | FORBEARANCE |
| Borrower Status | ACT | ACTIVE |
| Borrower Status | INA | INACTIVE |
| Product Status | ACT | true (boolean) |
| Product Status | INA | false (boolean) |
| Payment Type | REG | REGULAR |
| Payment Type | EXT | EXTRA |
| Payment Type | PRT | PARTIAL |
| Payment Type | PRE | PREPAYMENT |
| Payment Status | PST | POSTED |
| Payment Status | REV | REVERSED |
| Payment Status | NSF | NSF |
| Payment Status | PND | PENDING |
| Property Type | SFR | Single Family |
| Property Type | CND | Condominium |
| Property Type | MFR | Multi-Family |
| Property Type | TWN | Townhouse |

### 5.4 Denormalization Removal
**Decision:** Drop `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` from `loan_accounts`.
Replace with `borrower_id` FK resolved via join to `borrowers.external_id`.

**Rationale:** The legacy schema embeds borrower data directly in loan accounts for
convenience. In the modern schema, borrower data lives in a single authoritative
`borrowers` table, eliminating update anomalies.

### 5.5 Foreign Key Resolution
**Decision:** Resolve legacy string references (`BORR_ID`, `PROD_CD`, `LN_ACCT_NBR`)
to modern `BIGINT` foreign keys via left joins during ingestion.

**Rationale:** Left joins (not inner joins) ensure that orphaned records are preserved
in the target with null FKs. The quality framework then flags these orphans for review
rather than silently dropping them.

### 5.6 Lineage Columns
**Decision:** Every target table includes a `_legacy_*` column storing the original
primary key and an `_ingested_at` timestamp.

**Rationale:** Enables traceability from any modern record back to the source CDW row.
Critical for audit, debugging, and reconciliation.

### 5.7 Payment Year Partition Key
**Decision:** Extract `payment_year = year(payment_date)` as a materialized partition column.

**Rationale:** Payment queries almost always filter by date range. Partitioning by year
gives good partition pruning without creating too many small partitions (vs. monthly).

---

## 6. Partitioning Rationale

| Table | Partition Column | Justification |
|-------|-----------------|---------------|
| `loan_accounts` | `status` | Most queries filter by active vs. closed. Low cardinality (4 values) ensures large, efficient partitions. |
| `payments` | `payment_year` | Time-range queries are dominant access pattern. Year-level gives good pruning without over-partitioning. |
| `borrowers` | *(none)* | Small dimension table. No partition needed. |
| `loan_products` | *(none)* | Tiny reference table (<100 rows expected). No partition needed. |

All tables enable Delta Lake auto-optimize (`optimizeWrite` + `autoCompact`) to handle
small-file consolidation automatically.

---

## 7. Execution Order

The ingestion pipeline must respect foreign key dependencies:

```
Step 1: CREATE DATABASE loan_warehouse
        (run_all.py → create_schema)

Step 2: Run DDL scripts in order
        databricks/ddl/01_borrowers.sql
        databricks/ddl/02_loan_products.sql
        databricks/ddl/03_loan_accounts.sql
        databricks/ddl/04_payments.sql
        databricks/ddl/05_migration_audit.sql

Step 3: Ingest borrowers (no dependencies)
        databricks/ingestion/ingest_borrowers.py

Step 4: Ingest loan products (no dependencies)
        databricks/ingestion/ingest_loan_products.py

Step 5: Ingest loan accounts (depends on Steps 3 & 4)
        databricks/ingestion/ingest_loan_accounts.py

Step 6: Ingest payments (depends on Step 5)
        databricks/ingestion/ingest_payments.py

Step 7: Run data quality checks
        databricks/quality/checks.py

Step 8: Review DATA_QUALITY_REPORT.md
```

**Orchestrator shortcut:** Run `databricks/ingestion/run_all.py` to execute Steps 3-6
in the correct order with automatic audit logging. Then run `databricks/quality/checks.py`
for Step 7.

### Databricks Notebook Setup

```python
# Cell 1: Configuration
# Mount the legacy data source (adjust path for your environment)
LEGACY_DATA_PATH = "/mnt/legacy-cdw"

# Cell 2: Run DDL
for ddl_file in ["01_borrowers", "02_loan_products", "03_loan_accounts",
                  "04_payments", "05_migration_audit"]:
    with open(f"/Workspace/databricks/ddl/{ddl_file}.sql") as f:
        spark.sql(f.read())

# Cell 3: Run ingestion pipeline
%run ./ingestion/run_all

# Cell 4: Run quality checks
%run ./quality/checks
source_counts = {
    "CDW_BORR_MSTR": 5,
    "CDW_LN_PROD": 5,
    "CDW_LN_ACCT": 5,
    "CDW_PMT_HIST": 10,
}
results = run(spark, source_counts=source_counts)
```

---

## 8. Data Quality Checks

The quality framework (`databricks/quality/checks.py`) runs the following post-ingestion
checks:

| # | Check | Category | Severity |
|---|-------|----------|----------|
| 1 | Row count reconciliation (source vs. target per table) | Reconciliation | CRITICAL |
| 2 | NOT NULL on required fields (borrowers, accounts, payments) | Null Check | HIGH |
| 3 | FK integrity: loan_accounts.borrower_id → borrowers | Referential Integrity | HIGH |
| 4 | FK integrity: loan_accounts.product_id → loan_products | Referential Integrity | HIGH |
| 5 | FK integrity: payments.loan_account_id → loan_accounts | Referential Integrity | HIGH |
| 6 | Active loan balance > 0 | Business Rule | MEDIUM |
| 7 | Closed/default loans have updated_at | Business Rule | MEDIUM |
| 8 | Credit score in FICO range (300-850) | Business Rule | MEDIUM |
| 9 | Payment components sum to total | Business Rule | HIGH |
| 10 | Delinquency days consistent with loan status | Business Rule | MEDIUM |
| 11 | LTV percent in 0-200% range | Business Rule | LOW |
| 12 | Date parse success (no nulls from parse failures) | Type Validation | MEDIUM |

### Expected Failures on Seed Data

Based on the known data quality issues in the seed data, the following checks will
**fail** on the initial run:

1. **Payment component integrity** — `PMT-2025120001` (escrow overcounts by $400),
   `PMT-2025110003` (late fee not in total)
2. **Delinquency/status consistency** — `LN-2018-00089` (15 delinquency days + ACTIVE)

These are **expected** and documented in `docs/DATA_ANOMALY_REPORT.md`.

---

## 9. Rollback Procedure

Delta Lake supports time travel, making rollback straightforward:

```sql
-- View table history
DESCRIBE HISTORY loan_warehouse.borrowers;

-- Restore to a specific version
RESTORE TABLE loan_warehouse.borrowers TO VERSION AS OF <version_number>;

-- Or restore to a timestamp
RESTORE TABLE loan_warehouse.payments TO TIMESTAMP AS OF '2025-01-15T00:00:00';
```

For a full rollback of all tables:

```sql
-- Drop all target tables (preserving the schema for re-run)
DROP TABLE IF EXISTS loan_warehouse.payments;
DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
DROP TABLE IF EXISTS loan_warehouse.loan_products;
DROP TABLE IF EXISTS loan_warehouse.borrowers;
-- Keep migration_audit_log for debugging
```

---

## 10. Known Data Quality Issues

See `docs/DATA_ANOMALY_REPORT.md` for a comprehensive catalog. Key issues relevant
to this migration:

| ID | Issue | Impact on Migration |
|----|-------|---------------------|
| ANO-001 | All VARCHAR columns | Every column needs type coercion — null on parse failure |
| ANO-002 | Dates as MM/DD/YYYY strings | `to_date` handles this; nulls flagged by quality checks |
| ANO-003 | Payment components don't sum | Ingested as-is; flagged by integrity check |
| ANO-004 | No FK constraints in source | Left joins preserve orphans; flagged by integrity check |
| ANO-005 | Denormalized borrower data | Dropped from loan_accounts; resolved via borrower FK |
| ANO-007 | Commas in monetary amounts | `regexp_replace` strips commas before casting |
| ANO-011 | Delinquency/status mismatch | Ingested as-is; flagged by business rule check |
