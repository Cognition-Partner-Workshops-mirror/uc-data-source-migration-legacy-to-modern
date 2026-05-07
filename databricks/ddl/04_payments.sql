-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Payment History)
-- =============================================================================
-- Fact table for payment transactions. Largest table by volume in the warehouse.
-- Partitioned by payment_year (extracted from payment_date) for time-range
-- queries which dominate payment analytics (monthly statements, annual reports).
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    -- Surrogate key
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,
    -- Legacy payment sequence number preserved for traceability
    legacy_payment_id   STRING          NOT NULL COMMENT 'Legacy PMT_SEQ_NBR from CDW_PMT_HIST',
    -- FK to loan_accounts (replaces raw account number string)
    loan_account_id     BIGINT          NOT NULL COMMENT 'FK to loan_accounts.id; resolved from LN_ACCT_NBR via account_number lookup',
    -- Date fields parsed from MM/DD/YYYY VARCHAR strings
    payment_date        DATE            NOT NULL COMMENT 'Payment date (was PMT_DT)',
    received_date       DATE            COMMENT 'Date payment received (was PMT_RECV_DT)',
    processed_date      DATE            COMMENT 'Date payment processed (was PMT_PROC_DT)',
    -- Financial amounts parsed from comma-formatted VARCHAR strings
    total_amount        DECIMAL(10,2)   NOT NULL COMMENT 'Total payment amount (was PMT_AMT)',
    principal_amount    DECIMAL(10,2)   COMMENT 'Principal portion (was PMT_PRIN_AMT)',
    interest_amount     DECIMAL(10,2)   COMMENT 'Interest portion (was PMT_INT_AMT)',
    escrow_amount       DECIMAL(10,2)   COMMENT 'Escrow portion (was PMT_ESCROW_AMT)',
    late_fee            DECIMAL(10,2)   DEFAULT 0.00 COMMENT 'Late fee amount (was PMT_LATE_FEE)',
    -- Status/type codes expanded from abbreviations
    type                STRING          NOT NULL COMMENT 'Expanded: REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT',
    status              STRING          NOT NULL COMMENT 'Expanded: PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING',
    -- Audit timestamps
    created_at          TIMESTAMP       COMMENT 'Record creation (was PMT_CRET_DT)',
    updated_at          TIMESTAMP       COMMENT 'Last update (was PMT_UPDT_DT)',
    -- Partition column derived from payment_date for time-range query optimization
    payment_year        INT             GENERATED ALWAYS AS (YEAR(payment_date)) COMMENT 'Partition key derived from payment_date',
    -- Pipeline metadata
    _ingested_at        TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Ingestion timestamp',
    _source_system      STRING          DEFAULT 'CDW_PMT_HIST' COMMENT 'Source system identifier'
)
USING DELTA
PARTITIONED BY (payment_year)
COMMENT 'Payment history fact table migrated from CDW_PMT_HIST. Partitioned by payment_year for time-range analytics.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
