-- =============================================================================
-- Delta Lake Table: borrowers (dimension table)
-- Source: CDW_BORR_MSTR (Legacy Borrower Master)
-- =============================================================================
-- Migrated from the legacy CDW_BORR_MSTR table. All VARCHAR columns are now
-- typed correctly (DATE, INT, DECIMAL). The BORR_REC_TYP column is dropped
-- as it has no business value in the modern schema. Status codes are expanded
-- from abbreviations (ACT→ACTIVE, INA→INACTIVE) during ingestion.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    -- Surrogate key generated during ingestion
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,

    -- Legacy BORR_ID preserved as a natural key for traceability
    external_id         STRING          NOT NULL
        COMMENT 'Legacy BORR_ID from CDW_BORR_MSTR',

    -- Borrower identity fields (legacy: BORR_FST_NM, BORR_LST_NM, BORR_MID_INIT)
    first_name          STRING          NOT NULL
        COMMENT 'Borrower first name',
    last_name           STRING          NOT NULL
        COMMENT 'Borrower last name',
    middle_initial      STRING
        COMMENT 'Single-character middle initial',

    -- Sensitive field (legacy: BORR_SSN_ENCR) — kept encrypted, re-encrypt recommended
    ssn_hash            STRING
        COMMENT 'Encrypted SSN carried over from legacy; re-encryption recommended',

    -- Parsed from MM/DD/YYYY string (legacy: BORR_DOB_DT)
    date_of_birth       DATE
        COMMENT 'Date of birth, parsed from legacy MM/DD/YYYY string',

    -- Address fields (legacy: BORR_ADDR_LN1, BORR_ADDR_LN2, BORR_CTY_NM, BORR_ST_CD, BORR_ZIP_CD)
    address_line1       STRING,
    address_line2       STRING,
    city                STRING,
    state               STRING          COMMENT 'Two-letter state code',
    zip_code            STRING,

    -- Contact (legacy: BORR_PH_NBR, BORR_EMAIL_ADDR)
    phone               STRING,
    email               STRING,

    -- Parsed from VARCHAR to INT (legacy: BORR_CRDT_SCR)
    credit_score        INT
        COMMENT 'Numeric credit score, parsed from legacy VARCHAR',

    -- Employment (legacy: BORR_EMP_STAT)
    employment_status   STRING,

    -- Parsed from comma-formatted string e.g. "92,500" (legacy: BORR_ANN_INCM)
    annual_income       DECIMAL(12, 2)
        COMMENT 'Annual income, parsed from legacy comma-formatted string',

    -- Expanded from abbreviation (ACT→ACTIVE, INA→INACTIVE) (legacy: BORR_STAT_CD)
    status              STRING          DEFAULT 'ACTIVE'
        COMMENT 'Borrower status: ACTIVE or INACTIVE',

    -- Parsed from MM/DD/YYYY strings (legacy: BORR_CRET_DT, BORR_UPDT_DT)
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,

    -- Audit column added during migration
    _migration_ts       TIMESTAMP       DEFAULT current_timestamp()
        COMMENT 'Timestamp when the row was loaded by the migration pipeline'
)
USING DELTA
COMMENT 'Modern borrower dimension table migrated from legacy CDW_BORR_MSTR'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);

-- Unique constraint on legacy ID for FK lookups during loan_accounts ingestion
ALTER TABLE loan_warehouse.borrowers
    ADD CONSTRAINT borrowers_external_id_unique UNIQUE (external_id);
