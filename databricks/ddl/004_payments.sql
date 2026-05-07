-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy CDW)
-- =============================================================================
-- Payment history fact table. Partitioned by payment year/month for
-- time-series queries and efficient pruning of historical data.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_modernized.payments (
    payment_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_nbr STRING          NOT NULL    COMMENT 'Original PMT_SEQ_NBR for traceability',
    account_number      STRING          NOT NULL    COMMENT 'FK reference to loan_accounts.account_number',
    payment_date        DATE            NOT NULL    COMMENT 'Payment due date parsed from MM/DD/YYYY',
    total_amount        DECIMAL(10, 2)  NOT NULL    COMMENT 'Total payment amount',
    principal_amount    DECIMAL(10, 2)              COMMENT 'Principal portion of payment',
    interest_amount     DECIMAL(10, 2)              COMMENT 'Interest portion of payment',
    escrow_amount       DECIMAL(10, 2)              COMMENT 'Escrow portion of payment',
    late_fee            DECIMAL(10, 2)  DEFAULT 0   COMMENT 'Late fee amount',
    type                STRING          NOT NULL    COMMENT 'Expanded: REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT',
    status              STRING          NOT NULL    COMMENT 'Expanded: PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING',
    received_date       DATE                        COMMENT 'Date payment was received',
    processed_date      DATE                        COMMENT 'Date payment was processed',
    payment_year        INT                         COMMENT 'Derived from payment_date for partitioning',
    payment_month       INT                         COMMENT 'Derived from payment_date for partitioning',
    created_at          TIMESTAMP                   COMMENT 'Record creation timestamp',
    updated_at          TIMESTAMP                   COMMENT 'Last update timestamp',
    _migration_ts       TIMESTAMP       DEFAULT current_timestamp()
                                                    COMMENT 'Timestamp when record was migrated'
)
USING DELTA
COMMENT 'Payment history fact table migrated from legacy CDW_PMT_HIST'
PARTITIONED BY (payment_year, payment_month)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);

ALTER TABLE loan_modernized.payments
    ADD CONSTRAINT payments_positive_amount EXPECT (total_amount >= 0)
    VIOLATION (DROP ROW);
