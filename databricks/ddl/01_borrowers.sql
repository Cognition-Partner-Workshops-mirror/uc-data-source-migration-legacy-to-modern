-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy Borrower Master)
-- =============================================================================
-- Normalized borrower dimension table with proper data types.
-- Partitioned by state for geographic query optimization.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,
    external_id         STRING NOT NULL COMMENT 'Legacy BORR_ID (e.g., B-10001)',
    first_name          STRING NOT NULL,
    last_name           STRING NOT NULL,
    middle_initial      STRING,
    ssn_hash            STRING COMMENT 'Encrypted SSN carried from legacy; re-encryption recommended',
    date_of_birth       DATE COMMENT 'Parsed from MM/DD/YYYY string',
    address_line1       STRING,
    address_line2       STRING,
    city                STRING,
    state               STRING COMMENT 'Two-letter state code',
    zip_code            STRING,
    phone               STRING,
    email               STRING,
    credit_score        INT COMMENT 'Parsed from VARCHAR string',
    employment_status   STRING,
    annual_income       DECIMAL(12, 2) COMMENT 'Parsed from comma-formatted string',
    status              STRING NOT NULL COMMENT 'Expanded from legacy codes: ACT->ACTIVE, INA->INACTIVE',
    created_at          TIMESTAMP COMMENT 'Parsed from MM/DD/YYYY string',
    updated_at          TIMESTAMP COMMENT 'Parsed from MM/DD/YYYY string',
    _migration_source   STRING DEFAULT 'CDW_BORR_MSTR' COMMENT 'Lineage tracking',
    _migrated_at        TIMESTAMP DEFAULT current_timestamp() COMMENT 'Migration timestamp'
)
USING DELTA
PARTITIONED BY (state)
COMMENT 'Borrower dimension table migrated from legacy CDW_BORR_MSTR'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'quality.constraints.external_id_not_null' = 'external_id IS NOT NULL',
    'quality.constraints.name_not_null' = 'first_name IS NOT NULL AND last_name IS NOT NULL'
);
