-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy)
-- =============================================================================
-- Normalized borrower dimension table with proper Spark SQL types.
-- Partitioned by state for geographic query patterns common in loan servicing.
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
    status              STRING          NOT NULL DEFAULT 'ACTIVE',
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp(),
    _source_system      STRING          DEFAULT 'CDW_BORR_MSTR'
)
USING DELTA
PARTITIONED BY (state)
COMMENT 'Borrower dimension table migrated from legacy CDW_BORR_MSTR. Partitioned by state for regional query performance.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.tier'                     = 'gold'
);

-- Unique constraint on legacy external ID
ALTER TABLE loan_warehouse.borrowers
ADD CONSTRAINT borrowers_external_id_unique UNIQUE (external_id);
