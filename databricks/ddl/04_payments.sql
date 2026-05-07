-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Payment History)
-- =============================================================================
-- Payment transaction fact table.  Partitioned by payment_year (derived from
-- payment_date) to optimise time-range scans for reconciliation and reporting.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    id                  BIGINT        GENERATED ALWAYS AS IDENTITY,
    legacy_payment_id   STRING        COMMENT 'Original PMT_SEQ_NBR for traceability',
    loan_account_id     BIGINT        NOT NULL COMMENT 'FK to loan_accounts.id resolved via account_number',
    payment_date        DATE          COMMENT 'Parsed from MM/DD/YYYY',
    total_amount        DECIMAL(10,2) COMMENT 'Parsed from comma-formatted string',
    principal_amount    DECIMAL(10,2),
    interest_amount     DECIMAL(10,2),
    escrow_amount       DECIMAL(10,2),
    late_fee            DECIMAL(10,2),
    type                STRING        COMMENT 'Expanded: REG->Regular, EXT->Extra, PRT->Partial, PRE->Prepayment',
    status              STRING        COMMENT 'Expanded: PST->Posted, REV->Reversed, NSF->NSF, PND->Pending',
    received_date       DATE          COMMENT 'Parsed from MM/DD/YYYY',
    processed_date      DATE          COMMENT 'Parsed from MM/DD/YYYY',
    created_at          TIMESTAMP     COMMENT 'Parsed from MM/DD/YYYY',
    updated_at          TIMESTAMP     COMMENT 'Parsed from MM/DD/YYYY',
    payment_year        INT           COMMENT 'Derived partition column: year(payment_date)',
    _ingestion_ts       TIMESTAMP     DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp',

    CONSTRAINT pk_payments PRIMARY KEY (id)
)
USING DELTA
COMMENT 'Modern payment history fact table migrated from CDW_PMT_HIST'
PARTITIONED BY (payment_year)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);
