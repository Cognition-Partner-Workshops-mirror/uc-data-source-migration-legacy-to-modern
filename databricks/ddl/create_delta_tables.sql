-- =============================================================================
-- DELTA LAKE TABLE DEFINITIONS — Modern Normalized Schema
-- =============================================================================
-- Target: Databricks Unity Catalog
-- Source: Legacy CDW tables (CDW_BORR_MSTR, CDW_LN_PROD, CDW_LN_ACCT, CDW_PMT_HIST)
-- Mappings: data/mappings/column_mappings.md
-- =============================================================================

-- -------------------------------------------------------------------------
-- 1. Borrowers (from CDW_BORR_MSTR)
-- -------------------------------------------------------------------------
-- No partitioning: small dimension table (~thousands of rows).
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    borrower_id         BIGINT          GENERATED ALWAYS AS IDENTITY,
    external_id         STRING          NOT NULL COMMENT 'Legacy BORR_ID (e.g. B-10001)',
    first_name          STRING          NOT NULL,
    last_name           STRING          NOT NULL,
    middle_initial      STRING,
    ssn_hash            STRING          NOT NULL COMMENT 'Encrypted SSN from legacy BORR_SSN_ENCR',
    date_of_birth       DATE            COMMENT 'Parsed from MM/DD/YYYY',
    address_line1       STRING,
    address_line2       STRING,
    city                STRING,
    state               STRING          COMMENT '2-letter state code',
    zip_code            STRING,
    phone               STRING,
    email               STRING,
    credit_score        INT             COMMENT 'Valid range 300-850',
    employment_status   STRING,
    annual_income       DECIMAL(12, 2)  COMMENT 'Parsed from comma-separated string',
    status              STRING          NOT NULL COMMENT 'Expanded: ACT→ACTIVE, INA→INACTIVE',
    created_at          TIMESTAMP       NOT NULL,
    updated_at          TIMESTAMP       NOT NULL,
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp',
    _source_system      STRING          DEFAULT 'CDW' COMMENT 'Source system identifier'
)
USING DELTA
COMMENT 'Normalized borrower dimension table migrated from CDW_BORR_MSTR'
TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'true',
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);

-- -------------------------------------------------------------------------
-- 2. Loan Products (from CDW_LN_PROD)
-- -------------------------------------------------------------------------
-- No partitioning: small reference table (~tens of rows).
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS loan_warehouse.loan_products (
    product_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    code                STRING          NOT NULL COMMENT 'Legacy PROD_CD (e.g. FXD30)',
    name                STRING          NOT NULL COMMENT 'Product description',
    type                STRING          NOT NULL COMMENT 'Product type code: FXD, ARM, FHA, VA',
    term_months         INT             NOT NULL COMMENT 'Parsed from string',
    rate_type           STRING          NOT NULL COMMENT 'FIXED or VARIABLE',
    min_amount          DECIMAL(12, 2)  NOT NULL COMMENT 'Parsed from comma-separated string',
    max_amount          DECIMAL(12, 2)  NOT NULL COMMENT 'Parsed from comma-separated string',
    is_active           BOOLEAN         NOT NULL COMMENT 'Derived: ACT→true, INA→false',
    effective_date      DATE            NOT NULL COMMENT 'Parsed from MM/DD/YYYY',
    expiration_date     DATE            COMMENT 'Parsed from MM/DD/YYYY; 12/31/2099 = no expiry',
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp(),
    _source_system      STRING          DEFAULT 'CDW'
)
USING DELTA
COMMENT 'Loan product reference table migrated from CDW_LN_PROD'
TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'true',
    'delta.autoOptimize.optimizeWrite' = 'true'
);

-- -------------------------------------------------------------------------
-- 3. Loan Accounts (from CDW_LN_ACCT)
-- -------------------------------------------------------------------------
-- Partitioned by status: Active loans are queried most frequently.
-- Denormalized borrower fields (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4)
-- are dropped; use borrower_id FK instead.
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_account_id     BIGINT          GENERATED ALWAYS AS IDENTITY,
    account_number      STRING          NOT NULL COMMENT 'Legacy LN_ACCT_NBR',
    borrower_id         BIGINT          NOT NULL COMMENT 'FK to borrowers.borrower_id',
    product_id          BIGINT          NOT NULL COMMENT 'FK to loan_products.product_id',
    original_amount     DECIMAL(12, 2)  NOT NULL COMMENT 'Parsed from comma-separated string',
    current_balance     DECIMAL(12, 2)  NOT NULL,
    interest_rate       DECIMAL(5, 3)   NOT NULL COMMENT 'e.g. 4.750',
    term_months         INT             NOT NULL,
    monthly_payment     DECIMAL(10, 2)  NOT NULL,
    origination_date    DATE            NOT NULL COMMENT 'Parsed from MM/DD/YYYY',
    maturity_date       DATE            NOT NULL,
    first_payment_date  DATE,
    next_payment_date   DATE,
    status              STRING          NOT NULL COMMENT 'Expanded: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE',
    delinquency_days    INT             DEFAULT 0,
    escrow_balance      DECIMAL(10, 2)  DEFAULT 0.00,
    ltv_percent         DECIMAL(5, 2)   COMMENT 'Loan-to-value ratio',
    property_address    STRING,
    property_city       STRING,
    property_state      STRING,
    property_zip        STRING,
    property_type       STRING          COMMENT 'Expanded: SFR→Single Family, CND→Condominium, etc.',
    appraised_value     DECIMAL(12, 2),
    created_at          TIMESTAMP       NOT NULL,
    updated_at          TIMESTAMP       NOT NULL,
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp(),
    _source_system      STRING          DEFAULT 'CDW'
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Normalized loan account fact table migrated from CDW_LN_ACCT. Partitioned by status for efficient queries on active/closed/default loans.'
TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'true',
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);

-- -------------------------------------------------------------------------
-- 4. Payments (from CDW_PMT_HIST)
-- -------------------------------------------------------------------------
-- Partitioned by payment year for efficient time-range queries.
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_nbr STRING          COMMENT 'Legacy PMT_SEQ_NBR for traceability',
    loan_account_id     BIGINT          NOT NULL COMMENT 'FK to loan_accounts.loan_account_id',
    payment_date        DATE            NOT NULL COMMENT 'Parsed from MM/DD/YYYY',
    total_amount        DECIMAL(10, 2)  NOT NULL,
    principal_amount    DECIMAL(10, 2)  NOT NULL,
    interest_amount     DECIMAL(10, 2)  NOT NULL,
    escrow_amount       DECIMAL(10, 2)  DEFAULT 0.00,
    late_fee            DECIMAL(10, 2)  DEFAULT 0.00,
    type                STRING          NOT NULL COMMENT 'Expanded: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT',
    status              STRING          NOT NULL COMMENT 'Expanded: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING',
    received_date       DATE,
    processed_date      DATE,
    created_at          TIMESTAMP       NOT NULL,
    updated_at          TIMESTAMP       NOT NULL,
    payment_year        INT             NOT NULL COMMENT 'Derived partition key: YEAR(payment_date)',
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp(),
    _source_system      STRING          DEFAULT 'CDW'
)
USING DELTA
PARTITIONED BY (payment_year)
COMMENT 'Payment history fact table migrated from CDW_PMT_HIST. Partitioned by year for efficient time-range queries.'
TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'true',
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);

-- -------------------------------------------------------------------------
-- 5. Data Quality Log
-- -------------------------------------------------------------------------
-- Tracks all anomalies detected during ingestion.
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS loan_warehouse.data_quality_log (
    log_id              BIGINT          GENERATED ALWAYS AS IDENTITY,
    run_id              STRING          NOT NULL COMMENT 'Unique pipeline run identifier',
    source_table        STRING          NOT NULL,
    source_record_id    STRING          NOT NULL,
    column_name         STRING,
    anomaly_type        STRING          NOT NULL COMMENT 'e.g. NULL_REQUIRED, PARSE_FAILURE, FK_VIOLATION, BUSINESS_RULE',
    severity            STRING          NOT NULL COMMENT 'CRITICAL, HIGH, MEDIUM, LOW',
    description         STRING          NOT NULL,
    original_value      STRING,
    corrected_value     STRING,
    detected_at         TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
PARTITIONED BY (source_table)
COMMENT 'Audit log of data quality anomalies detected during CDW migration ingestion'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true'
);

-- -------------------------------------------------------------------------
-- Schema Creation (run first)
-- -------------------------------------------------------------------------
-- CREATE SCHEMA IF NOT EXISTS loan_warehouse
-- COMMENT 'Modern normalized loan data warehouse migrated from legacy CDW';
