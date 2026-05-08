# CDW-to-Delta Lake Migration Pipeline — High Level Design

## Architecture Overview

This document describes the high-level architecture of the Databricks migration pipeline
that transforms loan data from a legacy CDW (Corporate Data Warehouse) with all-VARCHAR,
denormalized tables into a modern, strongly-typed Delta Lake schema on Databricks
Unity Catalog.

---

## High Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                            CDW-to-Delta Lake Migration Pipeline                                 │
│                                                                                                 │
│  ┌──────────────────────┐         ┌────────────────────────────────────────────────────────────┐ │
│  │   LEGACY SOURCE      │         │              DATABRICKS PLATFORM                           │ │
│  │   (CDW / H2 RDBMS)   │         │                                                            │ │
│  │                       │         │   ┌──────────────────────────────────────────────────────┐ │ │
│  │  CDW_BORR_MSTR       │         │   │             LANDING ZONE (/mnt/landing)              │ │ │
│  │  CDW_LN_PROD         │─Extract─│──▶│  cdw_borr_mstr.csv   cdw_ln_prod.csv                │ │ │
│  │  CDW_LN_ACCT         │  (CSV/  │   │  cdw_ln_acct.csv     cdw_pmt_hist.csv               │ │ │
│  │  CDW_PMT_HIST        │ Parquet)│   └────────────────┬─────────────────────────────────────┘ │ │
│  │                       │         │                    │                                       │ │
│  │  Characteristics:     │         │                    ▼                                       │ │
│  │  • All VARCHAR cols   │         │   ┌──────────────────────────────────────────────────────┐ │ │
│  │  • String dates       │         │   │        PYSPARK INGESTION ENGINE                      │ │ │
│  │  • Comma amounts      │         │   │        (databricks/ingestion/)                       │ │ │
│  │  • Cryptic col names  │         │   │                                                      │ │ │
│  │  • Denormalized       │         │   │  ┌─────────────────┐  ┌───────────────────────────┐  │ │ │
│  │  • No FK constraints  │         │   │  │  utils.py        │  │  run_full_pipeline.py     │  │ │ │
│  └──────────────────────┘         │   │  │  (Shared         │  │  (Orchestrator — runs     │  │ │ │
│                                    │   │  │   transforms)    │  │   steps in dependency     │  │ │ │
│                                    │   │  └─────────────────┘  │   order)                   │  │ │ │
│                                    │   │                        └───────────┬───────────────┘  │ │ │
│                                    │   │                                    │                   │ │ │
│                                    │   │  Step 1─2 (Dimensions, parallel):  │                   │ │ │
│                                    │   │  ┌──────────────────┐ ┌──────────────────────────┐    │ │ │
│                                    │   │  │ingest_borrowers  │ │ingest_loan_products      │    │ │ │
│                                    │   │  │.py               │ │.py                       │    │ │ │
│                                    │   │  │                  │ │                          │    │ │ │
│                                    │   │  │ Read → Transform │ │ Read → Transform         │    │ │ │
│                                    │   │  │ → Write Delta    │ │ → Write Delta            │    │ │ │
│                                    │   │  └────────┬─────────┘ └────────────┬─────────────┘    │ │ │
│                                    │   │           │                        │                   │ │ │
│                                    │   │           └──────────┬─────────────┘                   │ │ │
│                                    │   │                      ▼                                 │ │ │
│                                    │   │  Step 3 (Fact — depends on dimensions):                │ │ │
│                                    │   │  ┌──────────────────────────────────────────────┐      │ │ │
│                                    │   │  │ ingest_loan_accounts.py                      │      │ │ │
│                                    │   │  │ Read → Transform → FK Lookup (borrowers,     │      │ │ │
│                                    │   │  │         loan_products) → Write Delta          │      │ │ │
│                                    │   │  └───────────────────────┬──────────────────────┘      │ │ │
│                                    │   │                          ▼                             │ │ │
│                                    │   │  Step 4 (Fact — depends on loan_accounts):             │ │ │
│                                    │   │  ┌──────────────────────────────────────────────┐      │ │ │
│                                    │   │  │ ingest_payments.py                           │      │ │ │
│                                    │   │  │ Read → Transform → FK Lookup (loan_accounts) │      │ │ │
│                                    │   │  │ → Write Delta                                │      │ │ │
│                                    │   │  └──────────────────────────────────────────────┘      │ │ │
│                                    │   └──────────────────────────────────────────────────────┘ │ │
│                                    │                    │                                       │ │
│                                    │                    ▼                                       │ │
│                                    │   ┌──────────────────────────────────────────────────────┐ │ │
│                                    │   │   UNITY CATALOG — DELTA LAKE TARGET                  │ │ │
│                                    │   │   loan_catalog.loan_warehouse                        │ │ │
│                                    │   │                                                      │ │ │
│                                    │   │   ┌────────────────┐     ┌──────────────────────┐    │ │ │
│                                    │   │   │  borrowers     │     │  loan_products        │    │ │ │
│                                    │   │   │  (Dimension)   │     │  (Dimension)          │    │ │ │
│                                    │   │   │  Part: status  │     │  (No partitioning)    │    │ │ │
│                                    │   │   └───────┬────────┘     └──────────┬───────────┘    │ │ │
│                                    │   │           │    FK                   │  FK            │ │ │
│                                    │   │           ▼                         ▼                │ │ │
│                                    │   │   ┌──────────────────────────────────────────────┐   │ │ │
│                                    │   │   │             loan_accounts (Fact)              │   │ │ │
│                                    │   │   │             Part: origination_year            │   │ │ │
│                                    │   │   └───────────────────────┬──────────────────────┘   │ │ │
│                                    │   │                           │  FK                      │ │ │
│                                    │   │                           ▼                          │ │ │
│                                    │   │   ┌──────────────────────────────────────────────┐   │ │ │
│                                    │   │   │             payments (Fact)                   │   │ │ │
│                                    │   │   │             Part: payment_year                │   │ │ │
│                                    │   │   └──────────────────────────────────────────────┘   │ │ │
│                                    │   └──────────────────────────────────────────────────────┘ │ │
│                                    │                    │                                       │ │
│                                    │                    ▼                                       │ │
│                                    │   ┌──────────────────────────────────────────────────────┐ │ │
│                                    │   │  DATA QUALITY FRAMEWORK                              │ │ │
│                                    │   │  (databricks/quality/data_quality_checks.py)         │ │ │
│                                    │   │                                                      │ │ │
│                                    │   │  • Row Count Reconciliation (source vs target)       │ │ │
│                                    │   │  • Null Checks on required fields                    │ │ │
│                                    │   │  • Referential Integrity validation                  │ │ │
│                                    │   │  • Business Rule checks                             │ │ │
│                                    │   │  • Generates DATA_QUALITY_REPORT.md                  │ │ │
│                                    │   └──────────────────────────────────────────────────────┘ │ │
│                                    │                    │                                       │ │
│                                    │                    ▼                                       │ │
│                                    │   ┌──────────────────────────────────────────────────────┐ │ │
│                                    │   │  AUTOMATED TEST SUITE                                │ │ │
│                                    │   │  (databricks/tests/test_migration_pipeline.py)       │ │ │
│                                    │   │                                                      │ │ │
│                                    │   │  10 test cases (TC-01 through TC-10) covering:       │ │ │
│                                    │   │  status expansion, date/amount parsing, FK           │ │ │
│                                    │   │  resolution, row count preservation                  │ │ │
│                                    │   └──────────────────────────────────────────────────────┘ │ │
│                                    └────────────────────────────────────────────────────────────┘ │
│                                                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────────────────────┐    │
│  │  SPRING BOOT LOAN SERVICE (src/)                                                        │    │
│  │  Java 17 / Spring Boot 3.2 / Spring Data JPA / H2                                      │    │
│  │                                                                                          │    │
│  │  REST Controllers: /api/loans, /api/borrowers                                            │    │
│  │  Legacy Entities: LegacyBorrower, LegacyLoanAccount, LegacyLoanProduct, LegacyPayment   │    │
│  │  DTOs: LoanSummaryDto, BorrowerDto, PaymentDto                                          │    │
│  │  (Serves as the source application whose data is being migrated to Databricks)           │    │
│  └──────────────────────────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Pipeline Data Flow Diagram

```
                      ┌───────────────┐
                      │  CDW Legacy   │
                      │  H2 / RDBMS   │
                      └───────┬───────┘
                              │
                         CSV / Parquet
                          extraction
                              │
                              ▼
                 ┌────────────────────────┐
                 │     Landing Zone       │
                 │   /mnt/landing/*.csv   │
                 └───────────┬────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              (wait)
     ┌─────────────┐ ┌─────────────┐        │
     │  Borrowers  │ │   Products  │        │
     │  Ingestion  │ │  Ingestion  │        │
     └──────┬──────┘ └──────┬──────┘        │
            │               │               │
            ▼               ▼               │
     ┌─────────────┐ ┌─────────────┐        │
     │  borrowers  │ │loan_products│        │
     │(Delta Table)│ │(Delta Table)│        │
     └──────┬──────┘ └──────┬──────┘        │
            │               │               │
            └───────┬───────┘               │
                    ▼                       │
          ┌──────────────────┐              │
          │   Loan Accounts  │◄─────────────┘
          │    Ingestion     │
          │  (FK Lookups:    │
          │   borrower_id,   │
          │   product_id)    │
          └────────┬─────────┘
                   │
                   ▼
          ┌──────────────────┐
          │  loan_accounts   │
          │  (Delta Table)   │
          └────────┬─────────┘
                   │
                   ▼
          ┌──────────────────┐
          │    Payments      │
          │    Ingestion     │
          │  (FK Lookup:     │
          │   loan_account_  │
          │   id)            │
          └────────┬─────────┘
                   │
                   ▼
          ┌──────────────────┐
          │    payments      │
          │  (Delta Table)   │
          └────────┬─────────┘
                   │
                   ▼
          ┌──────────────────┐
          │  Data Quality    │
          │  Checks          │
          │  (13 validation  │
          │   rules)         │
          └────────┬─────────┘
                   │
                   ▼
          ┌──────────────────┐
          │ Quality Report   │
          │ (.md output)     │
          └──────────────────┘
```

---

## Component Descriptions

### 1. Legacy Source System (CDW / H2 RDBMS)

The origin of all loan data. The CDW (Corporate Data Warehouse) stores borrower,
loan product, loan account, and payment records in four denormalized tables with
all-VARCHAR column types, cryptic abbreviated column names (e.g., `BORR_FST_NM`),
comma-formatted amount strings, and `MM/DD/YYYY` date strings. This system has no
foreign key constraints and duplicates borrower information inside loan records.

**Tables:**
| Legacy Table     | Description                  | Seed Rows |
|------------------|------------------------------|-----------|
| `CDW_BORR_MSTR`  | Borrower master records      | 5         |
| `CDW_LN_PROD`    | Loan product definitions     | 5         |
| `CDW_LN_ACCT`    | Loan account details         | 5         |
| `CDW_PMT_HIST`   | Payment transaction history  | 10        |

---

### 2. Landing Zone (`/mnt/landing/`)

A staging area on DBFS (Databricks File System) or cloud storage where extracted
legacy data is deposited as flat files (CSV with headers, or Parquet) before
ingestion. Each legacy table maps to one file:

- `cdw_borr_mstr.csv` / `.parquet`
- `cdw_ln_prod.csv` / `.parquet`
- `cdw_ln_acct.csv` / `.parquet`
- `cdw_pmt_hist.csv` / `.parquet`

The pipeline reads these files using PySpark with `inferSchema=false` to treat
all columns as strings initially, then applies explicit type casting during
transformation.

---

### 3. PySpark Ingestion Engine (`databricks/ingestion/`)

The core transformation layer built on PySpark. Each ingestion module follows a
consistent **Read → Transform → Write** pattern:

| Module                      | Source → Target                | Key Transformations                                                               |
|-----------------------------|-------------------------------|-----------------------------------------------------------------------------------|
| `ingest_borrowers.py`       | `CDW_BORR_MSTR` → `borrowers`| Date parsing, amount parsing, status expansion (ACT→Active), credit score casting |
| `ingest_loan_products.py`   | `CDW_LN_PROD` → `loan_products`| Amount parsing, integer casting, status-to-boolean (ACT→true)                   |
| `ingest_loan_accounts.py`   | `CDW_LN_ACCT` → `loan_accounts`| FK resolution (borrower_id, product_id via left join), denormalized column drop, property type expansion, partition key derivation |
| `ingest_payments.py`        | `CDW_PMT_HIST` → `payments`   | FK resolution (loan_account_id via left join), payment type/status expansion, partition key derivation |

**Shared Utilities (`utils.py`):**
- `expand_status_with_fallback()` — Maps abbreviation codes to full labels; preserves unknown codes as-is
- `parse_date_expr()` / `parse_timestamp_expr()` — Converts `MM/DD/YYYY` strings to `DATE` / `TIMESTAMP`
- `parse_amount_expr()` — Strips commas from amount strings and casts to `DECIMAL`
- `parse_int_expr()` / `parse_rate_expr()` — Casts strings to `INT` or `DECIMAL(5,3)`
- `log_null_counts()` — Logs warnings for null values in specified columns after transformation

**Orchestrator (`run_full_pipeline.py`):**
Executes all ingestion steps in the correct dependency order with timing, logging,
and error handling. Dimension tables (borrowers, loan_products) are ingested first,
followed by fact tables (loan_accounts, then payments) which depend on dimension
tables for FK resolution.

---

### 4. DDL Layer (`databricks/ddl/`)

Databricks SQL scripts that create the target Unity Catalog schema and Delta Lake
tables. Executed before ingestion to prepare the target environment.

| Script                   | Purpose                                              |
|--------------------------|------------------------------------------------------|
| `00_create_schema.sql`   | Creates `loan_catalog` catalog and `loan_warehouse` schema |
| `01_borrowers.sql`       | Creates `borrowers` dimension table with IDENTITY PK, partitioned by `status` |
| `02_loan_products.sql`   | Creates `loan_products` dimension table with IDENTITY PK (no partitioning) |
| `03_loan_accounts.sql`   | Creates `loan_accounts` fact table with FK columns, partitioned by `origination_year` |
| `04_payments.sql`        | Creates `payments` fact table with FK column, partitioned by `payment_year` |

All tables use Delta format with `autoOptimize.optimizeWrite`, `autoOptimize.autoCompact`,
and `quality.tier = gold` properties for optimal performance and data governance.

---

### 5. Unity Catalog Delta Lake Target (`loan_catalog.loan_warehouse`)

The modern data warehouse destination. Tables use proper Spark SQL types, human-readable
column names, normalized relationships, and Delta Lake features (ACID transactions,
time travel, auto-optimization).

**Entity Relationship Model:**

```
┌──────────────────┐         ┌──────────────────────┐
│    borrowers     │         │    loan_products      │
│  (Dimension)     │         │    (Dimension)        │
│──────────────────│         │──────────────────────│
│ PK borrower_id   │         │ PK product_id         │
│    external_id   │         │    code               │
│    first_name    │         │    name               │
│    last_name     │         │    type               │
│    credit_score  │         │    term_months        │
│    annual_income │         │    is_active          │
│    status        │         │    min/max_amount     │
│    ...           │         │    ...                │
└────────┬─────────┘         └──────────┬───────────┘
         │ 1                            │ 1
         │                              │
         │ N                            │ N
┌────────┴──────────────────────────────┴───────────┐
│                  loan_accounts                     │
│                  (Fact)                             │
│───────────────────────────────────────────────────│
│ PK loan_account_id                                 │
│ FK borrower_id  ──────▶ borrowers.borrower_id      │
│ FK product_id   ──────▶ loan_products.product_id   │
│    account_number                                  │
│    original_amount / current_balance               │
│    interest_rate / term_months                     │
│    status / property_type                          │
│    origination_year (partition key)                │
│    ...                                             │
└─────────────────────────┬─────────────────────────┘
                          │ 1
                          │
                          │ N
┌─────────────────────────┴─────────────────────────┐
│                    payments                        │
│                    (Fact)                           │
│───────────────────────────────────────────────────│
│ PK payment_id                                      │
│ FK loan_account_id ──▶ loan_accounts.loan_account_id│
│    legacy_sequence_nbr                             │
│    total_amount / principal / interest / escrow    │
│    type / status                                   │
│    payment_year (partition key)                    │
│    ...                                             │
└───────────────────────────────────────────────────┘
```

**Partitioning Strategy:**
| Table            | Partition Column     | Rationale                                          |
|------------------|---------------------|----------------------------------------------------|
| `borrowers`      | `status`            | Low cardinality; most queries filter active/inactive|
| `loan_products`  | *(none)*            | Small reference table; partitioning would cause small-file overhead |
| `loan_accounts`  | `origination_year`  | Immutable time dimension; supports vintage/cohort analysis |
| `payments`       | `payment_year`      | High-volume table; year partitioning enables efficient time-range scans |

---

### 6. Data Quality Framework (`databricks/quality/`)

Post-ingestion validation engine that runs 13 automated checks across four
categories and generates a structured Markdown report.

| Category                | Checks Performed                                                                 | Severity |
|-------------------------|---------------------------------------------------------------------------------|----------|
| **Row Count**           | Source file count vs. Delta table count for all 4 tables                        | ERROR    |
| **Null Check**          | Required columns (`external_id`, `borrower_id`, `status`, etc.) have zero NULLs | ERROR    |
| **Referential Integrity** | `loan_accounts.borrower_id` → `borrowers`, `loan_accounts.product_id` → `loan_products`, `payments.loan_account_id` → `loan_accounts` | ERROR |
| **Business Rules**      | Active loan balance > 0, interest rate 0–100, maturity > origination, LTV 0–200, delinquency >= 0, valid status enums, payment component sum equals total | ERROR / WARNING |

The framework uses a `QualityReport` dataclass that collects `CheckResult` objects,
logs each check inline, and outputs a full Markdown report. A non-zero exit code
signals failures for CI/CD alerting.

---

### 7. Automated Test Suite (`databricks/tests/`)

Unit and integration tests for the migration pipeline logic, executed in a local
PySpark environment with Delta Lake support.

| Test Case | Description                                                      |
|-----------|------------------------------------------------------------------|
| TC-01     | Status code expansion — abbreviations map to full labels         |
| TC-02     | Date parsing — `MM/DD/YYYY` strings convert to `DateType`       |
| TC-03     | Amount parsing — comma-separated strings convert to `DecimalType`|
| TC-04     | Integer and rate parsing — string to `IntegerType` / `DecimalType`|
| TC-05     | Borrower transformation — full column mapping and type conversion|
| TC-06     | Loan product transformation — status-to-boolean mapping          |
| TC-07     | Loan account FK resolution — borrower_id and product_id lookup   |
| TC-08     | Payment transformation — FK resolution + type/status expansion   |
| TC-09     | Payment component sum — total = principal + interest + escrow + late_fee |
| TC-10     | Row count preservation — no records dropped during transformation|

---

### 8. Spring Boot Loan Service (`src/`)

The original Java application (Spring Boot 3.2, Java 17, Spring Data JPA, H2)
that reads from the legacy CDW tables and exposes REST API endpoints for loan and
borrower data. This service is the business context for the migration — its data
is being replicated to a modern Databricks warehouse for analytics, while the
application itself continues to serve real-time API requests.

**Key Components:**
- **Controllers:** `LoanController` (`/api/loans`), `BorrowerController` (`/api/borrowers`)
- **Service:** `LoanService` — business logic with legacy-to-clean type translations
- **Entities:** `LegacyBorrower`, `LegacyLoanAccount`, `LegacyLoanProduct`, `LegacyPayment`
- **DTOs:** `LoanSummaryDto`, `BorrowerDto`, `PaymentDto`
- **Repositories:** Spring Data JPA repositories for each legacy entity

---

## Execution Order Summary

The pipeline must run in strict dependency order because fact tables depend on
dimension tables for foreign key resolution.

```
Phase 1 — Schema Setup:
  00_create_schema.sql  →  01_borrowers.sql + 02_loan_products.sql  →  03_loan_accounts.sql + 04_payments.sql

Phase 2 — Dimension Ingestion (parallel):
  ingest_borrowers.py  ─┐
                        ├──▶  (both must complete before Phase 3)
  ingest_loan_products.py ─┘

Phase 3 — Fact Ingestion (sequential):
  ingest_loan_accounts.py  →  ingest_payments.py

Phase 4 — Validation:
  data_quality_checks.py  →  DATA_QUALITY_REPORT.md
```

**Recommended Databricks Workflow DAG:**
```
[create_schema] → [create_dim_tables] → [create_fact_tables]
                                               ↓
[ingest_borrowers] ──┐
                     ├→ [ingest_loan_accounts] → [ingest_payments] → [quality_checks]
[ingest_products] ───┘
```

---

## Key Design Decisions

| Decision                         | Description                                                                                   |
|----------------------------------|-----------------------------------------------------------------------------------------------|
| **No silent data drops**         | Unparseable values become NULL; rows are never discarded. Warnings are logged for review.     |
| **Left outer join for FK resolution** | Orphaned records (unresolved FKs) are retained with NULL FK values and flagged by quality checks. |
| **Overwrite mode by default**    | Pipeline is idempotent — safe to re-run without creating duplicates.                          |
| **Legacy ID preservation**       | Original IDs stored in `external_id` and `legacy_sequence_nbr` columns for traceability.     |
| **DECIMAL over DOUBLE**          | Financial amounts use `DECIMAL` to avoid floating-point precision issues.                     |
| **Status fallback**              | Unknown status codes are kept as-is (trimmed) rather than dropped or nullified.               |
| **Delta Lake features**          | Auto-optimize, auto-compact, and time travel for rollback support.                            |
| **_ingestion_ts metadata**       | Every record carries a pipeline execution timestamp for lineage tracking.                     |

---

## Technology Stack

| Layer              | Technology                                    |
|--------------------|-----------------------------------------------|
| Source Database     | H2 / Legacy RDBMS (CDW)                      |
| Source Application  | Java 17, Spring Boot 3.2, Spring Data JPA    |
| Pipeline Engine     | PySpark (Databricks Runtime)                  |
| Target Storage      | Delta Lake on Databricks Unity Catalog        |
| Table Format        | Delta (ACID, time travel, auto-optimization)  |
| Namespace           | `loan_catalog.loan_warehouse`                 |
| Quality Framework   | Custom PySpark-based checks with Markdown output |
| Test Framework      | Python unittest + PySpark local mode + delta-spark |
| Orchestration       | `run_full_pipeline.py` or Databricks Workflows|

---

## File Structure

```
uc-data-source-migration-legacy-to-modern/
├── databricks/
│   ├── ddl/                            # Delta Lake table DDL scripts
│   │   ├── 00_create_schema.sql        # Creates Unity Catalog + schema
│   │   ├── 01_borrowers.sql            # Borrower dimension table
│   │   ├── 02_loan_products.sql        # Loan product dimension table
│   │   ├── 03_loan_accounts.sql        # Loan account fact table
│   │   └── 04_payments.sql             # Payment fact table
│   ├── ingestion/                      # PySpark ingestion modules
│   │   ├── utils.py                    # Shared transformation utilities
│   │   ├── ingest_borrowers.py         # Borrower ingestion pipeline
│   │   ├── ingest_loan_products.py     # Loan product ingestion pipeline
│   │   ├── ingest_loan_accounts.py     # Loan account ingestion (with FK resolution)
│   │   ├── ingest_payments.py          # Payment ingestion (with FK resolution)
│   │   └── run_full_pipeline.py        # Pipeline orchestrator
│   ├── quality/                        # Post-ingestion validation
│   │   ├── data_quality_checks.py      # 13 automated quality checks
│   │   └── DATA_QUALITY_REPORT.md      # Report template (populated at runtime)
│   └── tests/                          # Pipeline unit/integration tests
│       └── test_migration_pipeline.py  # 10 test cases (TC-01 through TC-10)
├── data/
│   ├── legacy-schema/cdw_tables.sql    # Legacy CDW schema documentation
│   ├── modern-schema/modern_tables.sql # Target modern SQL schema
│   └── mappings/column_mappings.md     # Legacy-to-modern field mapping reference
├── docs/
│   ├── MIGRATION_TASKS.md              # Workshop task breakdown
│   ├── DATABRICKS_MIGRATION_RUNBOOK.md # Detailed migration runbook
│   └── HIGH_LEVEL_DIAGRAM.md           # This document
└── src/                                # Spring Boot loan service application
    └── main/java/com/workshop/loanservice/
        ├── controller/                 # REST API controllers
        ├── service/                    # Business logic layer
        ├── entity/                     # JPA entities (legacy schema)
        ├── dto/                        # Data transfer objects
        └── repository/                 # Spring Data JPA repositories
```
