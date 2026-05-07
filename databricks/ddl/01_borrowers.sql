-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (legacy)
-- =============================================================================
-- Normalized borrower dimension table with proper Spark SQL types.
-- Partitioned by state for geographic query patterns.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    borrower_key        BIGINT          GENERATED ALWAYS AS IDENTITY,
    external_id         STRING          NOT NULL COMMENT 'Legacy BORR_ID (e.g. B-10001)',
    first_name          STRING          NOT NULL COMMENT 'Mapped from BORR_FST_NM',
    last_name           STRING          NOT NULL COMMENT 'Mapped from BORR_LST_NM',
    middle_initial      STRING          COMMENT 'Mapped from BORR_MID_INIT',
    ssn_hash            STRING          COMMENT 'Mapped from BORR_SSN_ENCR — re-encrypt recommended',
    date_of_birth       DATE            COMMENT 'Parsed from BORR_DOB_DT (MM/DD/YYYY)',
    address_line1       STRING          COMMENT 'Mapped from BORR_ADDR_LN1',
    address_line2       STRING          COMMENT 'Mapped from BORR_ADDR_LN2',
    city                STRING          COMMENT 'Mapped from BORR_CTY_NM',
    state               STRING          COMMENT 'Mapped from BORR_ST_CD (2-char state code)',
    zip_code            STRING          COMMENT 'Mapped from BORR_ZIP_CD',
    phone               STRING          COMMENT 'Mapped from BORR_PH_NBR',
    email               STRING          COMMENT 'Mapped from BORR_EMAIL_ADDR',
    credit_score        INT             COMMENT 'Parsed from BORR_CRDT_SCR (string to int)',
    employment_status   STRING          COMMENT 'Mapped from BORR_EMP_STAT',
    annual_income       DECIMAL(12, 2)  COMMENT 'Parsed from BORR_ANN_INCM (remove commas)',
    status              STRING          NOT NULL DEFAULT 'Active' COMMENT 'Expanded from BORR_STAT_CD: ACT→Active, INA→Inactive',
    created_at          TIMESTAMP       COMMENT 'Parsed from BORR_CRET_DT (MM/DD/YYYY)',
    updated_at          TIMESTAMP       COMMENT 'Parsed from BORR_UPDT_DT (MM/DD/YYYY)',
    _migration_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Timestamp of migration load',
    _source_system      STRING          DEFAULT 'CDW_BORR_MSTR' COMMENT 'Source table identifier',

    CONSTRAINT borrowers_pk PRIMARY KEY (borrower_key),
    CONSTRAINT borrowers_external_id_uq UNIQUE (external_id)
)
USING DELTA
PARTITIONED BY (state)
COMMENT 'Borrower dimension table — migrated from legacy CDW_BORR_MSTR'
TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'true',
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
