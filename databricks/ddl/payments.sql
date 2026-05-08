-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (legacy all-VARCHAR payment history table)
-- =============================================================================
-- Payment transaction fact table. Amount fields are parsed from comma-formatted
-- VARCHAR strings to DECIMAL. Status and type codes are expanded to readable
-- strings. The legacy PMT_SEQ_NBR is preserved for lineage.
--
-- Partitioned by payment year (extracted from payment_date) to align with the
-- time-series nature of payment queries and support efficient date-range scans.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    -- Surrogate key
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,

    -- Legacy sequence number preserved for lineage
    legacy_payment_id   STRING          NOT NULL    COMMENT 'Legacy PMT_SEQ_NBR for back-reference',

    -- Foreign key (resolved from legacy LN_ACCT_NBR during ingestion)
    loan_account_id     BIGINT          NOT NULL    COMMENT 'FK to loan_accounts.id resolved from LN_ACCT_NBR',

    -- Payment dates (parsed from MM/DD/YYYY strings)
    payment_date        DATE            NOT NULL    COMMENT 'Scheduled payment date (PMT_DT)',
    received_date       DATE                        COMMENT 'Date payment was received (PMT_RECV_DT)',
    processed_date      DATE                        COMMENT 'Date payment was processed (PMT_PROC_DT)',

    -- Amount breakdown (parsed from comma-formatted strings)
    total_amount        DECIMAL(10,2)   NOT NULL    COMMENT 'Total payment amount (PMT_AMT)',
    principal_amount    DECIMAL(10,2)   NOT NULL    COMMENT 'Principal portion (PMT_PRIN_AMT)',
    interest_amount     DECIMAL(10,2)   NOT NULL    COMMENT 'Interest portion (PMT_INT_AMT)',
    escrow_amount       DECIMAL(10,2)   NOT NULL    COMMENT 'Escrow portion (PMT_ESCROW_AMT)',
    late_fee            DECIMAL(10,2)   NOT NULL    DEFAULT 0 COMMENT 'Late fee if applicable (PMT_LATE_FEE)',

    -- Type and status (expanded from abbreviations)
    type                STRING          NOT NULL    COMMENT 'Expanded: REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT (PMT_TYP_CD)',
    status              STRING          NOT NULL    COMMENT 'Expanded: PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING (PMT_STAT_CD)',

    -- Derived field for partitioning
    payment_year        INT             NOT NULL    COMMENT 'Year extracted from payment_date for partitioning',

    -- Audit timestamps
    created_at          TIMESTAMP       NOT NULL    COMMENT 'PMT_CRET_DT parsed to timestamp',
    updated_at          TIMESTAMP       NOT NULL    COMMENT 'PMT_UPDT_DT parsed to timestamp',

    -- Ingestion metadata
    _legacy_source      STRING          DEFAULT 'CDW_PMT_HIST'   COMMENT 'Source table for lineage',
    _ingested_at        TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp'
)
USING DELTA
PARTITIONED BY (payment_year)
COMMENT 'Payment history fact table migrated from legacy CDW_PMT_HIST. Partitioned by payment year for time-range query performance.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);
