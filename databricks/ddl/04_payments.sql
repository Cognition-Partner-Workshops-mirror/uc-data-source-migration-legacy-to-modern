-- =============================================================================
-- Delta Lake Table: payments
-- =============================================================================
-- Source: CDW_PMT_HIST (legacy payment history table)
-- Migration: All amount fields parsed from comma-formatted VARCHAR strings to
--            DECIMAL. Date strings converted to DATE/TIMESTAMP. Payment type
--            and status codes expanded to readable values.
-- Partitioning: By payment_date (year-month granularity via DATE column) —
--               payment queries are almost always time-bounded (monthly
--               statements, quarterly reviews, annual reporting).
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_nbr STRING                      COMMENT 'Carried from PMT_SEQ_NBR for audit trail / reconciliation',
    loan_account_id     BIGINT          NOT NULL    COMMENT 'FK to loan_accounts.id; resolved from LN_ACCT_NBR via account_number lookup',
    payment_date        DATE            NOT NULL    COMMENT 'Parsed from PMT_DT (MM/DD/YYYY string)',
    total_amount        DECIMAL(10, 2)  NOT NULL    COMMENT 'Parsed from PMT_AMT (comma-formatted string)',
    principal_amount    DECIMAL(10, 2)              COMMENT 'Parsed from PMT_PRIN_AMT (comma-formatted string)',
    interest_amount     DECIMAL(10, 2)              COMMENT 'Parsed from PMT_INT_AMT (comma-formatted string)',
    escrow_amount       DECIMAL(10, 2)              COMMENT 'Parsed from PMT_ESCROW_AMT (comma-formatted string)',
    late_fee            DECIMAL(10, 2)  DEFAULT 0   COMMENT 'Parsed from PMT_LATE_FEE (comma-formatted string)',
    type                STRING          NOT NULL    COMMENT 'Expanded from PMT_TYP_CD: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT',
    status              STRING          NOT NULL    COMMENT 'Expanded from PMT_STAT_CD: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING',
    received_date       DATE                        COMMENT 'Parsed from PMT_RECV_DT (MM/DD/YYYY string)',
    processed_date      DATE                        COMMENT 'Parsed from PMT_PROC_DT (MM/DD/YYYY string)',
    created_at          TIMESTAMP                   COMMENT 'Parsed from PMT_CRET_DT (MM/DD/YYYY string)',
    updated_at          TIMESTAMP                   COMMENT 'Parsed from PMT_UPDT_DT (MM/DD/YYYY string)',

    CONSTRAINT pk_payments PRIMARY KEY (id),
    CONSTRAINT fk_payments_loan_account FOREIGN KEY (loan_account_id) REFERENCES loan_warehouse.loan_accounts(id)
)
USING DELTA
PARTITIONED BY (payment_date)
COMMENT 'Payment history table migrated from legacy CDW_PMT_HIST with proper types and expanded status codes'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'quality'                          = 'gold'
);
