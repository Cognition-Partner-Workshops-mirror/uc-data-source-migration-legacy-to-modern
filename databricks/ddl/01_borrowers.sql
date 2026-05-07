-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy Corporate Data Warehouse)
-- =============================================================================
-- Mapping reference: data/mappings/column_mappings.md § CDW_BORR_MSTR → borrowers
-- Partitioned by status for efficient filtering of active vs inactive borrowers.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    borrower_id         BIGINT          GENERATED ALWAYS AS IDENTITY,
    external_id         STRING          NOT NULL COMMENT 'Legacy BORR_ID (e.g., B-10001)',
    first_name          STRING          NOT NULL COMMENT 'Legacy BORR_FST_NM',
    last_name           STRING          NOT NULL COMMENT 'Legacy BORR_LST_NM',
    middle_initial      STRING          COMMENT 'Legacy BORR_MID_INIT, nullable',
    ssn_hash            STRING          COMMENT 'Legacy BORR_SSN_ENCR, re-encryption recommended',
    date_of_birth       DATE            COMMENT 'Legacy BORR_DOB_DT, parsed from MM/DD/YYYY',
    address_line1       STRING          COMMENT 'Legacy BORR_ADDR_LN1',
    address_line2       STRING          COMMENT 'Legacy BORR_ADDR_LN2, nullable',
    city                STRING          COMMENT 'Legacy BORR_CTY_NM',
    state               STRING          COMMENT 'Legacy BORR_ST_CD, 2-char state code',
    zip_code            STRING          COMMENT 'Legacy BORR_ZIP_CD',
    phone               STRING          COMMENT 'Legacy BORR_PH_NBR',
    email               STRING          COMMENT 'Legacy BORR_EMAIL_ADDR',
    credit_score        INT             COMMENT 'Legacy BORR_CRDT_SCR, parsed from VARCHAR',
    employment_status   STRING          COMMENT 'Legacy BORR_EMP_STAT',
    annual_income       DECIMAL(12, 2)  COMMENT 'Legacy BORR_ANN_INCM, parsed from comma-formatted string',
    status              STRING          NOT NULL COMMENT 'Expanded from BORR_STAT_CD: ACT→ACTIVE, INA→INACTIVE',
    created_at          TIMESTAMP       COMMENT 'Legacy BORR_CRET_DT, parsed from MM/DD/YYYY',
    updated_at          TIMESTAMP       COMMENT 'Legacy BORR_UPDT_DT, parsed from MM/DD/YYYY',
    _ingested_at        TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp',
    _source_system      STRING          DEFAULT 'CDW_BORR_MSTR' COMMENT 'Source system identifier'
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Borrower master data migrated from legacy CDW_BORR_MSTR table'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
