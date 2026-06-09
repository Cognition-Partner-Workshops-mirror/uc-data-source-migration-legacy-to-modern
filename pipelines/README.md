# Legacy CDW → Modern Data Platform Migration Pipelines

PySpark/Databricks data pipelines that transform the legacy Corporate Data Warehouse (CDW) tables into a normalized modern data platform using the **Medallion Architecture** (Bronze → Silver → Gold).

## Architecture

```
┌─────────────────────┐     ┌───────────────────────┐     ┌───────────────────────┐
│   BRONZE (Raw)      │     │   SILVER (Cleansed)   │     │   GOLD (Business)     │
│                     │     │                       │     │                       │
│ cdw_borr_mstr       │────▶│ borrowers             │────▶│ borrowers             │
│ cdw_ln_prod         │────▶│ loan_products         │────▶│ loan_products         │
│ cdw_ln_acct         │────▶│ loan_accounts         │────▶│ loan_accounts         │
│ cdw_pmt_hist        │────▶│ payments              │────▶│ payments              │
│                     │     │                       │     │                       │
│ • All VARCHAR       │     │ • Proper types        │     │ • Surrogate BIGINT PK │
│ • 1:1 raw copy      │     │ • Dates parsed        │     │ • FK resolved         │
│ • Metadata columns  │     │ • Amounts as DECIMAL  │     │ • Normalized          │
│                     │     │ • Status expanded     │     │ • Production-ready    │
│                     │     │ • Quality validated   │     │                       │
└─────────────────────┘     └───────────────────────┘     └───────────────────────┘
```

## Transformations

| Legacy Pattern | Modern Result | Method |
|---|---|---|
| `MM/DD/YYYY` VARCHAR | `DATE` / `TIMESTAMP` | `to_date()` with format pattern |
| `"285,000"` VARCHAR | `DECIMAL(12,2)` | Strip `$,` → cast |
| `"4.750"` VARCHAR | `DECIMAL(5,3)` | Direct cast |
| `ACT`, `CLO`, `DFT` | `ACTIVE`, `CLOSED`, `DEFAULT` | Status code expansion map |
| Denormalized borrower fields in loan table | FK to `borrowers.id` | Drop + join |
| No FK constraints | `FOREIGN KEY` references | Surrogate key assignment + lookup |

## Data Quality Checks

Quality checks run at the Silver layer boundary and catch all anomalies documented in `docs/DATA_ANOMALY_REPORT.md`:

| Check | Anomaly | Description |
|---|---|---|
| `check_null_required_fields` | ANO-008 | Null/blank values in NOT NULL columns |
| `check_date_parseable` | ANO-006 | Dates that don't match MM/dd/yyyy |
| `check_numeric_parseable` | ANO-005 | Values that can't be cast to numeric |
| `check_valid_status_codes` | ANO-004 | Unrecognized status codes |
| `check_credit_score_range` | — | Scores outside [300, 850] |
| `check_payment_reconciliation` | ANO-001 | Component sum ≠ total amount |
| `check_delinquency_status_consistency` | ANO-003 | Delinquent loan marked Active |
| `check_referential_integrity` | ANO-009 | Orphaned FK references |

## Project Structure

```
pipelines/
├── README.md                       # This file
├── requirements.txt                # Python dependencies (pyspark, pytest)
├── databricks_workflow.yml         # Databricks Workflow job definition
├── config/
│   ├── __init__.py
│   └── pipeline_config.py          # Catalog paths, status maps, thresholds
├── notebooks/
│   ├── 00_run_pipeline.py          # Orchestrator (runs all stages in order)
│   ├── 01_bronze_ingestion.py      # Raw ingestion from legacy CDW
│   ├── 02_silver_borrowers.py      # CDW_BORR_MSTR → silver.borrowers
│   ├── 03_silver_loan_products.py  # CDW_LN_PROD → silver.loan_products
│   ├── 04_silver_loan_accounts.py  # CDW_LN_ACCT → silver.loan_accounts
│   ├── 05_silver_payments.py       # CDW_PMT_HIST → silver.payments
│   └── 06_gold_final_tables.py     # FK resolution → gold.*
├── utils/
│   ├── __init__.py
│   ├── transformations.py          # Shared PySpark UDFs (dates, amounts, status)
│   └── data_quality.py             # Quality check functions
└── tests/
    ├── __init__.py
    ├── test_transformations.py     # Unit tests for transformation utils
    └── test_data_quality.py        # Unit tests for DQ checks
```

## Running Locally

```bash
# Install dependencies
pip install -r pipelines/requirements.txt

# Run tests
cd pipelines
pytest tests/ -v
```

## Running on Databricks

### Option 1: Orchestrator Notebook
Import `notebooks/00_run_pipeline.py` and run it — executes all stages sequentially.

### Option 2: Databricks Workflow
Deploy the workflow definition for parallel execution with dependency management:
```bash
# Using Databricks CLI / Asset Bundles
databricks bundle deploy
```

### Option 3: Individual Notebooks
Run each notebook independently for debugging or partial refreshes.

## Configuration

Edit `config/pipeline_config.py` to customize:
- **Catalog/schema names** — target Unity Catalog locations
- **JDBC connection** — legacy CDW source credentials (use Databricks secrets)
- **Status code mappings** — add new codes as business evolves
- **Quality thresholds** — tolerance for reconciliation, null percentages

## Key Design Decisions

1. **Medallion Architecture** — provides clear data lineage, allows reprocessing from bronze, and isolates quality issues to silver boundary.
2. **Quality checks don't block** — issues are logged and can be routed to a quarantine table, but the pipeline continues to avoid blocking downstream consumers on known legacy issues.
3. **Surrogate keys in Gold** — uses `monotonically_increasing_id()` for deterministic key assignment. In production, consider identity columns or UUIDs.
4. **Full refresh mode** — current implementation overwrites tables. For incremental loads, add change data capture (CDC) with Delta merge operations.
5. **FK resolution via joins** — silver layer keeps natural keys; gold layer resolves to integer FKs via lookup joins for referential integrity.
