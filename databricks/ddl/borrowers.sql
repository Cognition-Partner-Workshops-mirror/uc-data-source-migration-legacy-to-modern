-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy CDW Borrower Master)
-- =============================================================================
-- Normalized borrower dimension table with proper Spark SQL types.
-- Partitioned by state to support regional analytics and compliance queries.
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
    status              STRING          DEFAULT 'Active',
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    _migration_source   STRING          DEFAULT 'CDW_BORR_MSTR',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
PARTITIONED BY (state)
COMMENT 'Modern borrower dimension table migrated from legacy CDW_BORR_MSTR. Partitioned by state for regional query performance.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);

-- Unique constraint on legacy external_id for deduplication
ALTER TABLE loan_warehouse.borrowers
ADD CONSTRAINT borrowers_external_id_unique UNIQUE (external_id);
