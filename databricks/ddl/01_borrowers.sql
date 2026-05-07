-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy Borrower Master)
-- =============================================================================
-- Normalized borrower dimension table with proper data types.
-- Partitioned by state for geographic query optimization.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    borrower_key        BIGINT GENERATED ALWAYS AS IDENTITY,
    external_id         STRING        NOT NULL,
    first_name          STRING        NOT NULL,
    last_name           STRING        NOT NULL,
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
    status              STRING        DEFAULT 'ACTIVE',
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    _ingestion_ts       TIMESTAMP     DEFAULT current_timestamp(),
    _source_system      STRING        DEFAULT 'CDW_BORR_MSTR'
)
USING DELTA
PARTITIONED BY (state)
COMMENT 'Borrower dimension table migrated from legacy CDW_BORR_MSTR'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.constraints.external_id'  = 'external_id IS NOT NULL',
    'quality.constraints.first_name'   = 'first_name IS NOT NULL',
    'quality.constraints.last_name'    = 'last_name IS NOT NULL'
);

-- Optimize for common lookup patterns
ALTER TABLE loan_warehouse.borrowers
    SET TBLPROPERTIES ('delta.dataSkippingNumIndexedCols' = '10');
