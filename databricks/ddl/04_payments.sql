-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST
-- Partitioned by: payment_year (extracted from payment_date)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    loan_account_id     BIGINT          NOT NULL, -- FK resolved from legacy LN_ACCT_NBR via loan_accounts lookup
    payment_date        DATE            NOT NULL,
    payment_year        INT             NOT NULL COMMENT 'Partition key extracted from payment_date',
    total_amount        DECIMAL(10, 2)  NOT NULL,
    principal_amount    DECIMAL(10, 2),
    interest_amount     DECIMAL(10, 2),
    escrow_amount       DECIMAL(10, 2),
    late_fee            DECIMAL(10, 2),
    type                STRING          NOT NULL, -- Expanded: REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT
    status              STRING          NOT NULL, -- Expanded: PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING
    received_date       DATE,
    processed_date      DATE,
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    _legacy_pmt_seq     STRING          COMMENT 'Original CDW_PMT_HIST.PMT_SEQ_NBR for lineage',
    _ingested_at        TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Row ingestion timestamp',

    CONSTRAINT payments_pk PRIMARY KEY (payment_id),
    CONSTRAINT payments_loan_fk FOREIGN KEY (loan_account_id)
        REFERENCES loan_warehouse.loan_accounts (loan_id)
)
USING DELTA
PARTITIONED BY (payment_year)
COMMENT 'Payment history table migrated from CDW_PMT_HIST. Partitioned by payment year for time-range queries.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.pipeline.source'          = 'CDW_PMT_HIST'
);
