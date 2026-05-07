-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Payment History)
-- =============================================================================
-- Transaction-grain fact table for all loan payments.
-- Partitioned by payment year to optimize time-range queries and enable
-- efficient Z-ORDER on loan_account_id within each partition.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_id          BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_nbr STRING          NOT NULL    COMMENT 'Original CDW_PMT_HIST.PMT_SEQ_NBR',
    loan_account_id     BIGINT          NOT NULL    COMMENT 'FK to loan_accounts.loan_account_id',
    payment_date        DATE            NOT NULL,
    total_amount        DECIMAL(10, 2)  NOT NULL,
    principal_amount    DECIMAL(10, 2),
    interest_amount     DECIMAL(10, 2),
    escrow_amount       DECIMAL(10, 2),
    late_fee            DECIMAL(10, 2)  DEFAULT 0,
    type                STRING          NOT NULL
                                        COMMENT 'Regular, Extra, Partial, Prepayment',
    status              STRING          NOT NULL
                                        COMMENT 'Posted, Reversed, NSF, Pending',
    received_date       DATE,
    processed_date      DATE,
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    payment_year        INT             GENERATED ALWAYS AS (YEAR(payment_date))
                                        COMMENT 'Derived partition column',
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Row ingestion timestamp'
)
USING DELTA
COMMENT 'Payment history fact table migrated from CDW_PMT_HIST'
PARTITIONED BY (payment_year)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.tier'                     = 'gold'
);

-- Optimize reads that filter on a specific loan within a year partition
-- OPTIMIZE loan_warehouse.payments ZORDER BY (loan_account_id);
