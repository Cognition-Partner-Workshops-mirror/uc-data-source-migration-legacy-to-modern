-- =============================================================================
-- Delta Lake: borrowers table
-- Source: CDW_BORR_MSTR (legacy)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,
    external_id         STRING          NOT NULL COMMENT 'Legacy BORR_ID',
    first_name          STRING          NOT NULL,
    last_name           STRING          NOT NULL,
    middle_initial      STRING,
    ssn_hash            STRING          NOT NULL COMMENT 'Re-encrypt recommended',
    date_of_birth       DATE            COMMENT 'Parsed from MM/DD/YYYY',
    address_line1       STRING,
    address_line2       STRING,
    city                STRING,
    state               STRING          COMMENT '2-letter state code',
    zip_code            STRING,
    phone               STRING,
    email               STRING,
    credit_score        INT             COMMENT 'Valid range 300-850',
    employment_status   STRING,
    annual_income       DECIMAL(12,2)   COMMENT 'Parsed from comma-formatted string',
    status              STRING          NOT NULL COMMENT 'ACTIVE or INACTIVE (expanded from ACT/INA)',
    created_at          TIMESTAMP       COMMENT 'Parsed from MM/DD/YYYY',
    updated_at          TIMESTAMP       COMMENT 'Parsed from MM/DD/YYYY',

    CONSTRAINT borrowers_pk PRIMARY KEY (id)
)
USING DELTA
COMMENT 'Normalized borrower master data migrated from CDW_BORR_MSTR'
TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'true',
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);

CREATE INDEX IF NOT EXISTS idx_borrowers_external_id
ON loan_warehouse.borrowers (external_id);
