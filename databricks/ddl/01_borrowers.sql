-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy Corporate Data Warehouse)
-- =============================================================================
-- Normalized borrower dimension table with proper data types.
-- Partitioned by status for efficient filtering of active vs inactive borrowers.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,
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
    created_at          TIMESTAMP DEFAULT current_timestamp(),
    updated_at          TIMESTAMP DEFAULT current_timestamp(),

    CONSTRAINT borrowers_pk PRIMARY KEY (id),
    CONSTRAINT borrowers_external_id_uq UNIQUE (external_id),
    CONSTRAINT borrowers_credit_score_range CHECK (credit_score IS NULL OR (credit_score BETWEEN 300 AND 850)),
    CONSTRAINT borrowers_annual_income_pos CHECK (annual_income IS NULL OR annual_income >= 0),
    CONSTRAINT borrowers_status_values CHECK (status IN ('ACTIVE', 'INACTIVE', 'DECEASED', 'SUSPENDED'))
)
USING DELTA
PARTITIONED BY (status)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
)
COMMENT 'Borrower master table migrated from legacy CDW_BORR_MSTR. Contains one row per borrower with proper types and normalized structure.';
