-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Loan Accounts)
-- =============================================================================
-- Core fact table for loan accounts. Denormalized borrower fields from the
-- legacy table (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) are dropped;
-- borrower data is accessed via borrower_external_id join to borrowers table.
--
-- Partitioned by origination_year (derived from LN_ORIG_DT) to optimize
-- time-range queries on loan portfolios and support efficient data lifecycle
-- management (e.g., archiving old vintages).
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_key                BIGINT          GENERATED ALWAYS AS IDENTITY,
    account_number          STRING          NOT NULL    COMMENT 'Loan account number (was LN_ACCT_NBR)',
    borrower_external_id    STRING          NOT NULL    COMMENT 'FK to borrowers.external_id (was BORR_ID)',
    product_code            STRING          NOT NULL    COMMENT 'FK to loan_products.code (was PROD_CD)',
    original_amount         DECIMAL(12, 2)  NOT NULL    COMMENT 'Original loan amount, parsed from comma string (was LN_ORIG_AMT)',
    current_balance         DECIMAL(12, 2)  NOT NULL    COMMENT 'Current balance, parsed from comma string (was LN_CURR_BAL)',
    interest_rate           DECIMAL(5, 3)   NOT NULL    COMMENT 'Interest rate, parsed from string (was LN_INT_RT)',
    term_months             INT             NOT NULL    COMMENT 'Loan term in months, parsed from VARCHAR (was LN_TERM_MOS)',
    monthly_payment         DECIMAL(10, 2)  NOT NULL    COMMENT 'Monthly payment, parsed from comma string (was LN_PMT_AMT)',
    origination_date        DATE            NOT NULL    COMMENT 'Origination date, parsed from MM/DD/YYYY (was LN_ORIG_DT)',
    maturity_date           DATE            NOT NULL    COMMENT 'Maturity date, parsed from MM/DD/YYYY (was LN_MAT_DT)',
    first_payment_date      DATE                        COMMENT 'First payment date, parsed from MM/DD/YYYY (was LN_1ST_PMT_DT)',
    next_payment_date       DATE                        COMMENT 'Next payment due date, parsed from MM/DD/YYYY (was LN_NXT_PMT_DT)',
    status                  STRING          NOT NULL    COMMENT 'Expanded status: ACT->Active, CLO->Closed, DFT->Default, FRB->Forbearance (was LN_STAT_CD)',
    delinquency_days        INT             DEFAULT 0   COMMENT 'Days delinquent, parsed from VARCHAR (was LN_DLQ_DAYS)',
    escrow_balance          DECIMAL(10, 2)  DEFAULT 0   COMMENT 'Escrow balance, parsed from comma string (was LN_ESCROW_BAL)',
    ltv_percent             DECIMAL(5, 2)               COMMENT 'Loan-to-value ratio, parsed from string (was LN_LTV_PCT)',
    property_address        STRING                      COMMENT 'Property address (was PROP_ADDR_LN1)',
    property_city           STRING                      COMMENT 'Property city (was PROP_CTY_NM)',
    property_state          STRING                      COMMENT 'Property state code (was PROP_ST_CD)',
    property_zip            STRING                      COMMENT 'Property ZIP code (was PROP_ZIP_CD)',
    property_type           STRING                      COMMENT 'Expanded type: SFR->Single Family, CND->Condominium, MFR->Multi-Family, TWN->Townhouse (was PROP_TYP_CD)',
    appraised_value         DECIMAL(12, 2)              COMMENT 'Appraised property value, parsed from comma string (was PROP_APRS_VAL)',
    created_at              TIMESTAMP                   COMMENT 'Record creation timestamp, parsed from MM/DD/YYYY (was LN_CRET_DT)',
    updated_at              TIMESTAMP                   COMMENT 'Last update timestamp, parsed from MM/DD/YYYY (was LN_UPDT_DT)',
    origination_year        INT                         COMMENT 'Partition key derived from origination_date year',
    _migration_source       STRING          DEFAULT 'CDW_LN_ACCT' COMMENT 'Source table for lineage tracking',
    _migrated_at            TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Timestamp of migration run'
)
USING DELTA
PARTITIONED BY (origination_year)
COMMENT 'Loan accounts fact table migrated from legacy CDW_LN_ACCT. Denormalized borrower fields removed; use borrower_external_id to join to borrowers table.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.deletedFileRetentionDuration' = 'interval 30 days',
    'delta.logRetentionDuration'       = 'interval 90 days'
);

-- Unique constraint on account number
ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_acct_nbr_unique UNIQUE (account_number);
