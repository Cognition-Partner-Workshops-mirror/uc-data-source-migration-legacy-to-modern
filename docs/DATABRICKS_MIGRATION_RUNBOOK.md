# Databricks Migration Runbook

## Legacy CDW → Delta Lake Migration

This document describes every transformation decision, column mapping, type conversion,
partitioning rationale, and the recommended execution order for migrating the legacy
Corporate Data Warehouse (CDW) loan management data into Databricks Delta Lake.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Source System Description](#source-system-description)
3. [Target Schema Design](#target-schema-design)
4. [Column Mappings](#column-mappings)
5. [Type Conversion Decisions](#type-conversion-decisions)
6. [Status Code Expansion](#status-code-expansion)
7. [Partitioning Strategy](#partitioning-strategy)
8. [Data Quality Considerations](#data-quality-considerations)
9. [Execution Order](#execution-order)
10. [Rollback Procedure](#rollback-procedure)
11. [Post-Migration Validation](#post-migration-validation)

---

## 1. Architecture Overview

```
┌──────────────────┐     CSV/Parquet     ┌──────────────────────┐
│  Legacy CDW      │ ──── Extract ────→  │  DBFS Landing Zone   │
│  (H2 / Mainframe)│                     │  /mnt/legacy-extracts│
└──────────────────┘                     └──────────┬───────────┘
                                                    │
                                          PySpark Ingestion
                                          (transform + validate)
                                                    │
                                         ┌──────────▼───────────┐
                                         │  Delta Lake Tables   │
                                         │  loan_warehouse.*    │
                                         │  (typed, normalized) │
                                         └──────────┬───────────┘
                                                    │
                                          Data Quality Checks
                                                    │
                                         ┌──────────▼───────────┐
                                         │  Quality Report      │
                                         │  DATA_QUALITY_REPORT │
                                         └──────────────────────┘
```

**Key Design Principles:**
- **No silent data loss:** Malformed records are logged and quarantined, never silently dropped.
- **Idempotent runs:** All ingestion scripts use `overwrite` mode — safe to re-run.
- **Audit trail:** Every row gets `_ingested_at` and `_source_system` metadata columns.
- **Normalized schema:** Denormalized borrower fields in `CDW_LN_ACCT` are dropped in favor of a proper FK to the `borrowers` dimension table.

---

## 2. Source System Description

The legacy CDW stores all loan management data in 4 tables. Every column is `VARCHAR(n)` —
there are no typed columns, no foreign key constraints, and no check constraints.

| Legacy Table | Description | Row Volume (seed) |
|-------------|-------------|-------------------|
| `CDW_BORR_MSTR` | Borrower master records | 5 |
| `CDW_LN_PROD` | Loan product catalog | 4 |
| `CDW_LN_ACCT` | Loan accounts (denormalized with borrower fields) | 5 |
| `CDW_PMT_HIST` | Payment history | 12 |

**Known legacy issues:**
- Dates stored as `MM/DD/YYYY` strings (not sortable, locale-dependent)
- Amounts stored with commas (`285,000.00`) — not directly castable
- Status codes are 3-letter abbreviations (`ACT`, `CLO`, `DFT`, `FRB`)
- Borrower name/SSN duplicated in both `CDW_BORR_MSTR` and `CDW_LN_ACCT`
- No FK constraints — orphaned records possible
- Credit scores, term months, and rates stored as VARCHAR

---

## 3. Target Schema Design

The modern Delta Lake schema uses 4 tables with proper types and FK relationships:

| Target Table | Source | Partition Column | Rationale |
|-------------|--------|-----------------|-----------|
| `loan_warehouse.borrowers` | CDW_BORR_MSTR | `status` | Filter active vs inactive borrowers efficiently |
| `loan_warehouse.loan_products` | CDW_LN_PROD | *(none)* | Small dimension table (~10 rows), partitioning adds overhead |
| `loan_warehouse.loan_accounts` | CDW_LN_ACCT | `origination_year` | Time-based queries are the primary access pattern for loans |
| `loan_warehouse.payments` | CDW_PMT_HIST | `payment_year` | Highest-volume table; year-based partitioning enables efficient time-range scans |

All tables include:
- `BIGINT GENERATED ALWAYS AS IDENTITY` surrogate keys
- `_ingested_at TIMESTAMP` — pipeline audit column
- `_source_system STRING` — source traceability
- Delta Lake auto-optimization enabled (`autoOptimize.optimizeWrite`, `autoOptimize.autoCompact`)

DDL scripts are in `databricks/ddl/` and numbered for execution order:
```
00_create_schema.sql
01_borrowers.sql
02_loan_products.sql
03_loan_accounts.sql
04_payments.sql
```

---

## 4. Column Mappings

### CDW_BORR_MSTR → borrowers

| Legacy Column | Target Column | Type Change | Notes |
|--------------|--------------|-------------|-------|
| BORR_ID | external_id | VARCHAR → STRING | Preserved as-is (e.g., B-10001) |
| BORR_FST_NM | first_name | VARCHAR → STRING | Trimmed |
| BORR_LST_NM | last_name | VARCHAR → STRING | Trimmed |
| BORR_MID_INIT | middle_initial | VARCHAR → STRING | Nullable |
| BORR_SSN_ENCR | ssn_hash | VARCHAR → STRING | Re-encryption recommended post-migration |
| BORR_DOB_DT | date_of_birth | VARCHAR → DATE | Parsed from MM/DD/YYYY |
| BORR_ADDR_LN1 | address_line1 | VARCHAR → STRING | Trimmed |
| BORR_ADDR_LN2 | address_line2 | VARCHAR → STRING | Nullable |
| BORR_CTY_NM | city | VARCHAR → STRING | Trimmed |
| BORR_ST_CD | state | VARCHAR → STRING | Uppercased |
| BORR_ZIP_CD | zip_code | VARCHAR → STRING | Kept as string (leading zeros) |
| BORR_PH_NBR | phone | VARCHAR → STRING | Trimmed |
| BORR_EMAIL_ADDR | email | VARCHAR → STRING | Lowercased |
| BORR_CRDT_SCR | credit_score | VARCHAR → INT | Parsed, validated 300–850 |
| BORR_EMP_STAT | employment_status | VARCHAR → STRING | Trimmed |
| BORR_ANN_INCM | annual_income | VARCHAR → DECIMAL(12,2) | Comma-stripped |
| BORR_STAT_CD | status | VARCHAR → STRING | Expanded: ACT→ACTIVE, INA→INACTIVE |
| BORR_CRET_DT | created_at | VARCHAR → TIMESTAMP | Parsed from MM/DD/YYYY |
| BORR_UPDT_DT | updated_at | VARCHAR → TIMESTAMP | Parsed from MM/DD/YYYY |
| BORR_REC_TYP | *(dropped)* | — | Internal CDW metadata, not needed |

### CDW_LN_PROD → loan_products

| Legacy Column | Target Column | Type Change | Notes |
|--------------|--------------|-------------|-------|
| PROD_CD | code | VARCHAR → STRING | Primary business key |
| PROD_DESC_TXT | name | VARCHAR → STRING | Trimmed |
| PROD_TYP_CD | type | VARCHAR → STRING | Uppercased (FXD, ARM, FHA, VA) |
| PROD_TERM_MOS | term_months | VARCHAR → INT | Parsed |
| PROD_RT_TYP | rate_type | VARCHAR → STRING | Uppercased (FIXED, VARIABLE) |
| PROD_MIN_AMT | min_amount | VARCHAR → DECIMAL(12,2) | Comma-stripped |
| PROD_MAX_AMT | max_amount | VARCHAR → DECIMAL(12,2) | Comma-stripped |
| PROD_STAT_CD | is_active | VARCHAR → BOOLEAN | ACT→true, INA→false |
| PROD_EFF_DT | effective_date | VARCHAR → DATE | Parsed from MM/DD/YYYY |
| PROD_EXP_DT | expiration_date | VARCHAR → DATE | Parsed from MM/DD/YYYY |

### CDW_LN_ACCT → loan_accounts

| Legacy Column | Target Column | Type Change | Notes |
|--------------|--------------|-------------|-------|
| LN_ACCT_NBR | account_number | VARCHAR → STRING | Business key |
| BORR_ID | borrower_id | VARCHAR → BIGINT FK | Resolved via join to borrowers.external_id |
| PROD_CD | product_id | VARCHAR → BIGINT FK | Resolved via join to loan_products.code |
| LN_ORIG_AMT | original_amount | VARCHAR → DECIMAL(12,2) | Comma-stripped |
| LN_CURR_BAL | current_balance | VARCHAR → DECIMAL(12,2) | Comma-stripped |
| LN_INT_RT | interest_rate | VARCHAR → DECIMAL(5,3) | Direct cast |
| LN_TERM_MOS | term_months | VARCHAR → INT | Parsed |
| LN_PMT_AMT | monthly_payment | VARCHAR → DECIMAL(10,2) | Comma-stripped |
| LN_ORIG_DT | origination_date | VARCHAR → DATE | Parsed from MM/DD/YYYY |
| LN_MAT_DT | maturity_date | VARCHAR → DATE | Parsed from MM/DD/YYYY |
| LN_1ST_PMT_DT | first_payment_date | VARCHAR → DATE | Parsed from MM/DD/YYYY |
| LN_NXT_PMT_DT | next_payment_date | VARCHAR → DATE | Parsed from MM/DD/YYYY |
| LN_STAT_CD | status | VARCHAR → STRING | Expanded (see §6) |
| LN_DLQ_DAYS | delinquency_days | VARCHAR → INT | Default 0 if null |
| LN_ESCROW_BAL | escrow_balance | VARCHAR → DECIMAL(10,2) | Default 0.00 if null |
| LN_LTV_PCT | ltv_percent | VARCHAR → DECIMAL(5,2) | Direct cast |
| PROP_ADDR_LN1 | property_address | VARCHAR → STRING | Trimmed |
| PROP_CTY_NM | property_city | VARCHAR → STRING | Trimmed |
| PROP_ST_CD | property_state | VARCHAR → STRING | Uppercased |
| PROP_ZIP_CD | property_zip | VARCHAR → STRING | Kept as string |
| PROP_TYP_CD | property_type | VARCHAR → STRING | Expanded (see §6) |
| PROP_APRS_VAL | appraised_value | VARCHAR → DECIMAL(12,2) | Comma-stripped |
| LN_CRET_DT | created_at | VARCHAR → TIMESTAMP | Parsed from MM/DD/YYYY |
| LN_UPDT_DT | updated_at | VARCHAR → TIMESTAMP | Parsed from MM/DD/YYYY |
| *(derived)* | origination_year | — → INT | `YEAR(origination_date)`, partition key |
| BORR_FST_NM | *(dropped)* | — | Denormalized; use borrower FK instead |
| BORR_LST_NM | *(dropped)* | — | Denormalized; use borrower FK instead |
| BORR_SSN_LST4 | *(dropped)* | — | Sensitive; available via borrower FK |

### CDW_PMT_HIST → payments

| Legacy Column | Target Column | Type Change | Notes |
|--------------|--------------|-------------|-------|
| PMT_SEQ_NBR | legacy_sequence_nbr | VARCHAR → STRING | Preserved for traceability |
| LN_ACCT_NBR | loan_account_id | VARCHAR → BIGINT FK | Resolved via join to loan_accounts.account_number |
| PMT_DT | payment_date | VARCHAR → DATE | Parsed from MM/DD/YYYY |
| PMT_AMT | total_amount | VARCHAR → DECIMAL(10,2) | Comma-stripped |
| PMT_PRIN_AMT | principal_amount | VARCHAR → DECIMAL(10,2) | Comma-stripped |
| PMT_INT_AMT | interest_amount | VARCHAR → DECIMAL(10,2) | Comma-stripped |
| PMT_ESCROW_AMT | escrow_amount | VARCHAR → DECIMAL(10,2) | Default 0.00 if null |
| PMT_LATE_FEE | late_fee | VARCHAR → DECIMAL(10,2) | Default 0.00 if null |
| PMT_TYP_CD | type | VARCHAR → STRING | Expanded (see §6) |
| PMT_STAT_CD | status | VARCHAR → STRING | Expanded (see §6) |
| PMT_RECV_DT | received_date | VARCHAR → DATE | Parsed from MM/DD/YYYY |
| PMT_PROC_DT | processed_date | VARCHAR → DATE | Parsed from MM/DD/YYYY |
| PMT_CRET_DT | created_at | VARCHAR → TIMESTAMP | Parsed from MM/DD/YYYY |
| PMT_UPDT_DT | updated_at | VARCHAR → TIMESTAMP | Parsed from MM/DD/YYYY |
| *(derived)* | payment_year | — → INT | `YEAR(payment_date)`, partition key |

---

## 5. Type Conversion Decisions

| Conversion | Method | Null Handling | Example |
|-----------|--------|---------------|---------|
| Date (MM/DD/YYYY) | `to_date(col, "MM/dd/yyyy")` with fallback to `yyyy-MM-dd` and `M/d/yyyy` | Returns `null` for unparseable | `02/15/2019` → `2019-02-15` |
| Amount (comma-formatted) | Strip `$`, `,`, spaces → cast to `DECIMAL` | Returns `null` for unparseable | `285,000.00` → `285000.00` |
| Integer | `trim` → `cast(IntegerType())` | Returns `null` for unparseable | `360` → `360` |
| Decimal (rate) | `trim` → `cast(DecimalType(5,3))` | Returns `null` for unparseable | `4.750` → `4.750` |
| Status codes | Map lookup with `UNKNOWN` fallback | Never null — defaults to `UNKNOWN` | `ACT` → `ACTIVE` |
| Boolean (product status) | Map lookup with `false` fallback | Defaults to `false` | `ACT` → `true` |
| Timestamp | Parse date then cast to `TimestampType` (midnight) | Returns `null` for unparseable | `01/15/2019` → `2019-01-15T00:00:00` |

**Why not `inferSchema`?** The legacy data is all VARCHAR. Spark's schema inference would:
- Misparse comma-formatted numbers as strings
- Miss date format inconsistencies
- Not expand status codes
- Not handle the specific null representations in CDW (`null` literal strings)

All parsing is explicit via `common.py` utility functions.

---

## 6. Status Code Expansion

| Field | Code | Expanded Value |
|-------|------|---------------|
| Loan Status (`LN_STAT_CD`) | ACT | ACTIVE |
| | CLO | CLOSED |
| | DFT | DEFAULT |
| | FRB | FORBEARANCE |
| Borrower Status (`BORR_STAT_CD`) | ACT | ACTIVE |
| | INA | INACTIVE |
| Payment Type (`PMT_TYP_CD`) | REG | REGULAR |
| | EXT | EXTRA |
| | PRT | PARTIAL |
| | PRE | PREPAYMENT |
| Payment Status (`PMT_STAT_CD`) | PST | POSTED |
| | REV | REVERSED |
| | NSF | NSF |
| | PND | PENDING |
| Property Type (`PROP_TYP_CD`) | SFR | SINGLE_FAMILY |
| | CND | CONDOMINIUM |
| | MFR | MULTI_FAMILY |
| | TWN | TOWNHOUSE |
| Product Status (`PROD_STAT_CD`) | ACT | `true` (boolean) |
| | INA | `false` (boolean) |

Unmapped codes default to `UNKNOWN` (string fields) or `false` (boolean fields) and are logged as warnings during ingestion.

---

## 7. Partitioning Strategy

| Table | Partition Column | Rationale |
|-------|-----------------|-----------|
| `borrowers` | `status` | Low cardinality (2 values). Enables efficient filtering for active borrower queries, which represent 95%+ of access patterns. |
| `loan_products` | *(none)* | Catalog table with <20 rows. Partitioning would create more overhead than benefit. |
| `loan_accounts` | `origination_year` | Medium cardinality (~10 values for a decade of data). Most loan queries filter by vintage year or year range. Avoids over-partitioning by status (which changes over time). |
| `payments` | `payment_year` | Highest-volume table. Year partitioning provides good balance between partition count and per-partition size. Payment queries almost always include a date range filter. |

**Why not partition by month?** With the current data volumes, monthly partitions would create
too many small files. Year partitioning provides adequate pruning while keeping partition sizes
healthy for Delta Lake's optimization features.

---

## 8. Data Quality Considerations

The following known anomalies exist in the legacy CDW data and are handled during ingestion:

| # | Anomaly | Severity | Handling |
|---|---------|----------|----------|
| 1 | Payment component sum ≠ total (PMT-2025120001, PMT-2025110001) | Critical | Logged as warning, data preserved as-is for investigation |
| 2 | Active loan with 15 delinquency days (LN-2018-00089) | Critical | Logged as warning, both fields preserved |
| 3 | All-VARCHAR columns require parsing | High | Safe parsers return null on failure, never throw |
| 4 | Dates stored as MM/DD/YYYY strings | High | Multi-format parser with fallback chain |
| 5 | No FK constraints in CDW | High | FK resolution via joins; orphans logged, not dropped |
| 6 | Denormalized borrower data in loan table | Medium | Dropped from target; normalized via borrower FK |
| 7 | Null values in optional fields | Medium | Coalesced to sensible defaults (0 for amounts, null for optional strings) |
| 8 | Comma-formatted numbers | Medium | Regex strip before cast |

The data quality framework (`databricks/quality/data_quality_checks.py`) runs 26 automated
checks after ingestion covering row counts, null checks, referential integrity, business
rules, status code validity, and duplicate detection.

---

## 9. Execution Order

### Prerequisites
1. Databricks workspace with access to DBFS
2. Mount points configured:
   - `dbfs:/mnt/legacy-extracts/` — Landing zone for CDW extract files
   - `dbfs:/mnt/loan-warehouse/` — Delta Lake storage location
3. Legacy data extracted from CDW as CSV or Parquet files into the landing zone
4. Cluster with PySpark and Delta Lake support (Databricks Runtime 13.x+)

### Step-by-Step Execution

```
Step  Script                                    Depends On    Est. Time
────  ────────────────────────────────────────  ────────────  ─────────
 1    databricks/ddl/00_create_schema.sql       (none)        < 1s
 2    databricks/ddl/01_borrowers.sql           Step 1        < 1s
 3    databricks/ddl/02_loan_products.sql       Step 1        < 1s
 4    databricks/ddl/03_loan_accounts.sql       Step 1        < 1s
 5    databricks/ddl/04_payments.sql            Step 1        < 1s
 6    databricks/ingestion/ingest_borrowers.py  Step 2        ~2 min
 7    databricks/ingestion/ingest_loan_products.py  Step 3    ~1 min
 8    databricks/ingestion/ingest_loan_accounts.py  Steps 6,7 ~5 min
 9    databricks/ingestion/ingest_payments.py   Step 8        ~10 min
10    databricks/quality/data_quality_checks.py Steps 6–9     ~3 min
```

**Alternatively**, use the orchestrator script which handles the dependency order:
```python
# Runs steps 6-9 in order
%run databricks/ingestion/run_full_pipeline
```

### Notebook Setup (Databricks)

Create a Databricks workflow with the following task dependencies:

```
[Create Schema] → [DDL: borrowers] ──→ [Ingest: borrowers] ──────────→┐
                → [DDL: products]  ──→ [Ingest: products]  ──────────→├→ [Ingest: loans] → [Ingest: payments] → [Quality Checks]
                → [DDL: loans]     ──────────────────────────────────→┘
                → [DDL: payments]  ──────────────────────────────────────────────────────→┘
```

---

## 10. Rollback Procedure

Delta Lake's time travel feature enables safe rollback:

```sql
-- View table history
DESCRIBE HISTORY loan_warehouse.loan_accounts;

-- Rollback to a specific version
RESTORE TABLE loan_warehouse.loan_accounts TO VERSION AS OF <version_number>;

-- Rollback to a specific timestamp
RESTORE TABLE loan_warehouse.payments TO TIMESTAMP AS OF '2026-01-15T00:00:00';
```

For a full rollback of the entire migration:
```sql
DROP TABLE IF EXISTS loan_warehouse.payments;
DROP TABLE IF EXISTS loan_warehouse.loan_accounts;
DROP TABLE IF EXISTS loan_warehouse.loan_products;
DROP TABLE IF EXISTS loan_warehouse.borrowers;
DROP DATABASE IF EXISTS loan_warehouse;
```

---

## 11. Post-Migration Validation

After running the quality checks, manually verify:

1. **Row counts** match the legacy CDW source extraction report
2. **Spot-check 5 records** per table by comparing the Delta table values against the raw CDW data
3. **Run downstream reports** that previously read from CDW and compare outputs
4. **Verify date formatting** — all dates should be ISO-8601 (YYYY-MM-DD), not MM/DD/YYYY
5. **Verify status expansion** — no 3-letter abbreviations should remain in status columns
6. **Check partition sizes** — `DESCRIBE DETAIL loan_warehouse.payments` should show reasonable file sizes

### Sign-Off Checklist

- [ ] All DDL scripts executed without error
- [ ] All ingestion scripts completed with zero failures
- [ ] Data quality report shows 0 FAIL results (or all failures are acknowledged known issues)
- [ ] Row count reconciliation passes for all 4 tables
- [ ] No orphaned records (all FK joins resolved)
- [ ] Sample data spot-check completed
- [ ] Downstream report parity confirmed
- [ ] Rollback procedure tested in staging
- [ ] Production migration window scheduled
