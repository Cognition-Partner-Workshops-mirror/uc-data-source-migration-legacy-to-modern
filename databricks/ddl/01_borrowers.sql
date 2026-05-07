-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (legacy)
-- =============================================================================
-- Normalized borrower dimension table with proper data types.
-- Partitioned by state for geographic query patterns.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    borrower_key        BIGINT GENERATED ALWAYS AS IDENTITY,
    external_id         STRING NOT NULL,
    first_name          STRING NOT NULL,
    last_name           STRING NOT NULL,
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
    status              STRING DEFAULT 'ACTIVE',
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    _load_timestamp     TIMESTAMP DEFAULT current_timestamp(),
    _source_system      STRING DEFAULT 'CDW_BORR_MSTR'
)
USING DELTA
COMMENT 'Borrower dimension table migrated from legacy CDW_BORR_MSTR'
PARTITIONED BY (state)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.tier'                     = 'gold'
);

-- Unique constraint on external_id for deduplication
ALTER TABLE loan_warehouse.borrowers
ADD CONSTRAINT borrowers_external_id_unique UNIQUE (external_id);
