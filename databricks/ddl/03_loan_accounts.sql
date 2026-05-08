-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy Core Data Warehouse)
-- =============================================================================
-- Fact table for loan accounts. Denormalized borrower fields from legacy are
-- dropped; borrower data is referenced via borrower_id FK.
-- Partitioned by origination_year to support time-range queries and efficient
-- pruning for reporting on vintage cohorts.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_account_id     BIGINT          GENERATED ALWAYS AS IDENTITY,
    account_number      STRING          NOT NULL    COMMENT 'Legacy LN_ACCT_NBR',
    borrower_id         BIGINT          NOT NULL    COMMENT 'FK to borrowers.borrower_id',
    product_id          BIGINT          NOT NULL    COMMENT 'FK to loan_products.product_id',
    original_amount     DECIMAL(12, 2)  NOT NULL    COMMENT 'Parsed from comma-formatted string',
    current_balance     DECIMAL(12, 2)  NOT NULL    COMMENT 'Parsed from comma-formatted string',
    interest_rate       DECIMAL(5, 3)   NOT NULL    COMMENT 'Parsed from string (e.g. "5.250")',
    term_months         INT             NOT NULL    COMMENT 'Parsed from string',
    monthly_payment     DECIMAL(10, 2)  NOT NULL    COMMENT 'Parsed from comma-formatted string',
    origination_date    DATE            NOT NULL    COMMENT 'Parsed from MM/DD/YYYY',
    maturity_date       DATE            NOT NULL    COMMENT 'Parsed from MM/DD/YYYY',
    first_payment_date  DATE                        COMMENT 'Parsed from MM/DD/YYYY',
    next_payment_date   DATE                        COMMENT 'Parsed from MM/DD/YYYY',
    status              STRING          NOT NULL    COMMENT 'Expanded: ACT->Active, CLO->Closed, DFT->Default, FRB->Forbearance',
    delinquency_days    INT             DEFAULT 0   COMMENT 'Parsed from string',
    escrow_balance      DECIMAL(10, 2)  DEFAULT 0   COMMENT 'Parsed from comma-formatted string',
    ltv_percent         DECIMAL(5, 2)               COMMENT 'Loan-to-value ratio parsed from string',
    property_address    STRING                      COMMENT 'Property street address',
    property_city       STRING,
    property_state      STRING                      COMMENT 'Two-letter state code',
    property_zip        STRING,
    property_type       STRING                      COMMENT 'Expanded: SFR->Single Family, CND->Condominium, MFR->Multi-Family, TWN->Townhouse',
    appraised_value     DECIMAL(12, 2)              COMMENT 'Parsed from comma-formatted string',
    created_at          TIMESTAMP                   COMMENT 'Parsed from legacy LN_CRET_DT',
    updated_at          TIMESTAMP                   COMMENT 'Parsed from legacy LN_UPDT_DT',
    origination_year    INT             NOT NULL    COMMENT 'Derived partition key: year(origination_date)',
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp'
)
USING DELTA
PARTITIONED BY (origination_year)
COMMENT 'Loan account fact table migrated from CDW_LN_ACCT. Partitioned by origination year for vintage analysis.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.tier'                     = 'gold'
);

ALTER TABLE loan_warehouse.loan_accounts
    ADD CONSTRAINT loan_accounts_acct_unique UNIQUE (account_number);
