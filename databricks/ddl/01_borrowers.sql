-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy Borrower Master)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_management.borrowers (
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
    status              STRING NOT NULL,
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,

    CONSTRAINT pk_borrowers PRIMARY KEY (id)
)
USING DELTA
COMMENT 'Borrower dimension table migrated from CDW_BORR_MSTR'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
)
PARTITIONED BY (state);
