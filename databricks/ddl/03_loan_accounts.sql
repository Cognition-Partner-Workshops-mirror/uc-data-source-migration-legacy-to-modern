-- =============================================================================
-- Delta Lake Table: loan_accounts
-- =============================================================================
-- Source: CDW_LN_ACCT (legacy denormalized loan accounts table)
-- Migration: Denormalized borrower columns (BORR_FST_NM, BORR_LST_NM,
--            BORR_SSN_LST4) are dropped; borrower reference is via FK to
--            the borrowers dimension table. PROD_CD resolved to product FK.
--            Status codes expanded (ACT→ACTIVE, CLO→CLOSED, etc.).
--            Property type codes expanded (SFR→Single Family, etc.).
-- Partitioning: By status — most operational queries filter on loan status
--               (e.g., active vs. closed vs. default portfolios).
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,
    account_number      STRING          NOT NULL    COMMENT 'Mapped from LN_ACCT_NBR',
    borrower_id         BIGINT          NOT NULL    COMMENT 'FK to borrowers.id; resolved from BORR_ID via external_id lookup',
    product_id          BIGINT          NOT NULL    COMMENT 'FK to loan_products.id; resolved from PROD_CD via code lookup',
    original_amount     DECIMAL(12, 2)  NOT NULL    COMMENT 'Parsed from LN_ORIG_AMT (comma-formatted string)',
    current_balance     DECIMAL(12, 2)  NOT NULL    COMMENT 'Parsed from LN_CURR_BAL (comma-formatted string)',
    interest_rate       DECIMAL(5, 3)   NOT NULL    COMMENT 'Parsed from LN_INT_RT (string like "5.250")',
    term_months         INT             NOT NULL    COMMENT 'Parsed from LN_TERM_MOS (string to integer)',
    monthly_payment     DECIMAL(10, 2)  NOT NULL    COMMENT 'Parsed from LN_PMT_AMT (comma-formatted string)',
    origination_date    DATE            NOT NULL    COMMENT 'Parsed from LN_ORIG_DT (MM/DD/YYYY string)',
    maturity_date       DATE            NOT NULL    COMMENT 'Parsed from LN_MAT_DT (MM/DD/YYYY string)',
    first_payment_date  DATE                        COMMENT 'Parsed from LN_1ST_PMT_DT (MM/DD/YYYY string)',
    next_payment_date   DATE                        COMMENT 'Parsed from LN_NXT_PMT_DT (MM/DD/YYYY string)',
    status              STRING          NOT NULL DEFAULT 'ACTIVE'
                                                    COMMENT 'Expanded from LN_STAT_CD: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE',
    delinquency_days    INT             DEFAULT 0   COMMENT 'Parsed from LN_DLQ_DAYS (string to integer)',
    escrow_balance      DECIMAL(10, 2)  DEFAULT 0   COMMENT 'Parsed from LN_ESCROW_BAL (comma-formatted string)',
    ltv_percent         DECIMAL(5, 2)               COMMENT 'Parsed from LN_LTV_PCT (string like "82.5")',
    property_address    STRING                      COMMENT 'Mapped from PROP_ADDR_LN1',
    property_city       STRING                      COMMENT 'Mapped from PROP_CTY_NM',
    property_state      STRING                      COMMENT 'Mapped from PROP_ST_CD (2-char state code)',
    property_zip        STRING                      COMMENT 'Mapped from PROP_ZIP_CD',
    property_type       STRING                      COMMENT 'Expanded from PROP_TYP_CD: SFR→Single Family, CND→Condominium, MFR→Multi-Family, TWN→Townhouse',
    appraised_value     DECIMAL(12, 2)              COMMENT 'Parsed from PROP_APRS_VAL (comma-formatted string)',
    created_at          TIMESTAMP                   COMMENT 'Parsed from LN_CRET_DT (MM/DD/YYYY string)',
    updated_at          TIMESTAMP                   COMMENT 'Parsed from LN_UPDT_DT (MM/DD/YYYY string)',

    CONSTRAINT pk_loan_accounts PRIMARY KEY (id),
    CONSTRAINT fk_loan_accounts_borrower FOREIGN KEY (borrower_id) REFERENCES loan_warehouse.borrowers(id),
    CONSTRAINT fk_loan_accounts_product  FOREIGN KEY (product_id)  REFERENCES loan_warehouse.loan_products(id)
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Normalized loan accounts table migrated from legacy CDW_LN_ACCT (denormalized borrower columns removed)'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'quality'                          = 'gold'
);

-- Unique constraint on legacy account number for cross-reference lookups
ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT uq_loan_accounts_account_number UNIQUE (account_number);
