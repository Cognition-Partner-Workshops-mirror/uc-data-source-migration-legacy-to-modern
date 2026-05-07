-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Payment History)
-- =============================================================================
-- Transaction-level payment history. Partitioned by payment year derived from
-- payment_date to support time-range queries common in servicing and audit.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_payment_id   STRING          COMMENT 'Legacy PMT_SEQ_NBR for traceability',
    loan_account_id     BIGINT          NOT NULL COMMENT 'FK to loan_accounts.id',
    payment_date        DATE            NOT NULL,
    total_amount        DECIMAL(10, 2),
    principal_amount    DECIMAL(10, 2),
    interest_amount     DECIMAL(10, 2),
    escrow_amount       DECIMAL(10, 2),
    late_fee            DECIMAL(10, 2),
    type                STRING          COMMENT 'REGULAR, EXTRA, PARTIAL, PREPAYMENT',
    status              STRING          NOT NULL COMMENT 'POSTED, REVERSED, NSF, PENDING',
    received_date       DATE,
    processed_date      DATE,
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    payment_year        INT             COMMENT 'Derived from payment_date for partitioning',
    _migration_src      STRING          DEFAULT 'CDW_PMT_HIST' COMMENT 'Source table for lineage',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Migration run timestamp',

    CONSTRAINT payments_pk PRIMARY KEY (id),
    CONSTRAINT payments_loan_fk FOREIGN KEY (loan_account_id) REFERENCES loan_warehouse.loan_accounts(id)
)
USING DELTA
PARTITIONED BY (payment_year)
COMMENT 'Payment history table migrated from CDW_PMT_HIST'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);
