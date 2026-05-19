-- =============================================================================
-- Delta Lake Table: borrowers
-- =============================================================================
-- Source: CDW_BORR_MSTR (legacy borrower master table)
-- 
-- Migration notes:
--   - Replaces all-VARCHAR columns with proper Spark SQL types
--   - Maps cryptic legacy names to readable modern names
--     (e.g., BORR_FST_NM -> first_name, BORR_CRDT_SCR -> credit_score)
--   - BORR_REC_TYP column is intentionally dropped (not needed in modern schema)
--   - Status codes expanded: ACT -> ACTIVE, INA -> INACTIVE
--   - Dates converted from MM/DD/YYYY strings to DATE/TIMESTAMP types
--   - Annual income parsed from comma-formatted string to DECIMAL
--   - Credit score parsed from string to INT
--   - Partitioned by status for efficient filtering on active/inactive borrowers
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_management.borrowers (
    -- Surrogate primary key (auto-generated in Delta Lake via IDENTITY)
    id                  BIGINT GENERATED ALWAYS AS IDENTITY,

    -- Legacy BORR_ID preserved as natural key for traceability
    external_id         STRING        NOT NULL,

    -- Borrower name fields (from BORR_FST_NM, BORR_LST_NM, BORR_MID_INIT)
    first_name          STRING        NOT NULL,
    last_name           STRING        NOT NULL,
    middle_initial      STRING,

    -- Encrypted SSN carried over (re-encryption recommended post-migration)
    ssn_hash            STRING,

    -- Date of birth: parsed from MM/DD/YYYY string to DATE
    date_of_birth       DATE,

    -- Address fields (direct copy from legacy BORR_ADDR_* columns)
    address_line1       STRING,
    address_line2       STRING,
    city                STRING,
    state               STRING,
    zip_code            STRING,

    -- Contact info (from BORR_PH_NBR, BORR_EMAIL_ADDR)
    phone               STRING,
    email               STRING,

    -- Credit score: parsed from VARCHAR(5) string to INT
    credit_score        INT,

    -- Employment status (direct copy from BORR_EMP_STAT)
    employment_status   STRING,

    -- Annual income: parsed from comma-formatted string (e.g., "92,500") to DECIMAL
    annual_income       DECIMAL(12, 2),

    -- Status: expanded from abbreviation (ACT -> ACTIVE, INA -> INACTIVE)
    status              STRING        DEFAULT 'ACTIVE',

    -- Audit timestamps: parsed from MM/DD/YYYY strings to TIMESTAMP
    created_at          TIMESTAMP     DEFAULT current_timestamp(),
    updated_at          TIMESTAMP     DEFAULT current_timestamp(),

    -- Primary key constraint for Delta Lake (informational, not enforced)
    CONSTRAINT pk_borrowers PRIMARY KEY (id)
)
USING DELTA
-- Partition by status for efficient queries on active vs. inactive borrowers
PARTITIONED BY (status)
COMMENT 'Modern borrower dimension table migrated from legacy CDW_BORR_MSTR. Contains normalized borrower demographics, contact info, and credit data.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true',
    'delta.columnMapping.mode' = 'name',
    'delta.minReaderVersion' = '2',
    'delta.minWriterVersion' = '5'
);
