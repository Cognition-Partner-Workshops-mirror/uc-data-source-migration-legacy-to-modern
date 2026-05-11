-- =============================================================================
-- Delta Lake Table: payments
-- =============================================================================
-- Source: CDW_PMT_HIST (legacy all-VARCHAR payment history table)
-- Target: payments (modern typed payment fact table)
--
-- Key transformations from legacy:
--   - LN_ACCT_NBR resolved to loan_account_id via loan_accounts lookup
--   - PMT_AMT, PMT_PRIN_AMT, etc. (VARCHAR with commas) → DECIMAL
--   - PMT_TYP_CD (REG/EXT/PRT/PRE) → type (expanded string)
--   - PMT_STAT_CD (PST/REV/NSF/PND) → status (expanded string)
--   - All date VARCHARs (MM/DD/YYYY) → DATE or TIMESTAMP
--
-- Partitioning: by payment_year — derived from payment_date.
--   Payment queries are almost always time-bounded; year partitioning enables
--   efficient partition pruning for monthly/quarterly reporting.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    -- Surrogate key
    payment_id          BIGINT          GENERATED ALWAYS AS IDENTITY,

    -- Legacy sequence number preserved for audit trail
    legacy_sequence_nbr STRING,

    -- FK to loan_accounts — resolved from legacy LN_ACCT_NBR via account_number lookup
    loan_account_id     BIGINT          NOT NULL,

    -- Payment date — parsed from legacy MM/DD/YYYY VARCHAR
    payment_date        DATE            NOT NULL,

    -- Payment amounts — parsed from legacy comma-formatted VARCHAR to decimal
    total_amount        DECIMAL(10, 2)  NOT NULL,
    principal_amount    DECIMAL(10, 2),
    interest_amount     DECIMAL(10, 2),
    escrow_amount       DECIMAL(10, 2),
    late_fee            DECIMAL(10, 2)  DEFAULT 0,

    -- Payment type — expanded from legacy abbreviation:
    --   REG→Regular, EXT→Extra, PRT→Partial, PRE→Prepayment
    type                STRING          NOT NULL,

    -- Payment status — expanded from legacy abbreviation:
    --   PST→Posted, REV→Reversed, NSF→NSF, PND→Pending
    status              STRING          NOT NULL,

    -- Processing dates — parsed from legacy MM/DD/YYYY VARCHAR
    received_date       DATE,
    processed_date      DATE,

    -- Audit timestamps — parsed from legacy MM/DD/YYYY strings
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,

    -- Partition column — derived from payment_date during ingestion
    payment_year        INT             NOT NULL,

    -- ETL metadata columns for lineage tracking
    _etl_loaded_at      TIMESTAMP       DEFAULT current_timestamp(),
    _etl_source         STRING          DEFAULT 'CDW_PMT_HIST'
)
USING DELTA
-- Partition by payment year: time-series data benefits from year-level partitioning
-- for efficient pruning in monthly/quarterly reporting queries.
PARTITIONED BY (payment_year)
COMMENT 'Modern payment fact table migrated from legacy CDW_PMT_HIST. Amount VARCHARs converted to DECIMAL, status/type codes expanded, FK references loan_accounts.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name'
);
