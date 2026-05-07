-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Loan Accounts)
-- =============================================================================
-- Core fact table for loan accounts. Removes denormalized borrower columns
-- (BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4) and replaces them with a
-- foreign key to the borrowers dimension. Converts all VARCHAR amounts and
-- dates to proper typed columns. Partitioned by status for query efficiency
-- since most operational queries filter by loan status (e.g., active loans).
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_account_id     BIGINT          GENERATED ALWAYS AS IDENTITY,
    account_number      STRING          NOT NULL,
    borrower_id         BIGINT          NOT NULL
        COMMENT 'FK to borrowers.borrower_id, resolved from legacy BORR_ID via external_id lookup',
    product_id          BIGINT          NOT NULL
        COMMENT 'FK to loan_products.product_id, resolved from legacy PROD_CD via code lookup',
    original_amount     DECIMAL(12, 2)  NOT NULL,
    current_balance     DECIMAL(12, 2)  NOT NULL,
    interest_rate       DECIMAL(5, 3)   NOT NULL,
    term_months         INT             NOT NULL,
    monthly_payment     DECIMAL(10, 2)  NOT NULL,
    origination_date    DATE            NOT NULL,
    maturity_date       DATE            NOT NULL,
    first_payment_date  DATE,
    next_payment_date   DATE,
    status              STRING          NOT NULL DEFAULT 'ACTIVE'
        COMMENT 'Expanded from legacy codes: ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE',
    delinquency_days    INT             DEFAULT 0,
    escrow_balance      DECIMAL(10, 2)  DEFAULT 0,
    ltv_percent         DECIMAL(5, 2),
    property_address    STRING,
    property_city       STRING,
    property_state      STRING,
    property_zip        STRING,
    property_type       STRING
        COMMENT 'Expanded from legacy codes: SFR->Single Family, CND->Condominium, MFR->Multi-Family, TWN->Townhouse',
    appraised_value     DECIMAL(12, 2),
    origination_year    INT             GENERATED ALWAYS AS (YEAR(origination_date))
        COMMENT 'Derived partition column from origination_date',
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    _migration_source   STRING          DEFAULT 'CDW_LN_ACCT',
    _migrated_at        TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Loan account fact table migrated from legacy CDW_LN_ACCT. Partitioned by status for operational query patterns.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality'                          = 'gold'
);

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_number_unique UNIQUE (account_number);
