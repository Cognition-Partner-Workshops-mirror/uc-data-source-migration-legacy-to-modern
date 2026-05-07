-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Loan Accounts)
-- =============================================================================
-- Core fact table for loan accounts. Denormalized borrower columns dropped;
-- relationships enforced via borrower_id FK. Partitioned by origination_year
-- to optimize time-range queries and loan vintage analysis.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    id                  BIGINT        GENERATED ALWAYS AS IDENTITY,
    account_number      STRING        NOT NULL COMMENT 'Legacy LN_ACCT_NBR',
    borrower_id         BIGINT        NOT NULL COMMENT 'FK to borrowers.id via external_id lookup',
    product_id          BIGINT        NOT NULL COMMENT 'FK to loan_products.id via code lookup',
    original_amount     DECIMAL(12,2) NOT NULL COMMENT 'Loan origination amount',
    current_balance     DECIMAL(12,2) NOT NULL COMMENT 'Current outstanding balance',
    interest_rate       DECIMAL(5,3)  NOT NULL COMMENT 'Annual interest rate (e.g. 4.750)',
    term_months         INT           NOT NULL COMMENT 'Loan term in months',
    monthly_payment     DECIMAL(10,2) NOT NULL COMMENT 'Scheduled monthly payment',
    origination_date    DATE          NOT NULL COMMENT 'Loan origination date',
    maturity_date       DATE          NOT NULL COMMENT 'Loan maturity date',
    first_payment_date  DATE          COMMENT 'Date of first scheduled payment',
    next_payment_date   DATE          COMMENT 'Date of next due payment',
    status              STRING        NOT NULL COMMENT 'Expanded: ACT->Active, CLO->Closed, DFT->Default, FRB->Forbearance',
    delinquency_days    INT           DEFAULT 0 COMMENT 'Days past due',
    escrow_balance      DECIMAL(10,2) COMMENT 'Current escrow balance',
    ltv_percent         DECIMAL(5,2)  COMMENT 'Loan-to-value ratio',
    property_address    STRING        COMMENT 'Collateral property address',
    property_city       STRING,
    property_state      STRING        COMMENT 'Two-letter state code',
    property_zip        STRING,
    property_type       STRING        COMMENT 'Expanded: SFR->Single Family, CND->Condominium, MFR->Multi-Family, TWN->Townhouse',
    appraised_value     DECIMAL(12,2) COMMENT 'Property appraised value',
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    origination_year    INT           GENERATED ALWAYS AS (YEAR(origination_date))
                                      COMMENT 'Partition key derived from origination_date',

    CONSTRAINT loan_accounts_pk PRIMARY KEY (id),
    CONSTRAINT fk_loan_borrower FOREIGN KEY (borrower_id) REFERENCES loan_warehouse.borrowers(id),
    CONSTRAINT fk_loan_product  FOREIGN KEY (product_id)  REFERENCES loan_warehouse.loan_products(id)
)
USING DELTA
PARTITIONED BY (origination_year)
COMMENT 'Modern loan accounts fact table migrated from CDW_LN_ACCT. Partitioned by origination year for vintage analysis.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);
