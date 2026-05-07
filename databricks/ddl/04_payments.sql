-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (legacy)
-- =============================================================================
-- Payment transaction fact table. Partitioned by payment_year (derived from
-- payment_date) for time-series query performance and retention management.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_key         BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_id  STRING          COMMENT 'Legacy PMT_SEQ_NBR preserved for traceability',
    loan_account_key    BIGINT          NOT NULL COMMENT 'FK → loan_accounts.loan_account_key (resolved from LN_ACCT_NBR)',
    payment_date        DATE            NOT NULL COMMENT 'Parsed from PMT_DT (MM/DD/YYYY)',
    total_amount        DECIMAL(10, 2)  NOT NULL COMMENT 'Parsed from PMT_AMT (remove commas)',
    principal_amount    DECIMAL(10, 2)  COMMENT 'Parsed from PMT_PRIN_AMT (remove commas)',
    interest_amount     DECIMAL(10, 2)  COMMENT 'Parsed from PMT_INT_AMT (remove commas)',
    escrow_amount       DECIMAL(10, 2)  COMMENT 'Parsed from PMT_ESCROW_AMT (remove commas)',
    late_fee            DECIMAL(10, 2)  DEFAULT 0 COMMENT 'Parsed from PMT_LATE_FEE (remove commas)',
    type                STRING          NOT NULL COMMENT 'Expanded from PMT_TYP_CD: REG→Regular, EXT→Extra, PRT→Partial, PRE→Prepayment',
    status              STRING          NOT NULL COMMENT 'Expanded from PMT_STAT_CD: PST→Posted, REV→Reversed, NSF→NSF, PND→Pending',
    received_date       DATE            COMMENT 'Parsed from PMT_RECV_DT (MM/DD/YYYY)',
    processed_date      DATE            COMMENT 'Parsed from PMT_PROC_DT (MM/DD/YYYY)',
    created_at          TIMESTAMP       COMMENT 'Parsed from PMT_CRET_DT (MM/DD/YYYY)',
    updated_at          TIMESTAMP       COMMENT 'Parsed from PMT_UPDT_DT (MM/DD/YYYY)',
    payment_year        INT             NOT NULL COMMENT 'Derived from payment_date for partitioning',
    _migration_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Timestamp of migration load',
    _source_system      STRING          DEFAULT 'CDW_PMT_HIST' COMMENT 'Source table identifier',

    CONSTRAINT payments_pk PRIMARY KEY (payment_key),
    CONSTRAINT payments_loan_account_fk FOREIGN KEY (loan_account_key) REFERENCES loan_warehouse.loan_accounts (loan_account_key)
)
USING DELTA
PARTITIONED BY (payment_year)
COMMENT 'Payment transaction fact table — migrated from legacy CDW_PMT_HIST'
TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'true',
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
