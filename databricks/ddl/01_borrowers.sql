-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy Corporate Data Warehouse)
-- =============================================================================
-- Borrower dimension table extracted from the legacy borrower master.
-- Partitioned by state to support regional loan portfolio analysis.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    borrower_id         BIGINT          GENERATED ALWAYS AS IDENTITY,
    external_id         STRING          NOT NULL COMMENT 'Legacy BORR_ID (e.g. B-10001)',
    first_name          STRING          NOT NULL COMMENT 'Legacy BORR_FST_NM',
    last_name           STRING          NOT NULL COMMENT 'Legacy BORR_LST_NM',
    middle_initial      STRING          COMMENT 'Legacy BORR_MID_INIT',
    ssn_hash            STRING          COMMENT 'Legacy BORR_SSN_ENCR — re-encryption recommended',
    date_of_birth       DATE            COMMENT 'Legacy BORR_DOB_DT — parsed from MM/DD/YYYY',
    address_line1       STRING          COMMENT 'Legacy BORR_ADDR_LN1',
    address_line2       STRING          COMMENT 'Legacy BORR_ADDR_LN2',
    city                STRING          COMMENT 'Legacy BORR_CTY_NM',
    state               STRING          COMMENT 'Legacy BORR_ST_CD (2-letter)',
    zip_code            STRING          COMMENT 'Legacy BORR_ZIP_CD',
    phone               STRING          COMMENT 'Legacy BORR_PH_NBR',
    email               STRING          COMMENT 'Legacy BORR_EMAIL_ADDR',
    credit_score        INT             COMMENT 'Legacy BORR_CRDT_SCR — parsed from string',
    employment_status   STRING          COMMENT 'Legacy BORR_EMP_STAT',
    annual_income       DECIMAL(12, 2)  COMMENT 'Legacy BORR_ANN_INCM — parsed, commas removed',
    status              STRING          NOT NULL DEFAULT 'Active' COMMENT 'Legacy BORR_STAT_CD expanded: ACT→Active, INA→Inactive',
    created_at          TIMESTAMP       COMMENT 'Legacy BORR_CRET_DT — parsed from MM/DD/YYYY',
    updated_at          TIMESTAMP       COMMENT 'Legacy BORR_UPDT_DT — parsed from MM/DD/YYYY',
    _migration_source   STRING          DEFAULT 'CDW_BORR_MSTR' COMMENT 'Lineage: source table',
    _migration_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Lineage: ingestion timestamp',

    CONSTRAINT borrowers_pk PRIMARY KEY (borrower_id),
    CONSTRAINT borrowers_external_id_uq UNIQUE (external_id)
)
USING DELTA
PARTITIONED BY (state)
COMMENT 'Modern borrower dimension — migrated from CDW_BORR_MSTR'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.enableChangeDataFeed'       = 'true'
);
