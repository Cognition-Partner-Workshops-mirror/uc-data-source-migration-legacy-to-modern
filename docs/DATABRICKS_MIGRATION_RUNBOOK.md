# Databricks Migration Runbook — CDW Legacy to Modern Schema

> **Version:** 1.0
> **Date:** 2026-05-07
> **Source System:** Corporate Data Warehouse (CDW) — H2/SQL legacy tables
> **Target System:** Databricks Lakehouse — Delta Lake tables

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Execution Order](#execution-order)
4. [Column Mapping Reference](#column-mapping-reference)
5. [Type Conversion Decisions](#type-conversion-decisions)
6. [Status Code Expansion](#status-code-expansion)
7. [Partitioning Strategy](#partitioning-strategy)
8. [Anomaly Handling Strategy](#anomaly-handling-strategy)
9. [Rollback Procedure](#rollback-procedure)

---

## Overview

This runbook documents the migration of 4 legacy CDW tables into a normalized Delta Lake schema:

| Legacy Table | Target Table | Records (Est.) | Complexity |
|-------------|-------------|----------------|------------|
| CDW_BORR_MSTR | loan_warehouse.borrowers | ~thousands | Medium — date/amount parsing, dedup |
| CDW_LN_PROD | loan_warehouse.loan_products | ~tens | Low — small reference table |
| CDW_LN_ACCT | loan_warehouse.loan_accounts | ~tens of thousands | High — FK resolution, denorm removal |
| CDW_PMT_HIST | loan_warehouse.payments | ~hundreds of thousands | High — FK resolution, reconciliation |

A fifth table, `loan_warehouse.data_quality_log`, captures all anomalies detected during ingestion.

---

## Prerequisites

1. **Databricks Workspace** with Unity Catalog enabled
2. **Catalog/Schema**: Create `loan_warehouse` schema:
   ```sql
   CREATE SCHEMA IF NOT EXISTS loan_warehouse
   COMMENT 'Modern normalized loan data warehouse migrated from legacy CDW';
   ```
3. **Source Data**: Legacy CDW data exported as CSV or Parquet files to:
   - `/mnt/legacy-cdw/CDW_BORR_MSTR/`
   - `/mnt/legacy-cdw/CDW_LN_PROD/`
   - `/mnt/legacy-cdw/CDW_LN_ACCT/`
   - `/mnt/legacy-cdw/CDW_PMT_HIST/`
4. **Cluster**: Databricks Runtime 14.0+ with:
   - At least 4 workers for payment history processing
   - Delta Lake optimized writes enabled
5. **Permissions**: `CREATE TABLE`, `INSERT`, `MERGE` on `loan_warehouse` schema

---

## Execution Order

**Order matters** — dimension tables must be populated before fact tables that reference them via FK lookups.

### Step 1: Create Delta Tables

```bash
# Run DDL script
databricks workspace import databricks/ddl/create_delta_tables.sql
# Execute in a SQL warehouse or notebook
```

### Step 2: Ingest Borrowers (dimension)

```bash
spark-submit databricks/ingestion/ingest_borrowers.py
```

**What it does:**
- Reads CDW_BORR_MSTR CSV/Parquet
- Parses dates (MM/DD/YYYY → DATE), amounts (commas → DECIMAL), credit scores
- Expands status codes (ACT→ACTIVE, INA→INACTIVE)
- Detects null required fields, unparseable values, out-of-range scores, duplicates
- MERGE into `loan_warehouse.borrowers` (idempotent)

### Step 3: Ingest Loan Products (dimension)

```bash
spark-submit databricks/ingestion/ingest_loan_products.py
```

**What it does:**
- Reads CDW_LN_PROD
- Parses amounts, dates, term months
- Converts status to boolean (ACT→true, INA→false)
- MERGE into `loan_warehouse.loan_products`

### Step 4: Ingest Loan Accounts (fact)

```bash
spark-submit databricks/ingestion/ingest_loan_accounts.py
```

**What it does:**
- Reads CDW_LN_ACCT
- **Drops denormalized borrower fields** (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
- Resolves `BORR_ID` → `borrower_id` FK via lookup on `borrowers.external_id`
- Resolves `PROD_CD` → `product_id` FK via lookup on `loan_products.code`
- Expands status and property type codes
- Detects orphaned FKs, name mismatches, delinquency inconsistencies, LTV drift
- MERGE into `loan_warehouse.loan_accounts`

**Depends on:** Steps 2 and 3 (borrowers and products must exist for FK resolution)

### Step 5: Ingest Payments (fact)

```bash
spark-submit databricks/ingestion/ingest_payments.py
```

**What it does:**
- Reads CDW_PMT_HIST
- Resolves `LN_ACCT_NBR` → `loan_account_id` FK
- Derives `payment_year` partition key from payment date
- Detects orphaned loan references, payment reconciliation failures, null required fields
- MERGE into `loan_warehouse.payments`

**Depends on:** Step 4 (loan accounts must exist for FK resolution)

### Step 6: Run Data Quality Checks

```bash
spark-submit databricks/quality/data_quality_checks.py
```

**What it does:**
- Row count reconciliation (source vs. target for all 4 tables)
- Null checks on all required fields
- Referential integrity validation (3 FK relationships)
- Business rule validation (active balance > 0, rate > 0, date ordering, etc.)
- Generates `DATA_QUALITY_REPORT.md`

### Step 7: Review and Sign-off

1. Review `DATA_QUALITY_REPORT.md` for FAIL/WARN items
2. Query `loan_warehouse.data_quality_log` for anomaly details:
   ```sql
   SELECT anomaly_type, severity, COUNT(*) as cnt
   FROM loan_warehouse.data_quality_log
   GROUP BY anomaly_type, severity
   ORDER BY severity, cnt DESC;
   ```
3. Decide on remediation actions for CRITICAL/HIGH anomalies

---

## Column Mapping Reference

### CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| BORR_ID | external_id | VARCHAR→STRING | Direct copy |
| BORR_FST_NM | first_name | VARCHAR→STRING | Trim whitespace |
| BORR_LST_NM | last_name | VARCHAR→STRING | Trim whitespace |
| BORR_MID_INIT | middle_initial | VARCHAR→STRING | Direct copy |
| BORR_SSN_ENCR | ssn_hash | VARCHAR→STRING | Direct copy |
| BORR_DOB_DT | date_of_birth | VARCHAR→DATE | Parse MM/DD/YYYY |
| BORR_ADDR_LN1 | address_line1 | VARCHAR→STRING | Trim |
| BORR_ADDR_LN2 | address_line2 | VARCHAR→STRING | Trim |
| BORR_CTY_NM | city | VARCHAR→STRING | Trim |
| BORR_ST_CD | state | VARCHAR→STRING | Trim |
| BORR_ZIP_CD | zip_code | VARCHAR→STRING | Trim |
| BORR_PH_NBR | phone | VARCHAR→STRING | Trim |
| BORR_EMAIL_ADDR | email | VARCHAR→STRING | Trim |
| BORR_CRDT_SCR | credit_score | VARCHAR→INT | Parse, validate 300-850 |
| BORR_EMP_STAT | employment_status | VARCHAR→STRING | Trim |
| BORR_ANN_INCM | annual_income | VARCHAR→DECIMAL(12,2) | Strip commas/$ |
| BORR_CRET_DT | created_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |
| BORR_UPDT_DT | updated_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |
| BORR_STAT_CD | status | VARCHAR→STRING | ACT→ACTIVE, INA→INACTIVE |
| BORR_REC_TYP | *(dropped)* | — | Not needed |

### CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| LN_ACCT_NBR | account_number | VARCHAR→STRING | Direct copy |
| BORR_ID | borrower_id | VARCHAR→BIGINT | FK lookup on borrowers.external_id |
| BORR_FST_NM | *(dropped)* | — | Denormalized; use borrower FK |
| BORR_LST_NM | *(dropped)* | — | Denormalized; use borrower FK |
| BORR_SSN_LST4 | *(dropped)* | — | Denormalized; use borrower FK |
| PROD_CD | product_id | VARCHAR→BIGINT | FK lookup on loan_products.code |
| LN_ORIG_AMT | original_amount | VARCHAR→DECIMAL(12,2) | Strip commas/$ |
| LN_CURR_BAL | current_balance | VARCHAR→DECIMAL(12,2) | Strip commas/$ |
| LN_INT_RT | interest_rate | VARCHAR→DECIMAL(5,3) | Parse string |
| LN_TERM_MOS | term_months | VARCHAR→INT | Parse string |
| LN_PMT_AMT | monthly_payment | VARCHAR→DECIMAL(10,2) | Strip commas/$ |
| LN_ORIG_DT | origination_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_MAT_DT | maturity_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_1ST_PMT_DT | first_payment_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_NXT_PMT_DT | next_payment_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_STAT_CD | status | VARCHAR→STRING | ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| LN_DLQ_DAYS | delinquency_days | VARCHAR→INT | Parse string |
| LN_ESCROW_BAL | escrow_balance | VARCHAR→DECIMAL(10,2) | Strip commas/$ |
| LN_LTV_PCT | ltv_percent | VARCHAR→DECIMAL(5,2) | Parse string |
| PROP_ADDR_LN1 | property_address | VARCHAR→STRING | Trim |
| PROP_CTY_NM | property_city | VARCHAR→STRING | Trim |
| PROP_ST_CD | property_state | VARCHAR→STRING | Trim |
| PROP_ZIP_CD | property_zip | VARCHAR→STRING | Trim |
| PROP_TYP_CD | property_type | VARCHAR→STRING | SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| PROP_APRS_VAL | appraised_value | VARCHAR→DECIMAL(12,2) | Strip commas/$ |
| LN_CRET_DT | created_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |
| LN_UPDT_DT | updated_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |

### CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| PMT_SEQ_NBR | legacy_sequence_nbr | VARCHAR→STRING | For traceability |
| LN_ACCT_NBR | loan_account_id | VARCHAR→BIGINT | FK lookup on loan_accounts.account_number |
| PMT_DT | payment_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| PMT_AMT | total_amount | VARCHAR→DECIMAL(10,2) | Strip commas/$ |
| PMT_PRIN_AMT | principal_amount | VARCHAR→DECIMAL(10,2) | Strip commas/$ |
| PMT_INT_AMT | interest_amount | VARCHAR→DECIMAL(10,2) | Strip commas/$ |
| PMT_ESCROW_AMT | escrow_amount | VARCHAR→DECIMAL(10,2) | Strip commas/$ |
| PMT_LATE_FEE | late_fee | VARCHAR→DECIMAL(10,2) | Strip commas/$ |
| PMT_TYP_CD | type | VARCHAR→STRING | REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| PMT_STAT_CD | status | VARCHAR→STRING | PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| PMT_RECV_DT | received_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| PMT_PROC_DT | processed_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| PMT_CRET_DT | created_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |
| PMT_UPDT_DT | updated_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |
| *(derived)* | payment_year | — | YEAR(payment_date) for partition key |

---

## Type Conversion Decisions

| Source Pattern | Target Type | Rationale |
|---------------|-------------|-----------|
| VARCHAR dates (MM/DD/YYYY) | DATE or TIMESTAMP | Enables date arithmetic, range queries, and consistent formatting. Fallback parsing for ISO format handles migrated records. |
| VARCHAR amounts ("285,000") | DECIMAL(12,2) | Enables aggregation, comparison, and financial calculations. Commas and $ stripped before cast. |
| VARCHAR integers ("360") | INT | Enables arithmetic. Non-numeric values become NULL (logged). |
| VARCHAR status ("ACT") | STRING (expanded) | Human-readable values improve downstream usability. Original codes preserved in DQ log. |
| VARCHAR boolean (ACT/INA) | BOOLEAN | For product `is_active` — simpler filtering. |
| VARCHAR ID ("B-10001") | STRING (external_id) + BIGINT (PK) | Preserve legacy ID for traceability; use auto-increment BIGINT as PK for FK relationships. |

---

## Status Code Expansion

| Table | Legacy Code | Modern Value |
|-------|------------|-------------|
| Borrowers | ACT | ACTIVE |
| Borrowers | INA | INACTIVE |
| Loan Accounts | ACT | ACTIVE |
| Loan Accounts | CLO | CLOSED |
| Loan Accounts | DFT | DEFAULT |
| Loan Accounts | FRB | FORBEARANCE |
| Payments (type) | REG | REGULAR |
| Payments (type) | EXT | EXTRA |
| Payments (type) | PRT | PARTIAL |
| Payments (type) | PRE | PREPAYMENT |
| Payments (status) | PST | POSTED |
| Payments (status) | REV | REVERSED |
| Payments (status) | NSF | NSF |
| Payments (status) | PND | PENDING |
| Property Type | SFR | Single Family |
| Property Type | CND | Condominium |
| Property Type | MFR | Multi-Family |
| Property Type | TWN | Townhouse |

Unrecognized codes pass through as uppercase after normalization, and are logged to the DQ anomaly table.

---

## Partitioning Strategy

| Table | Partition Column | Rationale |
|-------|-----------------|-----------|
| borrowers | *(none)* | Small dimension table; no benefit from partitioning |
| loan_products | *(none)* | Tiny reference table (~5-50 rows) |
| loan_accounts | `status` | Most queries filter by ACTIVE/CLOSED/DEFAULT. ~4 partitions keeps file sizes optimal. |
| payments | `payment_year` | Time-range queries are the primary access pattern for payment history. Year-level partitioning balances partition count with file size. |
| data_quality_log | `source_table` | Anomalies are typically queried per source table for investigation. |

All tables have `delta.autoOptimize.optimizeWrite` enabled for automatic file compaction. Change Data Feed is enabled on dimension and fact tables for downstream CDC consumers.

---

## Anomaly Handling Strategy

The pipeline **never silently drops records**. Instead:

1. **Parseable but anomalous** → Record is ingested with the anomaly logged to `data_quality_log`.
2. **Unparseable values** → NULL is written to the target column, original value logged.
3. **Orphaned FK references** → Record is ingested with NULL FK (left join), anomaly logged as CRITICAL.
4. **Business rule violations** → Record is ingested as-is, violation logged as MEDIUM/HIGH.

This preserves data completeness for investigation while providing full audit trail of quality issues.

---

## Rollback Procedure

Delta Lake's time travel enables instant rollback:

```sql
-- View table history
DESCRIBE HISTORY loan_warehouse.loan_accounts;

-- Restore to a specific version
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF <version_number>;

-- Or restore to a timestamp
RESTORE TABLE loan_warehouse.borrowers TO TIMESTAMP AS OF '2026-05-07T00:00:00Z';
```

For full pipeline rollback, restore all 4 tables to their pre-migration versions and truncate the `data_quality_log` for the specific run:

```sql
DELETE FROM loan_warehouse.data_quality_log WHERE run_id LIKE '%_ingest_20260507%';
```
