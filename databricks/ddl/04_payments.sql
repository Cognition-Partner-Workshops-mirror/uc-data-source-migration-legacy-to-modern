-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Core Data Warehouse)
-- =============================================================================
-- Payment history fact table. Partitioned by payment_year (extracted from
-- payment_date) for time-range queries on payment history and monthly
-- reconciliation runs.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_nbr STRING          COMMENT 'Original PMT_SEQ_NBR from CDW_PMT_HIST for traceability',
    loan_account_id     BIGINT          NOT NULL,
    payment_date        DATE            NOT NULL,
    total_amount        DECIMAL(10, 2)  NOT NULL,
    principal_amount    DECIMAL(10, 2),
    interest_amount     DECIMAL(10, 2),
    escrow_amount       DECIMAL(10, 2),
    late_fee            DECIMAL(10, 2)  DEFAULT 0,
    type                STRING          NOT NULL    COMMENT 'REGULAR, EXTRA, PARTIAL, PREPAYMENT',
    status              STRING          NOT NULL    COMMENT 'POSTED, REVERSED, NSF, PENDING',
    received_date       DATE,
    processed_date      DATE,
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    payment_year        INT             GENERATED ALWAYS AS (YEAR(payment_date)),
    _load_ts            TIMESTAMP       DEFAULT current_timestamp(),
    _source_system      STRING          DEFAULT 'CDW_PMT_HIST',

    CONSTRAINT pk_payments PRIMARY KEY (payment_id),
    CONSTRAINT fk_payment_loan FOREIGN KEY (loan_account_id) REFERENCES loan_warehouse.loan_accounts(loan_account_id)
)
USING DELTA
PARTITIONED BY (payment_year)
COMMENT 'Payment history fact table migrated from CDW_PMT_HIST. Partitioned by payment year for time-range analytics.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.minReaderVersion'           = '1',
    'delta.minWriterVersion'           = '2'
);
