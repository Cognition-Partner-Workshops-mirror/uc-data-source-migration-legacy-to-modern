-- =============================================================================
-- Delta Lake Table: payments
-- =============================================================================
-- Migrated from legacy CDW_PMT_HIST table.
-- Payment type codes expanded: REG->Regular, EXT->Extra, PRT->Partial, PRE->Prepayment.
-- Payment status codes expanded: PST->Posted, REV->Reversed, NSF->NSF, PND->Pending.
-- All amount strings parsed from comma-formatted VARCHAR to DECIMAL types.
-- All date strings (MM/DD/YYYY) parsed to DATE or TIMESTAMP types.
-- Legacy PMT_SEQ_NBR preserved as external_payment_id for traceability.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    -- Surrogate key generated during ingestion
    payment_id              BIGINT              COMMENT 'Auto-generated surrogate primary key',
    -- Legacy sequence number preserved for traceability
    external_payment_id     STRING              COMMENT 'Legacy payment ID from CDW_PMT_HIST.PMT_SEQ_NBR',
    -- Foreign key to loan_accounts table (resolved from CDW_PMT_HIST.LN_ACCT_NBR)
    loan_account_id         BIGINT NOT NULL      COMMENT 'FK to loan_accounts.loan_account_id, resolved via LN_ACCT_NBR lookup',
    -- Payment financial details
    payment_date            DATE NOT NULL        COMMENT 'Parsed from PMT_DT (MM/DD/YYYY -> DATE)',
    total_amount            DECIMAL(10, 2) NOT NULL  COMMENT 'Parsed from PMT_AMT (comma-formatted string -> DECIMAL)',
    principal_amount        DECIMAL(10, 2)       COMMENT 'Parsed from PMT_PRIN_AMT (comma-formatted string -> DECIMAL)',
    interest_amount         DECIMAL(10, 2)       COMMENT 'Parsed from PMT_INT_AMT (comma-formatted string -> DECIMAL)',
    escrow_amount           DECIMAL(10, 2)       COMMENT 'Parsed from PMT_ESCROW_AMT (comma-formatted string -> DECIMAL)',
    late_fee                DECIMAL(10, 2) DEFAULT 0  COMMENT 'Parsed from PMT_LATE_FEE (comma-formatted string -> DECIMAL)',
    -- Payment classification
    type                    STRING NOT NULL       COMMENT 'Expanded from PMT_TYP_CD: REG->Regular, EXT->Extra, PRT->Partial, PRE->Prepayment',
    status                  STRING NOT NULL       COMMENT 'Expanded from PMT_STAT_CD: PST->Posted, REV->Reversed, NSF->NSF, PND->Pending',
    -- Processing dates
    received_date           DATE                 COMMENT 'Parsed from PMT_RECV_DT (MM/DD/YYYY -> DATE)',
    processed_date          DATE                 COMMENT 'Parsed from PMT_PROC_DT (MM/DD/YYYY -> DATE)',
    -- Audit timestamps
    created_at              TIMESTAMP            COMMENT 'Parsed from PMT_CRET_DT (MM/DD/YYYY -> TIMESTAMP)',
    updated_at              TIMESTAMP            COMMENT 'Parsed from PMT_UPDT_DT (MM/DD/YYYY -> TIMESTAMP)',
    -- Ingestion metadata
    _ingestion_ts           TIMESTAMP            COMMENT 'Timestamp when record was ingested into Delta Lake',
    _source_system          STRING               COMMENT 'Source system identifier (CDW_PMT_HIST)',
    -- Partition columns derived from payment_date during ingestion
    payment_year            INT                  COMMENT 'Derived year from payment_date for partitioning',
    payment_month           INT                  COMMENT 'Derived month from payment_date for partitioning'
)
USING DELTA
-- Partitioned by payment year and month for efficient time-range queries
-- and data lifecycle management (e.g., archiving old payment records)
PARTITIONED BY (payment_year, payment_month)
COMMENT 'Payment history fact table migrated from legacy CDW_PMT_HIST. Contains all loan payment transactions with expanded type and status codes.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.enableChangeDataFeed'       = 'true'
);
