-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy Corporate Data Warehouse)
-- =============================================================================
-- Normalized borrower dimension table with proper data types.
-- Partitioned by state to optimize geographic queries common in loan servicing.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    -- Primary key (auto-generated surrogate key)
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,

    -- Legacy reference identifier (CDW_BORR_MSTR.BORR_ID)
    external_id         STRING NOT NULL,

    -- Borrower name fields
    first_name          STRING NOT NULL,
    last_name           STRING NOT NULL,
    middle_initial      STRING,

    -- Sensitive data (encrypted SSN carried over, re-encryption recommended)
    ssn_hash            STRING,

    -- Demographics
    date_of_birth       DATE,

    -- Address fields
    address_line1       STRING,
    address_line2       STRING,
    city                STRING,
    state               STRING,
    zip_code            STRING,

    -- Contact information
    phone               STRING,
    email               STRING,

    -- Financial profile
    credit_score        INT,
    employment_status   STRING,
    annual_income       DECIMAL(12, 2),

    -- Status (expanded from legacy codes: ACT→Active, INA→Inactive)
    status              STRING DEFAULT 'Active',

    -- Audit timestamps (parsed from legacy MM/DD/YYYY strings)
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,

    -- Constraints
    CONSTRAINT pk_borrowers PRIMARY KEY (id),
    CONSTRAINT uq_borrowers_external_id UNIQUE (external_id)
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
COMMENT 'Borrower dimension table migrated from legacy CDW_BORR_MSTR. Contains normalized borrower demographics, contact info, and financial profile.';
