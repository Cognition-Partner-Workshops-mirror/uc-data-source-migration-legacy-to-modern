# Databricks Migration Runbook

## Legacy CDW → Delta Lake (Loan Management System)

---

## Table of Contents

1. [Overview](#overview)
2. [Source System Analysis](#source-system-analysis)
3. [Column Mapping Reference](#column-mapping-reference)
4. [Type Conversion Decisions](#type-conversion-decisions)
5. [Transformation Rules](#transformation-rules)
6. [Partitioning Strategy](#partitioning-strategy)
7. [Execution Order](#execution-order)
8. [Databricks Cluster Configuration](#databricks-cluster-configuration)
9. [Pre-Migration Checklist](#pre-migration-checklist)
10. [Post-Migration Validation](#post-migration-validation)
11. [Rollback Plan](#rollback-plan)
12. [Known Edge Cases](#known-edge-cases)

---

## Overview

This runbook documents the migration of a legacy Corporate Data Warehouse (CDW) loan management system to Databricks Delta Lake. The legacy system stores all data as VARCHAR strings with cryptic abbreviated column names, no foreign key constraints, and embedded status code abbreviations.

### Migration Goals

- **Type Safety:** Convert all-VARCHAR columns to proper Spark SQL types (DATE, DECIMAL, INT, BOOLEAN)
- **Normalization:** Split denormalized borrower fields out of loan accounts into a separate dimension table
- **Readability:** Map cryptic column names (BORR_FST_NM) to meaningful names (first_name)
- **Referential Integrity:** Establish proper foreign key relationships between tables
- **Query Performance:** Implement Delta Lake partitioning and auto-optimization

### Architecture

```
Legacy CDW (H2/MySQL)          →    Databricks Delta Lake
─────────────────────                ────────────────────
CDW_BORR_MSTR (all VARCHAR)    →    loan_warehouse.borrowers (typed, partitioned by state)
CDW_LN_PROD   (all VARCHAR)    →    loan_warehouse.loan_products (typed)
CDW_LN_ACCT   (all VARCHAR)    →    loan_warehouse.loan_accounts (typed, partitioned by status)
CDW_PMT_HIST  (all VARCHAR)    →    loan_warehouse.payments (typed, partitioned by year/month)
```

---

## Source System Analysis

### Legacy Schema Characteristics

| Characteristic | Description |
|---|---|
| **Database** | CDW-style relational (H2 for dev, likely DB2/Oracle in prod) |
| **Typing** | All columns VARCHAR — no native dates, decimals, or integers |
| **Naming** | Abbreviated cryptic names (max ~15 chars), inconsistent patterns |
| **Date Format** | MM/DD/YYYY stored as VARCHAR(10) strings |
| **Amount Format** | Comma-separated strings (e.g., "285,000", "271,432.56") |
| **Status Codes** | 3-char abbreviations (ACT, CLO, DFT, FRB, etc.) |
| **Foreign Keys** | None enforced — denormalized with redundant borrower data in loan table |
| **Primary Keys** | String-based IDs (B-10001, LN-2019-00142, PMT-2025120001) |

### Source Tables

| Table | Purpose | Approx. Columns | Key Issues |
|---|---|---|---|
| `CDW_BORR_MSTR` | Borrower master | 20 | SSN stored encrypted, income/credit as strings |
| `CDW_LN_PROD` | Loan products | 10 | Min/max amounts as strings |
| `CDW_LN_ACCT` | Loan accounts | 27 | Denormalized borrower fields, all amounts as strings |
| `CDW_PMT_HIST` | Payment history | 14 | All amounts as strings, multiple date fields |

---

## Column Mapping Reference

### CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| BORR_ID | external_id | VARCHAR→STRING | Direct copy |
| BORR_FST_NM | first_name | VARCHAR→STRING | Direct copy |
| BORR_LST_NM | last_name | VARCHAR→STRING | Direct copy |
| BORR_MID_INIT | middle_initial | VARCHAR→STRING | Direct copy |
| BORR_SSN_ENCR | ssn_hash | VARCHAR→STRING | Direct copy (re-encrypt recommended) |
| BORR_DOB_DT | date_of_birth | VARCHAR→DATE | Parse MM/DD/YYYY |
| BORR_ADDR_LN1 | address_line1 | VARCHAR→STRING | Direct copy |
| BORR_ADDR_LN2 | address_line2 | VARCHAR→STRING | Direct copy |
| BORR_CTY_NM | city | VARCHAR→STRING | Direct copy |
| BORR_ST_CD | state | VARCHAR→STRING | Direct copy |
| BORR_ZIP_CD | zip_code | VARCHAR→STRING | Direct copy |
| BORR_PH_NBR | phone | VARCHAR→STRING | Direct copy |
| BORR_EMAIL_ADDR | email | VARCHAR→STRING | Direct copy |
| BORR_CRDT_SCR | credit_score | VARCHAR→INT | Parse string to integer |
| BORR_EMP_STAT | employment_status | VARCHAR→STRING | Direct copy |
| BORR_ANN_INCM | annual_income | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| BORR_CRET_DT | created_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |
| BORR_UPDT_DT | updated_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |
| BORR_STAT_CD | status | VARCHAR→STRING | Expand: ACT→ACTIVE, INA→INACTIVE |
| BORR_REC_TYP | *(dropped)* | — | Not needed in modern schema |

### CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| PROD_CD | code | VARCHAR→STRING | Direct copy |
| PROD_DESC_TXT | name | VARCHAR→STRING | Direct copy |
| PROD_TYP_CD | type | VARCHAR→STRING | Direct copy |
| PROD_TERM_MOS | term_months | VARCHAR→INT | Parse string |
| PROD_RT_TYP | rate_type | VARCHAR→STRING | Direct copy |
| PROD_MIN_AMT | min_amount | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| PROD_MAX_AMT | max_amount | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| PROD_STAT_CD | is_active | VARCHAR→BOOLEAN | ACT→true, INA→false |
| PROD_EFF_DT | effective_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| PROD_EXP_DT | expiration_date | VARCHAR→DATE | Parse MM/DD/YYYY |

### CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| LN_ACCT_NBR | account_number | VARCHAR→STRING | Direct copy |
| BORR_ID | borrower_id | VARCHAR→BIGINT | FK lookup via borrowers.external_id |
| BORR_FST_NM | *(dropped)* | — | Denormalized; use borrower FK |
| BORR_LST_NM | *(dropped)* | — | Denormalized; use borrower FK |
| BORR_SSN_LST4 | *(dropped)* | — | Denormalized; use borrower FK |
| PROD_CD | product_id | VARCHAR→BIGINT | FK lookup via loan_products.code |
| LN_ORIG_AMT | original_amount | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| LN_CURR_BAL | current_balance | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| LN_INT_RT | interest_rate | VARCHAR→DECIMAL(5,3) | Parse string |
| LN_TERM_MOS | term_months | VARCHAR→INT | Parse string |
| LN_PMT_AMT | monthly_payment | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| LN_ORIG_DT | origination_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_MAT_DT | maturity_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_1ST_PMT_DT | first_payment_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_NXT_PMT_DT | next_payment_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_STAT_CD | status | VARCHAR→STRING | Expand: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| LN_DLQ_DAYS | delinquency_days | VARCHAR→INT | Parse string |
| LN_ESCROW_BAL | escrow_balance | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| LN_LTV_PCT | ltv_percent | VARCHAR→DECIMAL(5,2) | Parse string |
| PROP_ADDR_LN1 | property_address | VARCHAR→STRING | Direct copy |
| PROP_CTY_NM | property_city | VARCHAR→STRING | Direct copy |
| PROP_ST_CD | property_state | VARCHAR→STRING | Direct copy |
| PROP_ZIP_CD | property_zip | VARCHAR→STRING | Direct copy |
| PROP_TYP_CD | property_type | VARCHAR→STRING | Expand: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| PROP_APRS_VAL | appraised_value | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| LN_CRET_DT | created_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |
| LN_UPDT_DT | updated_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |

### CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Change | Transformation |
|---|---|---|---|
| PMT_SEQ_NBR | legacy_payment_id | VARCHAR→STRING | Preserved for audit |
| LN_ACCT_NBR | loan_account_id | VARCHAR→BIGINT | FK lookup via loan_accounts.account_number |
| PMT_DT | payment_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| PMT_AMT | total_amount | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_PRIN_AMT | principal_amount | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_INT_AMT | interest_amount | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_ESCROW_AMT | escrow_amount | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_LATE_FEE | late_fee | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_TYP_CD | type | VARCHAR→STRING | Expand: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| PMT_STAT_CD | status | VARCHAR→STRING | Expand: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| PMT_RECV_DT | received_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| PMT_PROC_DT | processed_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| PMT_CRET_DT | created_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |
| PMT_UPDT_DT | updated_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |

---

## Type Conversion Decisions

### Date Fields → DATE vs. TIMESTAMP

| Decision | Rationale |
|---|---|
| DOB, origination, maturity, payment dates → **DATE** | These represent calendar dates with no time component |
| created_at, updated_at → **TIMESTAMP** | Audit timestamps; even though source has only dates, TIMESTAMP allows future precision |

### Amount Fields → DECIMAL Precision

| Field Category | Type | Rationale |
|---|---|---|
| Loan amounts (original, balance, appraised) | DECIMAL(12,2) | Supports up to $9,999,999,999.99 |
| Payment amounts (total, principal, interest) | DECIMAL(10,2) | Supports up to $99,999,999.99 |
| Interest rates | DECIMAL(5,3) | Supports rates like 99.999% (e.g., 4.750%) |
| LTV percentage | DECIMAL(5,2) | Supports values like 999.99% |
| Annual income | DECIMAL(12,2) | Supports high incomes up to ~$10B |

### Status Codes → Expanded Strings (not Enum)

We expand abbreviated codes to full readable strings rather than using a lookup/enum table because:
1. The code set is small and stable
2. Avoids an extra join for every query
3. Delta Lake CHECK constraints enforce valid values
4. Readable in ad-hoc queries without needing documentation

### ID Fields → BIGINT with IDENTITY

Modern tables use auto-generated BIGINT identity columns because:
1. Uniform integer keys enable efficient joins
2. Legacy string IDs are preserved in `external_id` / `legacy_payment_id` columns
3. No collision risk across systems

---

## Transformation Rules

### 1. Date Parsing

```python
# Input: "03/15/1978" (MM/DD/YYYY)
# Output: 1978-03-15 (DateType)
F.to_date(F.col("BORR_DOB_DT"), "MM/dd/yyyy")
```

**Edge cases handled:**
- NULL input → NULL output (no error)
- Invalid date (e.g., "13/45/2020") → NULL output + error flag
- Empty string → NULL output

### 2. Amount Parsing

```python
# Input: "285,000" or "271,432.56"
# Output: Decimal(285000.00) or Decimal(271432.56)
F.regexp_replace(F.col("LN_ORIG_AMT"), ",", "").cast(DecimalType(12, 2))
```

**Edge cases handled:**
- NULL input → NULL output
- Non-numeric after comma removal → NULL + error flag
- "0" → Decimal(0.00)

### 3. Status Code Expansion

```python
# Input: "ACT"
# Output: "ACTIVE"
mapping = {"ACT": "ACTIVE", "CLO": "CLOSED", "DFT": "DEFAULT", "FRB": "FORBEARANCE"}
```

**Edge cases handled:**
- Unknown code → preserved with "_UNKNOWN" suffix (e.g., "XYZ_UNKNOWN")
- NULL → NULL (not expanded)
- Case insensitive matching (whitespace trimmed)

### 4. Denormalization Removal

The `CDW_LN_ACCT` table embeds borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) redundantly. These are:
- **Dropped** from loan_accounts
- **Replaced** by a `borrower_id` foreign key resolved via `CDW_BORR_MSTR.BORR_ID`

### 5. Foreign Key Resolution

```
CDW_LN_ACCT.BORR_ID → JOIN borrowers ON external_id → borrowers.id
CDW_LN_ACCT.PROD_CD → JOIN loan_products ON code → loan_products.id
CDW_PMT_HIST.LN_ACCT_NBR → JOIN loan_accounts ON account_number → loan_accounts.id
```

Unresolved FKs are logged to rejection tables but records are NOT dropped.

---

## Partitioning Strategy

| Table | Partition Column(s) | Rationale |
|---|---|---|
| **borrowers** | `state` | Geographic queries are common; ~50 partitions (US states) |
| **loan_products** | *(none)* | Small reference table (~10-50 rows); partitioning adds overhead |
| **loan_accounts** | `status` | Portfolio analysis by status (ACTIVE/CLOSED/DEFAULT/FORBEARANCE); 4 partitions |
| **payments** | `payment_year`, `payment_month` | Time-series queries; efficient pruning for monthly reporting |

### Why These Choices

- **loan_accounts by status:** Most queries filter by active vs. closed portfolio. Only 4 partition values keeps files optimally sized.
- **payments by year/month:** Payment data grows monthly. Partitioning by time enables efficient date-range queries and partition pruning.
- **borrowers by state:** Regulatory reporting often requires geographic segmentation. ~50 partitions is a good balance.
- **All tables:** Delta Lake auto-optimization (`optimizeWrite` + `autoCompact`) handles small file problems.

---

## Execution Order

The pipeline must execute in dependency order due to foreign key resolution:

```
Step 1: Create Database/Schema
         ↓
Step 2: Ingest borrowers (no dependencies)
Step 3: Ingest loan_products (no dependencies)
         ↓  (Steps 2 & 3 can run in parallel)
Step 4: Ingest loan_accounts (depends on borrowers + loan_products)
         ↓
Step 5: Ingest payments (depends on loan_accounts)
         ↓
Step 6: Run data quality checks
         ↓
Step 7: Generate quality report
```

### Databricks Job Configuration

```json
{
  "name": "CDW_Migration_Pipeline",
  "tasks": [
    {"task_key": "create_schema", "notebook_path": "databricks/ddl/00_database"},
    {"task_key": "ingest_borrowers", "depends_on": ["create_schema"], "notebook_path": "databricks/ingestion/ingest_borrowers"},
    {"task_key": "ingest_products", "depends_on": ["create_schema"], "notebook_path": "databricks/ingestion/ingest_loan_products"},
    {"task_key": "ingest_accounts", "depends_on": ["ingest_borrowers", "ingest_products"], "notebook_path": "databricks/ingestion/ingest_loan_accounts"},
    {"task_key": "ingest_payments", "depends_on": ["ingest_accounts"], "notebook_path": "databricks/ingestion/ingest_payments"},
    {"task_key": "quality_checks", "depends_on": ["ingest_payments"], "notebook_path": "databricks/quality/run_quality_checks"}
  ]
}
```

---

## Databricks Cluster Configuration

### Recommended Cluster Specs

| Setting | Value | Rationale |
|---|---|---|
| Runtime | DBR 14.x+ (with Unity Catalog) | Required for Delta Lake constraints and IDENTITY columns |
| Worker Type | Standard_DS3_v2 (or equivalent) | Balanced compute/memory for ETL |
| Workers | 2-4 (for initial load) | Source data is small; scale up for production volumes |
| Autoscaling | Enabled (min 2, max 8) | Handle payment history growth |
| Spark Config | `spark.sql.adaptive.enabled=true` | Optimize joins and shuffles |

### Required Libraries

- PySpark (included in DBR)
- No additional PyPI packages required

---

## Pre-Migration Checklist

- [ ] Unity Catalog and schema `loan_warehouse` created
- [ ] Source files extracted from legacy system to `/mnt/legacy-data/cdw/`
- [ ] Source file format verified (CSV with headers or Parquet)
- [ ] Cluster configured with appropriate DBR version (14.x+)
- [ ] Storage permissions configured for source and target paths
- [ ] Rejection log path `/mnt/data/rejections/` is writable
- [ ] DDL scripts reviewed and approved by data governance team
- [ ] Backup of legacy source data confirmed

---

## Post-Migration Validation

After the pipeline completes, run the quality framework (`databricks/quality/run_quality_checks.py`):

1. **Row Count Reconciliation** — Verify source and target counts match
2. **Null Checks** — Required fields (IDs, names, statuses) must not be null
3. **Referential Integrity** — All FK values must resolve to parent tables
4. **Business Rules:**
   - Active loans must have positive balance
   - Closed loans must have an updated_at date
   - Payment components must sum to total amount (±$0.01)
   - Credit scores must be 300-850
   - Loan terms must be standard (60/120/180/240/300/360 months)

### Acceptance Criteria

| Metric | Threshold |
|---|---|
| Row count match | 100% (0 tolerance) |
| Required field nulls | 0 |
| FK integrity violations | 0 |
| Business rule failures | 0 critical, <1% warnings |

---

## Rollback Plan

If migration fails or quality checks indicate unacceptable data loss:

1. **Drop target tables:**
   ```sql
   DROP TABLE IF EXISTS loan_warehouse.payments;
   DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
   DROP TABLE IF EXISTS loan_warehouse.loan_products;
   DROP TABLE IF EXISTS loan_warehouse.borrowers;
   ```

2. **Investigate rejection logs** at `/mnt/data/rejections/{table_name}/`

3. **Fix transformation logic** in `databricks/ingestion/transformations.py`

4. **Re-run pipeline** with `mode="overwrite"` (default)

Delta Lake's ACID transactions ensure partial writes don't corrupt the target tables.

---

## Known Edge Cases

| Issue | Handling | Impact |
|---|---|---|
| NULL middle initial | Passed through as NULL | None — optional field |
| NULL address_line2 | Passed through as NULL | None — optional field |
| Commas in amount strings | Removed via regex before decimal parse | None |
| "0" as loan amount (VA loans) | Parsed as DECIMAL 0.00 | Valid for VA min_amount |
| 15-day delinquency (borderline) | Stored as integer 15 | Business logic in downstream |
| Unknown status codes | Preserved with "_UNKNOWN" suffix | Flagged in quality report |
| Unresolved FK (orphan BORR_ID) | Record kept, logged to rejections | Quality check will catch |
| Future dates in PROD_EXP_DT | Accepted (e.g., 12/31/2099) | Valid for open-ended products |

---

## Appendix: Status Code Reference

### Loan Status (LN_STAT_CD)
| Code | Expansion | Description |
|---|---|---|
| ACT | ACTIVE | Loan is current and being serviced |
| CLO | CLOSED | Loan has been paid off or settled |
| DFT | DEFAULT | Borrower has defaulted on payments |
| FRB | FORBEARANCE | Temporary payment reduction/pause |

### Payment Type (PMT_TYP_CD)
| Code | Expansion | Description |
|---|---|---|
| REG | REGULAR | Standard monthly payment |
| EXT | EXTRA | Additional payment beyond minimum |
| PRT | PARTIAL | Less than full payment amount |
| PRE | PREPAYMENT | Early payoff (full or partial) |

### Payment Status (PMT_STAT_CD)
| Code | Expansion | Description |
|---|---|---|
| PST | POSTED | Payment applied to account |
| REV | REVERSED | Payment reversed (e.g., chargeback) |
| NSF | NSF | Non-sufficient funds |
| PND | PENDING | Payment received, not yet applied |

### Property Type (PROP_TYP_CD)
| Code | Expansion | Description |
|---|---|---|
| SFR | Single Family | Single-family residence |
| CND | Condominium | Condo unit |
| MFR | Multi-Family | Multi-family dwelling (2-4 units) |
| TWN | Townhouse | Townhouse/rowhouse |

### Borrower Status (BORR_STAT_CD)
| Code | Expansion | Description |
|---|---|---|
| ACT | ACTIVE | Active borrower |
| INA | INACTIVE | Inactive/archived borrower |
