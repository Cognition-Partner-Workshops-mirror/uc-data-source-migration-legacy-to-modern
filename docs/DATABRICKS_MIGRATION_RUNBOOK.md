# Databricks Migration Runbook

## CDW Legacy Data Warehouse → Modern Delta Lake Schema

---

## 1. Overview

This runbook documents the migration of a legacy CDW (Corporate Data Warehouse) loan management system to a modern Delta Lake architecture on Databricks. The legacy system stores all data as VARCHAR columns with cryptic abbreviated names, no foreign keys, and embedded status code abbreviations.

### Source System Characteristics
- **All columns are VARCHAR** — no type enforcement at the database level
- **Cryptic column names** — abbreviated (e.g., `BORR_FST_NM`, `LN_CURR_BAL`, `PMT_ESCROW_AMT`)
- **Denormalized** — borrower data embedded directly in loan account records
- **No foreign keys** — referential integrity not enforced
- **Status codes** — abbreviated values (ACT, CLO, DFT, FRB)
- **Dates as strings** — stored in `MM/DD/YYYY` format
- **Amounts as strings** — stored with commas (e.g., "285,000")

### Target System
- **Databricks Unity Catalog** with Delta Lake tables
- **Proper data types** — DATE, DECIMAL, INT, TIMESTAMP, BOOLEAN
- **Normalized schema** — separate borrower dimension table
- **Foreign key constraints** — enforced relationships
- **Meaningful column names** — full descriptive names

---

## 2. Architecture

```
┌─────────────────────┐     ┌─────────────────────┐     ┌──────────────────┐
│   Legacy CDW        │     │   PySpark Pipeline   │     │  Delta Lake      │
│                     │     │                      │     │                  │
│ CDW_BORR_MSTR  ────────►  ingest_borrowers  ────────►  borrowers        │
│ CDW_LN_PROD    ────────►  ingest_loan_products ─────►  loan_products    │
│ CDW_LN_ACCT    ────────►  ingest_loan_accounts ─────►  loan_accounts    │
│ CDW_PMT_HIST   ────────►  ingest_payments  ─────────►  payments         │
│                     │     │                      │     │                  │
└─────────────────────┘     │  data_quality_checks │     └──────────────────┘
                            └─────────────────────┘
```

---

## 3. Column Mapping Reference

### CDW_BORR_MSTR → borrowers

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| BORR_ID | external_id | VARCHAR→STRING | Direct copy |
| BORR_FST_NM | first_name | VARCHAR→STRING | Direct copy |
| BORR_LST_NM | last_name | VARCHAR→STRING | Direct copy |
| BORR_MID_INIT | middle_initial | VARCHAR→STRING | Direct copy |
| BORR_SSN_ENCR | ssn_hash | VARCHAR→STRING | Direct copy |
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
| BORR_STAT_CD | status | VARCHAR→STRING | ACT→ACTIVE, INA→INACTIVE |
| BORR_REC_TYP | *(dropped)* | — | Not needed in modern schema |

### CDW_LN_PROD → loan_products

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| PROD_CD | code | VARCHAR→STRING | Direct copy |
| PROD_DESC_TXT | name | VARCHAR→STRING | Direct copy |
| PROD_TYP_CD | type | VARCHAR→STRING | Direct copy |
| PROD_TERM_MOS | term_months | VARCHAR→INT | Parse to integer |
| PROD_RT_TYP | rate_type | VARCHAR→STRING | Direct copy |
| PROD_MIN_AMT | min_amount | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| PROD_MAX_AMT | max_amount | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| PROD_STAT_CD | is_active | VARCHAR→BOOLEAN | ACT→true, INA→false |
| PROD_EFF_DT | effective_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| PROD_EXP_DT | expiration_date | VARCHAR→DATE | Parse MM/DD/YYYY |

### CDW_LN_ACCT → loan_accounts

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| LN_ACCT_NBR | account_number | VARCHAR→STRING | Direct copy |
| BORR_ID | borrower_id | VARCHAR→BIGINT | FK lookup to borrowers.id |
| BORR_FST_NM | *(dropped)* | — | Denormalized; use borrower FK |
| BORR_LST_NM | *(dropped)* | — | Denormalized; use borrower FK |
| BORR_SSN_LST4 | *(dropped)* | — | Denormalized; use borrower FK |
| PROD_CD | product_id | VARCHAR→BIGINT | FK lookup to loan_products.id |
| LN_ORIG_AMT | original_amount | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| LN_CURR_BAL | current_balance | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| LN_INT_RT | interest_rate | VARCHAR→DECIMAL(5,3) | Parse to decimal |
| LN_TERM_MOS | term_months | VARCHAR→INT | Parse to integer |
| LN_PMT_AMT | monthly_payment | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| LN_ORIG_DT | origination_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_MAT_DT | maturity_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_1ST_PMT_DT | first_payment_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_NXT_PMT_DT | next_payment_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| LN_STAT_CD | status | VARCHAR→STRING | ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE |
| LN_DLQ_DAYS | delinquency_days | VARCHAR→INT | Parse to integer |
| LN_ESCROW_BAL | escrow_balance | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| LN_LTV_PCT | ltv_percent | VARCHAR→DECIMAL(5,2) | Parse to decimal |
| PROP_ADDR_LN1 | property_address | VARCHAR→STRING | Direct copy |
| PROP_CTY_NM | property_city | VARCHAR→STRING | Direct copy |
| PROP_ST_CD | property_state | VARCHAR→STRING | Direct copy |
| PROP_ZIP_CD | property_zip | VARCHAR→STRING | Direct copy |
| PROP_TYP_CD | property_type | VARCHAR→STRING | SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse |
| PROP_APRS_VAL | appraised_value | VARCHAR→DECIMAL(12,2) | Remove commas, parse |
| LN_CRET_DT | created_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |
| LN_UPDT_DT | updated_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |

### CDW_PMT_HIST → payments

| Legacy Column | Modern Column | Type Change | Transformation |
|---------------|---------------|-------------|----------------|
| PMT_SEQ_NBR | legacy_sequence_id | VARCHAR→STRING | Preserved for audit trail |
| LN_ACCT_NBR | loan_account_id | VARCHAR→BIGINT | FK lookup to loan_accounts.id |
| PMT_DT | payment_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| PMT_AMT | total_amount | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_PRIN_AMT | principal_amount | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_INT_AMT | interest_amount | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_ESCROW_AMT | escrow_amount | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_LATE_FEE | late_fee | VARCHAR→DECIMAL(10,2) | Remove commas, parse |
| PMT_TYP_CD | type | VARCHAR→STRING | REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| PMT_STAT_CD | status | VARCHAR→STRING | PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| PMT_RECV_DT | received_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| PMT_PROC_DT | processed_date | VARCHAR→DATE | Parse MM/DD/YYYY |
| PMT_CRET_DT | created_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |
| PMT_UPDT_DT | updated_at | VARCHAR→TIMESTAMP | Parse MM/DD/YYYY |

---

## 4. Type Conversion Decisions

| Pattern | Legacy Storage | Modern Type | Rationale |
|---------|---------------|-------------|-----------|
| Date fields | VARCHAR "MM/DD/YYYY" | DATE | Enables date arithmetic, partitioning, and proper sorting |
| Audit timestamps | VARCHAR "MM/DD/YYYY" | TIMESTAMP | Timestamps allow time-of-day precision for future use |
| Monetary amounts | VARCHAR with commas | DECIMAL(12,2) | Exact decimal arithmetic; avoids floating-point errors |
| Interest rates | VARCHAR "5.250" | DECIMAL(5,3) | Supports rates up to 99.999% with 3 decimal precision |
| LTV percentage | VARCHAR "82.5" | DECIMAL(5,2) | Supports percentages up to 999.99% |
| Term in months | VARCHAR "360" | INT | Integer arithmetic for term calculations |
| Credit scores | VARCHAR "745" | INT | Integer range 300-850 |
| Status codes | VARCHAR abbreviations | STRING (expanded) | Human-readable values improve query clarity |
| Product active flag | VARCHAR "ACT"/"INA" | BOOLEAN | Semantic clarity; efficient filtering |
| Surrogate keys | N/A (string IDs) | BIGINT IDENTITY | Auto-generated, performant joins |

---

## 5. Partitioning Strategy

| Table | Partition Column | Rationale |
|-------|-----------------|-----------|
| borrowers | `state` | Geographic queries are common in loan servicing; even distribution across ~50 states |
| loan_products | *(none)* | Small reference table (<100 rows); partitioning would add overhead |
| loan_accounts | `status` | Most queries filter by loan status (ACTIVE, CLOSED, etc.); enables partition pruning |
| payments | `status` | Separates POSTED from PENDING/REVERSED; most analytics focus on posted payments |

**Alternative considered:** Partitioning loan_accounts by `origination_year` (extracted from origination_date) for time-series analysis. This is viable for very large portfolios but adds complexity. The `status` partition was chosen because operational queries (servicing, collections) almost always filter by status first.

---

## 6. Execution Order

The pipeline must be executed in dependency order to ensure FK resolution works correctly:

```
Step 1: Run DDL scripts (00_schema.sql → 01 → 02 → 03 → 04)
Step 2: Ingest borrowers      (no dependencies)
Step 3: Ingest loan_products  (no dependencies)
Step 4: Ingest loan_accounts  (depends on borrowers + loan_products)
Step 5: Ingest payments       (depends on loan_accounts)
Step 6: Run data quality checks
```

### Databricks Execution Commands

```bash
# Step 1: Create schema and tables
# Run each DDL file in the Databricks SQL editor or via notebook:
#   databricks/ddl/00_schema.sql
#   databricks/ddl/01_borrowers.sql
#   databricks/ddl/02_loan_products.sql
#   databricks/ddl/03_loan_accounts.sql
#   databricks/ddl/04_payments.sql

# Step 2-5: Run the full ingestion pipeline
spark-submit --master local[*] databricks/ingestion/run_pipeline.py /path/to/source/files/

# Step 6: Run data quality validation
spark-submit --master local[*] databricks/quality/data_quality_checks.py \
  '{"borrowers": 5, "loan_products": 5, "loan_accounts": 5, "payments": 10}' \
  DATA_QUALITY_REPORT.md
```

---

## 7. Transformation Decisions

### 7.1 Denormalization Removal
The legacy `CDW_LN_ACCT` table embeds borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) directly in loan records. In the modern schema, these are dropped in favor of a `borrower_id` foreign key pointing to the `borrowers` dimension table. This:
- Eliminates data duplication and inconsistency
- Enables single-point updates to borrower information
- Reduces storage footprint

### 7.2 Status Code Expansion
Legacy status codes are 2-4 character abbreviations. The modern schema uses full descriptive strings for query readability:
- **Loan status:** ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE
- **Borrower status:** ACT→ACTIVE, INA→INACTIVE
- **Payment type:** REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT
- **Payment status:** PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING
- **Property type:** SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse
- **Product status:** ACT→true (boolean), INA→false (boolean)

### 7.3 Date Parsing
All legacy dates are stored as `MM/DD/YYYY` strings. The pipeline uses Spark's `to_date()` with format `MM/dd/yyyy`. Records with unparseable dates will have NULL in the target column and will be flagged by the quality framework.

### 7.4 Amount Parsing
Amounts are stored as comma-formatted strings (e.g., "285,000" or "1,487.02"). The pipeline:
1. Removes commas via `regexp_replace`
2. Casts to `DecimalType` with appropriate precision/scale
3. Logs any records where parsing fails (returns NULL)

### 7.5 Surrogate Keys
Legacy tables use string-based primary keys (e.g., "B-10001", "LN-2019-00142"). The modern schema uses auto-generated BIGINT identity columns. Legacy IDs are preserved in `external_id` or `legacy_sequence_id` columns for audit trail and cross-referencing during parallel operation.

### 7.6 Error Handling
The pipeline follows a "log and continue" approach:
- Malformed values produce NULL after type casting (Spark's default behavior)
- Records are never silently dropped
- Source vs. target row counts are validated
- NULL counts on required fields are logged as warnings
- The data quality framework catches issues post-ingestion

---

## 8. Data Quality Checks

The quality framework (`databricks/quality/data_quality_checks.py`) validates:

| Category | Checks |
|----------|--------|
| Row Count Reconciliation | Source count matches target count for each table |
| Null Checks | Required fields have no NULL values |
| Referential Integrity | loan_accounts→borrowers, loan_accounts→loan_products, payments→loan_accounts |
| Business Rules | Active loan balance > 0, valid interest rates, positive payments, valid date ranges, credit score range, LTV range, delinquency consistency |

The framework generates `DATA_QUALITY_REPORT.md` with pass/fail status for each check.

---

## 9. Rollback Procedure

If the migration produces unexpected results:

1. **Delta Lake Time Travel** — Revert any table to its previous state:
   ```sql
   RESTORE TABLE loan_management.loan_accounts TO VERSION AS OF 0;
   ```

2. **Drop and recreate** — For full reset:
   ```sql
   DROP TABLE IF EXISTS loan_management.payments;
   DROP TABLE IF EXISTS loan_management.loan_accounts;
   DROP TABLE IF EXISTS loan_management.loan_products;
   DROP TABLE IF EXISTS loan_management.borrowers;
   ```
   Then re-run DDL and ingestion.

---

## 10. Post-Migration Validation Checklist

- [ ] All DDL scripts executed without errors
- [ ] Row counts match between source and target for all 4 tables
- [ ] Data quality report shows PASSED or PASSED WITH WARNINGS
- [ ] Sample spot-check: verify 5+ records manually across tables
- [ ] FK integrity confirmed (no orphan records)
- [ ] Date columns contain valid dates (no NULLs from parse failures)
- [ ] Amount columns have correct precision (compare source amounts)
- [ ] Status codes expanded correctly (no raw abbreviations in target)
- [ ] Downstream consumers tested against new schema
- [ ] Audit trail: legacy IDs preserved and traceable
