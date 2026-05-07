-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Payment History)
-- =============================================================================
-- Payment transaction fact table. Partitioned by payment_year to optimise
-- time-range queries on payment history.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    id                  BIGINT        GENERATED ALWAYS AS IDENTITY,
    legacy_payment_id   STRING        COMMENT 'Legacy PMT_SEQ_NBR for traceability',
    loan_account_id     BIGINT        NOT NULL COMMENT 'FK to loan_accounts.id via account_number lookup',
    payment_date        DATE          NOT NULL COMMENT 'Scheduled payment due date',
    total_amount        DECIMAL(10,2) NOT NULL COMMENT 'Total payment amount',
    principal_amount    DECIMAL(10,2) COMMENT 'Principal portion of payment',
    interest_amount     DECIMAL(10,2) COMMENT 'Interest portion of payment',
    escrow_amount       DECIMAL(10,2) COMMENT 'Escrow portion of payment',
    late_fee            DECIMAL(10,2) DEFAULT 0 COMMENT 'Late fee assessed',
    type                STRING        NOT NULL COMMENT 'Expanded: REG->Regular, EXT->Extra, PRT->Partial, PRE->Prepayment',
    status              STRING        NOT NULL COMMENT 'Expanded: PST->Posted, REV->Reversed, NSF->NSF, PND->Pending',
    received_date       DATE          COMMENT 'Date payment was received',
    processed_date      DATE          COMMENT 'Date payment was processed',
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    payment_year        INT           GENERATED ALWAYS AS (YEAR(payment_date))
                                      COMMENT 'Partition key derived from payment_date',

    CONSTRAINT payments_pk PRIMARY KEY (id),
    CONSTRAINT fk_payment_loan FOREIGN KEY (loan_account_id) REFERENCES loan_warehouse.loan_accounts(id)
)
USING DELTA
PARTITIONED BY (payment_year)
COMMENT 'Modern payment history fact table migrated from CDW_PMT_HIST. Partitioned by payment year.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);
