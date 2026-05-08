-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Core Data Warehouse)
-- =============================================================================
-- Payment history fact table. Partitioned by payment_year to enable efficient
-- time-range scans for monthly/quarterly reconciliation reporting.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_nbr STRING                      COMMENT 'Original PMT_SEQ_NBR for audit trail',
    loan_account_id     BIGINT          NOT NULL    COMMENT 'FK to loan_accounts.loan_account_id',
    payment_date        DATE            NOT NULL    COMMENT 'Parsed from MM/DD/YYYY',
    total_amount        DECIMAL(10, 2)  NOT NULL    COMMENT 'Parsed from comma-formatted string',
    principal_amount    DECIMAL(10, 2)              COMMENT 'Principal portion of payment',
    interest_amount     DECIMAL(10, 2)              COMMENT 'Interest portion of payment',
    escrow_amount       DECIMAL(10, 2)              COMMENT 'Escrow portion of payment',
    late_fee            DECIMAL(10, 2)  DEFAULT 0   COMMENT 'Late fee amount',
    type                STRING          NOT NULL    COMMENT 'Expanded: REG->Regular, EXT->Extra, PRT->Partial, PRE->Prepayment',
    status              STRING          NOT NULL    COMMENT 'Expanded: PST->Posted, REV->Reversed, NSF->NSF, PND->Pending',
    received_date       DATE                        COMMENT 'Date payment was received',
    processed_date      DATE                        COMMENT 'Date payment was processed',
    created_at          TIMESTAMP                   COMMENT 'Parsed from legacy PMT_CRET_DT',
    updated_at          TIMESTAMP                   COMMENT 'Parsed from legacy PMT_UPDT_DT',
    payment_year        INT             NOT NULL    COMMENT 'Derived partition key: year(payment_date)',
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp'
)
USING DELTA
PARTITIONED BY (payment_year)
COMMENT 'Payment history fact table migrated from CDW_PMT_HIST. Partitioned by payment year.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.tier'                     = 'gold'
);
