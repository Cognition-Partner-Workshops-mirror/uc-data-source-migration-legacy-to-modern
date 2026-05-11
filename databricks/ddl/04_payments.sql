-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Payment History)
-- =============================================================================
-- Payment transactions linked to loan accounts via foreign key.
-- Status codes expanded: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING
-- Type codes expanded: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT
--
-- Partitioned by payment_date (year/month granularity via date column) to
-- support efficient time-range queries on payment history.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    -- Surrogate key
    id                  BIGINT         GENERATED ALWAYS AS IDENTITY,

    -- Legacy sequence number preserved for traceability
    legacy_sequence_nbr STRING         NOT NULL  COMMENT 'Legacy PMT_SEQ_NBR from CDW_PMT_HIST',

    -- Foreign key (resolved during ingestion via account_number lookup)
    loan_account_id     BIGINT         NOT NULL  COMMENT 'FK → loan_accounts.id (resolved from LN_ACCT_NBR)',

    -- Payment amounts
    payment_date        DATE           NOT NULL  COMMENT 'Parsed from PMT_DT (MM/DD/YYYY)',
    total_amount        DECIMAL(10,2)            COMMENT 'Parsed from PMT_AMT (commas removed)',
    principal_amount    DECIMAL(10,2)            COMMENT 'Parsed from PMT_PRIN_AMT (commas removed)',
    interest_amount     DECIMAL(10,2)            COMMENT 'Parsed from PMT_INT_AMT (commas removed)',
    escrow_amount       DECIMAL(10,2)            COMMENT 'Parsed from PMT_ESCROW_AMT (commas removed)',
    late_fee            DECIMAL(10,2)            COMMENT 'Parsed from PMT_LATE_FEE (commas removed)',

    -- Classification
    type                STRING         NOT NULL  COMMENT 'Expanded: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT',
    status              STRING         NOT NULL  COMMENT 'Expanded: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING',

    -- Processing dates
    received_date       DATE                     COMMENT 'Parsed from PMT_RECV_DT (MM/DD/YYYY)',
    processed_date      DATE                     COMMENT 'Parsed from PMT_PROC_DT (MM/DD/YYYY)',

    -- Audit timestamps
    created_at          TIMESTAMP                COMMENT 'Parsed from PMT_CRET_DT (MM/DD/YYYY)',
    updated_at          TIMESTAMP                COMMENT 'Parsed from PMT_UPDT_DT (MM/DD/YYYY)',

    -- Partitioning helper — year extracted from payment_date for efficient partition pruning
    payment_year        INT            NOT NULL  COMMENT 'Year extracted from payment_date for partitioning',

    -- Delta Lake metadata
    _ingestion_ts       TIMESTAMP    DEFAULT current_timestamp() COMMENT 'Row ingestion timestamp',
    _source_system      STRING       DEFAULT 'CDW_PMT_HIST'      COMMENT 'Source system identifier'
)
USING DELTA
-- Partition by payment year for time-range query performance
PARTITIONED BY (payment_year)
COMMENT 'Payment history fact table — migrated from legacy CDW_PMT_HIST'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);

-- Unique constraint on legacy sequence number
ALTER TABLE loan_warehouse.payments
    ADD CONSTRAINT payments_legacy_seq_unique UNIQUE (legacy_sequence_nbr);
