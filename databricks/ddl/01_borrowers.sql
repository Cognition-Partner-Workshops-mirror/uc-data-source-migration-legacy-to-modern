-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy Borrower Master)
-- =============================================================================
-- Normalized borrower dimension table with proper data types.
-- Partitioned by status to optimize queries filtering active vs inactive borrowers.
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
    status              STRING          NOT NULL DEFAULT 'ACTIVE',
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    _migration_source   STRING          DEFAULT 'CDW_BORR_MSTR',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Borrower dimension table migrated from legacy CDW_BORR_MSTR. Partitioned by status for efficient filtering.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);

-- Constraints
ALTER TABLE loan_warehouse.borrowers
    ADD CONSTRAINT borrowers_external_id_unique EXPECT (external_id IS NOT NULL);

ALTER TABLE loan_warehouse.borrowers
    ADD CONSTRAINT borrowers_credit_score_range EXPECT (credit_score IS NULL OR (credit_score >= 300 AND credit_score <= 850));
