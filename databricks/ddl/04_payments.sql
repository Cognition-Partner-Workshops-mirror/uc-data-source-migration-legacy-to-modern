-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Payment History)
-- =============================================================================
-- Payment fact table with FK to loan_accounts.
-- Partitioned by payment year/month for time-series query optimization.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,
    legacy_payment_id   STRING COMMENT 'Original PMT_SEQ_NBR for traceability',
    loan_account_id     BIGINT NOT NULL COMMENT 'FK to loan_accounts.id resolved from LN_ACCT_NBR',
    payment_date        DATE NOT NULL COMMENT 'Parsed from MM/DD/YYYY string',
    total_amount        DECIMAL(10, 2) NOT NULL COMMENT 'Parsed from comma-formatted string',
    principal_amount    DECIMAL(10, 2) COMMENT 'Parsed from comma-formatted string',
    interest_amount     DECIMAL(10, 2) COMMENT 'Parsed from comma-formatted string',
    escrow_amount       DECIMAL(10, 2) COMMENT 'Parsed from comma-formatted string',
    late_fee            DECIMAL(10, 2) DEFAULT 0 COMMENT 'Parsed from comma-formatted string',
    type                STRING NOT NULL COMMENT 'Expanded: REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT',
    status              STRING NOT NULL COMMENT 'Expanded: PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING',
    received_date       DATE COMMENT 'Parsed from MM/DD/YYYY string',
    processed_date      DATE COMMENT 'Parsed from MM/DD/YYYY string',
    payment_year        INT COMMENT 'Derived from payment_date for partitioning',
    payment_month       INT COMMENT 'Derived from payment_date for partitioning',
    created_at          TIMESTAMP COMMENT 'Parsed from MM/DD/YYYY string',
    updated_at          TIMESTAMP COMMENT 'Parsed from MM/DD/YYYY string',
    _migration_source   STRING DEFAULT 'CDW_PMT_HIST' COMMENT 'Lineage tracking',
    _migrated_at        TIMESTAMP DEFAULT current_timestamp() COMMENT 'Migration timestamp'
)
USING DELTA
PARTITIONED BY (payment_year, payment_month)
COMMENT 'Payment history migrated from legacy CDW_PMT_HIST'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'quality.constraints.amount_positive' = 'total_amount > 0',
    'quality.constraints.loan_account_not_null' = 'loan_account_id IS NOT NULL',
    'quality.constraints.payment_date_not_null' = 'payment_date IS NOT NULL'
);
