-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy Borrower Master)
-- =============================================================================
-- Normalized borrower dimension table with proper data types.
-- Partitioned by status to optimize queries filtering on active/inactive borrowers.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    borrower_id         BIGINT          GENERATED ALWAYS AS IDENTITY,
    external_id         STRING          NOT NULL,
    first_name          STRING          NOT NULL,
    last_name           STRING          NOT NULL,
    middle_initial      STRING,
    ssn_hash            STRING,
    date_of_birth       DATE,
    address_line1       STRING,
    address_line2       STRING,
    city                STRING,
    state               STRING,
    zip_code            STRING,
    phone               STRING,
    email               STRING,
    credit_score        INT,
    employment_status   STRING,
    annual_income       DECIMAL(12, 2),
    status              STRING          NOT NULL DEFAULT 'Active',
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    _legacy_borr_id     STRING          COMMENT 'Original CDW_BORR_MSTR.BORR_ID for lineage',
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Row ingestion timestamp'
)
USING DELTA
COMMENT 'Borrower dimension table migrated from CDW_BORR_MSTR'
PARTITIONED BY (status)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.tier'                     = 'gold'
);

-- Unique constraint on the legacy external ID
ALTER TABLE loan_warehouse.borrowers
    ADD CONSTRAINT borrowers_external_id_unique UNIQUE (external_id);
