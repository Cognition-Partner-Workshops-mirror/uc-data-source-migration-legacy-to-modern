-- =============================================================================
-- Delta Lake Table: borrowers (dimension table)
-- Source: CDW_BORR_MSTR
-- =============================================================================
-- Borrower dimension table with proper data types, meaningful column names,
-- and partitioning by state for geographic query optimization.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    borrower_id       BIGINT GENERATED ALWAYS AS IDENTITY,
    external_id       STRING NOT NULL,
    first_name        STRING NOT NULL,
    last_name         STRING NOT NULL,
    middle_initial    STRING,
    ssn_hash          STRING,
    date_of_birth     DATE,
    address_line1     STRING,
    address_line2     STRING,
    city              STRING,
    state             STRING,
    zip_code          STRING,
    phone             STRING,
    email             STRING,
    credit_score      INT,
    employment_status STRING,
    annual_income     DECIMAL(12, 2),
    status            STRING NOT NULL,
    created_at        TIMESTAMP,
    updated_at        TIMESTAMP,
    _ingestion_ts     TIMESTAMP DEFAULT current_timestamp(),
    _source_system    STRING DEFAULT 'CDW_LEGACY'
)
USING DELTA
PARTITIONED BY (state)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
)
COMMENT 'Borrower dimension table migrated from legacy CDW_BORR_MSTR. Partitioned by state for geographic query patterns.';

-- Constraints
ALTER TABLE loan_warehouse.borrowers
ADD CONSTRAINT borrowers_external_id_unique UNIQUE (external_id);

ALTER TABLE loan_warehouse.borrowers
ADD CONSTRAINT borrowers_status_check CHECK (status IN ('ACTIVE', 'INACTIVE'));

ALTER TABLE loan_warehouse.borrowers
ADD CONSTRAINT borrowers_credit_score_range CHECK (credit_score IS NULL OR (credit_score >= 300 AND credit_score <= 850));
