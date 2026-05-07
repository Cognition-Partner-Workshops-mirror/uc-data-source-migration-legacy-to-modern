-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR (Legacy Borrower Master)
-- =============================================================================
-- Normalized borrower dimension table with proper data types.
-- Partitioned by status to optimize queries filtering on active/inactive borrowers.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    borrower_key        BIGINT          GENERATED ALWAYS AS IDENTITY,
    external_id         STRING          NOT NULL    COMMENT 'Legacy BORR_ID (e.g. B-10001)',
    first_name          STRING          NOT NULL    COMMENT 'Legacy BORR_FST_NM',
    last_name           STRING          NOT NULL    COMMENT 'Legacy BORR_LST_NM',
    middle_initial      STRING                      COMMENT 'Legacy BORR_MID_INIT',
    ssn_hash            STRING                      COMMENT 'Legacy BORR_SSN_ENCR (re-encrypt recommended)',
    date_of_birth       DATE                        COMMENT 'Legacy BORR_DOB_DT parsed from MM/DD/YYYY',
    address_line1       STRING                      COMMENT 'Legacy BORR_ADDR_LN1',
    address_line2       STRING                      COMMENT 'Legacy BORR_ADDR_LN2',
    city                STRING                      COMMENT 'Legacy BORR_CTY_NM',
    state               STRING                      COMMENT 'Legacy BORR_ST_CD (2-char state code)',
    zip_code            STRING                      COMMENT 'Legacy BORR_ZIP_CD',
    phone               STRING                      COMMENT 'Legacy BORR_PH_NBR',
    email               STRING                      COMMENT 'Legacy BORR_EMAIL_ADDR',
    credit_score        INT                         COMMENT 'Legacy BORR_CRDT_SCR parsed from VARCHAR',
    employment_status   STRING                      COMMENT 'Legacy BORR_EMP_STAT',
    annual_income       DECIMAL(12, 2)              COMMENT 'Legacy BORR_ANN_INCM parsed from comma-formatted string',
    status              STRING          NOT NULL DEFAULT 'ACTIVE'
                                                    COMMENT 'Legacy BORR_STAT_CD expanded: ACT->ACTIVE, INA->INACTIVE',
    created_at          TIMESTAMP                   COMMENT 'Legacy BORR_CRET_DT parsed from MM/DD/YYYY',
    updated_at          TIMESTAMP                   COMMENT 'Legacy BORR_UPDT_DT parsed from MM/DD/YYYY',
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp()
                                                    COMMENT 'Pipeline ingestion timestamp',

    CONSTRAINT borrowers_pk PRIMARY KEY (borrower_key)
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Normalized borrower dimension table migrated from CDW_BORR_MSTR'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);

-- Unique constraint on legacy external ID
ALTER TABLE loan_warehouse.borrowers
    ADD CONSTRAINT borrowers_external_id_uq UNIQUE (external_id);
