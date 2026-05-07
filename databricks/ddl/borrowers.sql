-- =============================================================================
-- Delta Lake DDL: borrowers
-- Source: CDW_BORR_MSTR (Legacy CDW)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    external_id         STRING          NOT NULL    COMMENT 'Legacy: BORR_ID — unique borrower identifier',
    first_name          STRING          NOT NULL    COMMENT 'Legacy: BORR_FST_NM — borrower first name',
    last_name           STRING          NOT NULL    COMMENT 'Legacy: BORR_LST_NM — borrower last name',
    middle_initial      STRING                      COMMENT 'Legacy: BORR_MID_INIT — middle initial',
    ssn_hash            STRING                      COMMENT 'Legacy: BORR_SSN_ENCR — encrypted SSN (re-encrypt recommended)',
    date_of_birth       DATE                        COMMENT 'Legacy: BORR_DOB_DT — parsed from MM/DD/YYYY string',
    address_line1       STRING                      COMMENT 'Legacy: BORR_ADDR_LN1 — street address line 1',
    address_line2       STRING                      COMMENT 'Legacy: BORR_ADDR_LN2 — street address line 2',
    city                STRING                      COMMENT 'Legacy: BORR_CTY_NM — city name',
    state               STRING                      COMMENT 'Legacy: BORR_ST_CD — two-letter state code',
    zip_code            STRING                      COMMENT 'Legacy: BORR_ZIP_CD — ZIP code',
    phone               STRING                      COMMENT 'Legacy: BORR_PH_NBR — phone number',
    email               STRING                      COMMENT 'Legacy: BORR_EMAIL_ADDR — email address',
    credit_score        INT                         COMMENT 'Legacy: BORR_CRDT_SCR — parsed from VARCHAR to integer',
    employment_status   STRING                      COMMENT 'Legacy: BORR_EMP_STAT — employment status',
    annual_income       DECIMAL(12, 2)              COMMENT 'Legacy: BORR_ANN_INCM — parsed from comma-formatted string',
    status              STRING                      COMMENT 'Legacy: BORR_STAT_CD — expanded from ACT/INA to ACTIVE/INACTIVE',
    created_at          TIMESTAMP                   COMMENT 'Legacy: BORR_CRET_DT — parsed from MM/DD/YYYY string',
    updated_at          TIMESTAMP                   COMMENT 'Legacy: BORR_UPDT_DT — parsed from MM/DD/YYYY string',
    _migration_source   STRING                      COMMENT 'Source system identifier for lineage tracking',
    _migrated_at        TIMESTAMP                   COMMENT 'Timestamp when record was migrated'
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Borrower master data migrated from CDW_BORR_MSTR. Partitioned by status for common filter queries on active/inactive borrowers.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
