-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (legacy)
-- =============================================================================
-- Borrower dimension table with proper types, replacing the all-VARCHAR legacy
-- table. Partitioned by state for geographic query patterns common in loan ops.
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
    status              STRING          NOT NULL DEFAULT 'Active',
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    _migration_source   STRING          DEFAULT 'CDW_BORR_MSTR',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
COMMENT 'Borrower dimension table migrated from legacy CDW_BORR_MSTR'
PARTITIONED BY (state)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.expectation.external_id'  = 'external_id IS NOT NULL',
    'quality.expectation.first_name'   = 'first_name IS NOT NULL',
    'quality.expectation.last_name'    = 'last_name IS NOT NULL'
);

-- Indexes / Z-ORDER recommendation (run post-load):
-- OPTIMIZE loan_warehouse.borrowers ZORDER BY (external_id, email);
