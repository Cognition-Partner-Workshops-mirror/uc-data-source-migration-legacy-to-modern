-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy)
-- =============================================================================
-- Normalized borrower dimension extracted from the legacy borrower master table.
-- Partitioned by state for geographic query patterns common in loan servicing.
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
    status              STRING        DEFAULT 'Active',
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    _migration_source   STRING        DEFAULT 'CDW_BORR_MSTR',
    _migrated_at        TIMESTAMP     DEFAULT current_timestamp()
)
USING DELTA
PARTITIONED BY (state)
COMMENT 'Modern borrower dimension table migrated from CDW_BORR_MSTR'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.tier'                     = 'gold'
);

ALTER TABLE loan_warehouse.borrowers
    ADD CONSTRAINT borrowers_external_id_unique UNIQUE (external_id);

ALTER TABLE loan_warehouse.borrowers
    ADD CONSTRAINT borrowers_credit_score_range
    CHECK (credit_score IS NULL OR (credit_score >= 300 AND credit_score <= 850));

ALTER TABLE loan_warehouse.borrowers
    ADD CONSTRAINT borrowers_status_values
    CHECK (status IN ('Active', 'Inactive'));
