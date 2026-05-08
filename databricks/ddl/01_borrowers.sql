-- =============================================================================
-- Delta Lake Table: borrowers
-- =============================================================================
-- Source: CDW_BORR_MSTR (legacy borrower master table)
-- Migration: Cryptic column names mapped to readable names, VARCHAR-everything
--            converted to proper Spark SQL types, BORR_REC_TYP dropped as
--            it has no business value in the modern schema.
-- Partitioning: By borrower status to support common filter queries
--               (e.g., "show all active borrowers").
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,
    external_id         STRING          NOT NULL    COMMENT 'Legacy BORR_ID carried forward as natural key',
    first_name          STRING          NOT NULL    COMMENT 'Mapped from BORR_FST_NM',
    last_name           STRING          NOT NULL    COMMENT 'Mapped from BORR_LST_NM',
    middle_initial      STRING                      COMMENT 'Mapped from BORR_MID_INIT',
    ssn_hash            STRING                      COMMENT 'Mapped from BORR_SSN_ENCR; re-encryption recommended',
    date_of_birth       DATE                        COMMENT 'Parsed from BORR_DOB_DT (MM/DD/YYYY string)',
    address_line1       STRING                      COMMENT 'Mapped from BORR_ADDR_LN1',
    address_line2       STRING                      COMMENT 'Mapped from BORR_ADDR_LN2',
    city                STRING                      COMMENT 'Mapped from BORR_CTY_NM',
    state               STRING                      COMMENT 'Mapped from BORR_ST_CD (2-char state code)',
    zip_code            STRING                      COMMENT 'Mapped from BORR_ZIP_CD',
    phone               STRING                      COMMENT 'Mapped from BORR_PH_NBR',
    email               STRING                      COMMENT 'Mapped from BORR_EMAIL_ADDR',
    credit_score        INT                         COMMENT 'Parsed from BORR_CRDT_SCR (string to integer)',
    employment_status   STRING                      COMMENT 'Mapped from BORR_EMP_STAT',
    annual_income       DECIMAL(12, 2)              COMMENT 'Parsed from BORR_ANN_INCM (comma-formatted string)',
    status              STRING          NOT NULL DEFAULT 'ACTIVE'
                                                    COMMENT 'Expanded from BORR_STAT_CD: ACT→ACTIVE, INA→INACTIVE',
    created_at          TIMESTAMP                   COMMENT 'Parsed from BORR_CRET_DT (MM/DD/YYYY string)',
    updated_at          TIMESTAMP                   COMMENT 'Parsed from BORR_UPDT_DT (MM/DD/YYYY string)',

    -- Primary key constraint (informational in Databricks, not enforced)
    CONSTRAINT pk_borrowers PRIMARY KEY (id)
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Modern borrower dimension table migrated from legacy CDW_BORR_MSTR'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'quality'                          = 'gold'
);

-- Unique constraint on the legacy natural key for cross-reference lookups
ALTER TABLE loan_warehouse.borrowers
    ADD CONSTRAINT uq_borrowers_external_id UNIQUE (external_id);
