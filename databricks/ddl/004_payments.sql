-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Payment History)
-- =============================================================================
-- Payment transaction fact table. Partitioned by payment_year (extracted from
-- payment_date) for efficient time-range queries common in loan servicing.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_key         BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_nbr STRING          COMMENT 'Legacy PMT_SEQ_NBR preserved for audit/reconciliation',
    loan_account_key    BIGINT          NOT NULL COMMENT 'FK to loan_accounts, resolved from legacy LN_ACCT_NBR',
    payment_date        DATE            NOT NULL COMMENT 'Legacy PMT_DT parsed from MM/DD/YYYY',
    total_amount        DECIMAL(10, 2)  NOT NULL COMMENT 'Legacy PMT_AMT parsed from comma-string',
    principal_amount    DECIMAL(10, 2)  COMMENT 'Legacy PMT_PRIN_AMT parsed from comma-string',
    interest_amount     DECIMAL(10, 2)  COMMENT 'Legacy PMT_INT_AMT parsed from comma-string',
    escrow_amount       DECIMAL(10, 2)  COMMENT 'Legacy PMT_ESCROW_AMT parsed from comma-string',
    late_fee            DECIMAL(10, 2)  DEFAULT 0.00 COMMENT 'Legacy PMT_LATE_FEE parsed from comma-string',
    type                STRING          NOT NULL COMMENT 'Expanded from PMT_TYP_CD: REG->Regular, EXT->Extra, PRT->Partial, PRE->Prepayment',
    status              STRING          NOT NULL COMMENT 'Expanded from PMT_STAT_CD: PST->Posted, REV->Reversed, NSF->NSF, PND->Pending',
    received_date       DATE            COMMENT 'Legacy PMT_RECV_DT parsed from MM/DD/YYYY',
    processed_date      DATE            COMMENT 'Legacy PMT_PROC_DT parsed from MM/DD/YYYY',
    created_at          TIMESTAMP       COMMENT 'Legacy PMT_CRET_DT parsed from MM/DD/YYYY',
    updated_at          TIMESTAMP       COMMENT 'Legacy PMT_UPDT_DT parsed from MM/DD/YYYY',
    payment_year        INT             NOT NULL COMMENT 'Partition column derived from payment_date year',
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp',

    CONSTRAINT payments_pk PRIMARY KEY (payment_key),
    CONSTRAINT payments_loan_fk FOREIGN KEY (loan_account_key) REFERENCES loan_warehouse.loan_accounts (loan_account_key)
)
USING DELTA
PARTITIONED BY (payment_year)
COMMENT 'Payment history fact table migrated from CDW_PMT_HIST. Partitioned by payment year for time-range queries.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);
