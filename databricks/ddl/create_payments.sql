-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (legacy)
-- =============================================================================
-- Payment history fact table. Partitioned by payment year (derived from
-- payment_date) to support time-range queries on large payment volumes.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_id          BIGINT        GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_nbr STRING        COMMENT 'Legacy PMT_SEQ_NBR preserved for audit trail',
    loan_account_id     BIGINT        NOT NULL COMMENT 'FK to loan_accounts — resolved from legacy LN_ACCT_NBR',
    payment_date        DATE          NOT NULL COMMENT 'Legacy PMT_DT — parsed from MM/DD/YYYY',
    total_amount        DECIMAL(10,2) NOT NULL COMMENT 'Legacy PMT_AMT — parsed from comma-formatted string',
    principal_amount    DECIMAL(10,2) COMMENT 'Legacy PMT_PRIN_AMT — parsed from comma-formatted string',
    interest_amount     DECIMAL(10,2) COMMENT 'Legacy PMT_INT_AMT — parsed from comma-formatted string',
    escrow_amount       DECIMAL(10,2) COMMENT 'Legacy PMT_ESCROW_AMT — parsed from comma-formatted string',
    late_fee            DECIMAL(10,2) DEFAULT 0 COMMENT 'Legacy PMT_LATE_FEE — parsed from comma-formatted string',
    type                STRING        NOT NULL COMMENT 'Legacy PMT_TYP_CD expanded: REG->Regular, EXT->Extra, PRT->Partial, PRE->Prepayment',
    status              STRING        NOT NULL COMMENT 'Legacy PMT_STAT_CD expanded: PST->Posted, REV->Reversed, NSF->NSF, PND->Pending',
    received_date       DATE          COMMENT 'Legacy PMT_RECV_DT — parsed from MM/DD/YYYY',
    processed_date      DATE          COMMENT 'Legacy PMT_PROC_DT — parsed from MM/DD/YYYY',
    created_at          TIMESTAMP     COMMENT 'Legacy PMT_CRET_DT — parsed from MM/DD/YYYY',
    updated_at          TIMESTAMP     COMMENT 'Legacy PMT_UPDT_DT — parsed from MM/DD/YYYY',
    payment_year        INT           COMMENT 'Derived partition column: year(payment_date)',
    _migration_ts       TIMESTAMP     DEFAULT current_timestamp() COMMENT 'Row ingestion timestamp',
    _source_system      STRING        DEFAULT 'CDW_PMT_HIST' COMMENT 'Source table identifier'
)
USING DELTA
PARTITIONED BY (payment_year)
COMMENT 'Payment history fact table migrated from legacy CDW_PMT_HIST. Partitioned by payment year.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);
