-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy Core Data Warehouse)
-- =============================================================================
-- Borrower dimension table. Separated from loan accounts to eliminate the
-- denormalized borrower fields that were embedded in CDW_LN_ACCT.
-- Partitioned by state to support regional analytics and compliance reporting.
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
    _load_ts            TIMESTAMP       DEFAULT current_timestamp(),
    _source_system      STRING          DEFAULT 'CDW_BORR_MSTR',

    CONSTRAINT pk_borrowers PRIMARY KEY (borrower_id),
    CONSTRAINT uq_borrowers_ext UNIQUE (external_id)
)
USING DELTA
PARTITIONED BY (state)
COMMENT 'Borrower dimension table migrated from CDW_BORR_MSTR. Partitioned by state for regional query performance.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.minReaderVersion'           = '1',
    'delta.minWriterVersion'           = '2'
);
