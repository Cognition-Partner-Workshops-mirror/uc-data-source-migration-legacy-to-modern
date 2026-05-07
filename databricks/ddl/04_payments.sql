-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Corporate Data Warehouse)
-- =============================================================================
-- Payment transaction fact table.
-- Partitioned by payment_year (derived from payment_date) to support
-- time-range queries typical of payment history reporting.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_nbr STRING          COMMENT 'Legacy PMT_SEQ_NBR — preserved for audit trail',
    loan_account_id     BIGINT          NOT NULL COMMENT 'FK → loan_accounts.loan_account_id (resolved from LN_ACCT_NBR)',
    payment_date        DATE            NOT NULL COMMENT 'Legacy PMT_DT — parsed from MM/DD/YYYY',
    total_amount        DECIMAL(10, 2)  NOT NULL COMMENT 'Legacy PMT_AMT — parsed, commas removed',
    principal_amount    DECIMAL(10, 2)  COMMENT 'Legacy PMT_PRIN_AMT — parsed, commas removed',
    interest_amount     DECIMAL(10, 2)  COMMENT 'Legacy PMT_INT_AMT — parsed, commas removed',
    escrow_amount       DECIMAL(10, 2)  COMMENT 'Legacy PMT_ESCROW_AMT — parsed, commas removed',
    late_fee            DECIMAL(10, 2)  DEFAULT 0 COMMENT 'Legacy PMT_LATE_FEE — parsed, commas removed',
    type                STRING          NOT NULL COMMENT 'Legacy PMT_TYP_CD expanded: REG→Regular, EXT→Extra, PRT→Partial, PRE→Prepayment',
    status              STRING          NOT NULL COMMENT 'Legacy PMT_STAT_CD expanded: PST→Posted, REV→Reversed, NSF→NSF, PND→Pending',
    received_date       DATE            COMMENT 'Legacy PMT_RECV_DT — parsed from MM/DD/YYYY',
    processed_date      DATE            COMMENT 'Legacy PMT_PROC_DT — parsed from MM/DD/YYYY',
    payment_year        INT             COMMENT 'Derived from payment_date for partitioning',
    created_at          TIMESTAMP       COMMENT 'Legacy PMT_CRET_DT — parsed from MM/DD/YYYY',
    updated_at          TIMESTAMP       COMMENT 'Legacy PMT_UPDT_DT — parsed from MM/DD/YYYY',
    _migration_source   STRING          DEFAULT 'CDW_PMT_HIST' COMMENT 'Lineage: source table',
    _migration_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Lineage: ingestion timestamp',

    CONSTRAINT payments_pk PRIMARY KEY (payment_id),
    CONSTRAINT payments_loan_fk FOREIGN KEY (loan_account_id) REFERENCES loan_warehouse.loan_accounts (loan_account_id)
)
USING DELTA
PARTITIONED BY (payment_year)
COMMENT 'Payment history fact table — migrated from CDW_PMT_HIST'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.enableChangeDataFeed'       = 'true'
);
