-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Payment History)
-- =============================================================================
-- Payment transaction fact table. Partitioned by payment_year (derived from
-- payment_date) to optimize time-range queries and monthly reconciliation.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_key         BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_nbr STRING          NOT NULL    COMMENT 'Legacy PMT_SEQ_NBR for traceability',
    loan_key            BIGINT          NOT NULL    COMMENT 'FK to loan_accounts; resolved from legacy LN_ACCT_NBR',
    payment_date        DATE            NOT NULL    COMMENT 'Legacy PMT_DT parsed from MM/DD/YYYY',
    total_amount        DECIMAL(10, 2)  NOT NULL    COMMENT 'Legacy PMT_AMT parsed from comma-formatted string',
    principal_amount    DECIMAL(10, 2)              COMMENT 'Legacy PMT_PRIN_AMT parsed from comma-formatted string',
    interest_amount     DECIMAL(10, 2)              COMMENT 'Legacy PMT_INT_AMT parsed from comma-formatted string',
    escrow_amount       DECIMAL(10, 2)              COMMENT 'Legacy PMT_ESCROW_AMT parsed from comma-formatted string',
    late_fee            DECIMAL(10, 2)  DEFAULT 0   COMMENT 'Legacy PMT_LATE_FEE parsed from comma-formatted string',
    type                STRING          NOT NULL    COMMENT 'Legacy PMT_TYP_CD expanded: REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT',
    status              STRING          NOT NULL    COMMENT 'Legacy PMT_STAT_CD expanded: PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING',
    received_date       DATE                        COMMENT 'Legacy PMT_RECV_DT parsed from MM/DD/YYYY',
    processed_date      DATE                        COMMENT 'Legacy PMT_PROC_DT parsed from MM/DD/YYYY',
    payment_year        INT             NOT NULL    COMMENT 'Derived partition column: YEAR(payment_date)',
    created_at          TIMESTAMP                   COMMENT 'Legacy PMT_CRET_DT parsed from MM/DD/YYYY',
    updated_at          TIMESTAMP                   COMMENT 'Legacy PMT_UPDT_DT parsed from MM/DD/YYYY',
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp()
                                                    COMMENT 'Pipeline ingestion timestamp',

    CONSTRAINT payments_pk PRIMARY KEY (payment_key),
    CONSTRAINT payments_loan_fk FOREIGN KEY (loan_key) REFERENCES loan_warehouse.loan_accounts(loan_key)
)
USING DELTA
PARTITIONED BY (payment_year)
COMMENT 'Payment history fact table migrated from CDW_PMT_HIST'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);
