-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (Legacy CDW)
-- =============================================================================
-- Core fact table for loan accounts. Denormalized borrower fields from the
-- legacy table are dropped; borrower data is referenced via borrower_id FK.
-- Partitioned by status for efficient filtering on active/closed/default loans.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_modernized.loan_accounts (
    loan_account_id     BIGINT          GENERATED ALWAYS AS IDENTITY,
    account_number      STRING          NOT NULL    COMMENT 'Legacy LN_ACCT_NBR (e.g., LN-2019-00142)',
    borrower_id         BIGINT          NOT NULL    COMMENT 'FK to borrowers.borrower_id',
    product_code        STRING          NOT NULL    COMMENT 'FK reference to loan_products.code',
    original_amount     DECIMAL(12, 2)  NOT NULL    COMMENT 'Original loan amount parsed from comma-formatted string',
    current_balance     DECIMAL(12, 2)  NOT NULL    COMMENT 'Current outstanding balance',
    interest_rate       DECIMAL(5, 3)   NOT NULL    COMMENT 'Annual interest rate (e.g., 4.750)',
    term_months         INT             NOT NULL    COMMENT 'Loan term in months',
    monthly_payment     DECIMAL(10, 2)  NOT NULL    COMMENT 'Monthly payment amount',
    origination_date    DATE            NOT NULL    COMMENT 'Loan origination date parsed from MM/DD/YYYY',
    maturity_date       DATE            NOT NULL    COMMENT 'Loan maturity date parsed from MM/DD/YYYY',
    first_payment_date  DATE                        COMMENT 'First payment due date',
    next_payment_date   DATE                        COMMENT 'Next scheduled payment date',
    status              STRING          NOT NULL DEFAULT 'ACTIVE'
                                                    COMMENT 'Expanded: ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE',
    delinquency_days    INT             DEFAULT 0   COMMENT 'Days delinquent parsed from VARCHAR',
    escrow_balance      DECIMAL(10, 2)  DEFAULT 0   COMMENT 'Escrow account balance',
    ltv_percent         DECIMAL(5, 2)               COMMENT 'Loan-to-value ratio percentage',
    property_address    STRING                      COMMENT 'Property street address',
    property_city       STRING                      COMMENT 'Property city',
    property_state      STRING                      COMMENT 'Property two-letter state code',
    property_zip        STRING                      COMMENT 'Property ZIP code',
    property_type       STRING                      COMMENT 'Expanded: SFR->Single Family, CND->Condominium, MFR->Multi-Family, TWN->Townhouse',
    appraised_value     DECIMAL(12, 2)              COMMENT 'Property appraised value',
    origination_year    INT                         COMMENT 'Derived from origination_date for partitioning',
    created_at          TIMESTAMP                   COMMENT 'Record creation timestamp',
    updated_at          TIMESTAMP                   COMMENT 'Last update timestamp',
    _legacy_borr_id     STRING                      COMMENT 'Original BORR_ID for audit trail',
    _legacy_prod_cd     STRING                      COMMENT 'Original PROD_CD for audit trail',
    _migration_ts       TIMESTAMP       DEFAULT current_timestamp()
                                                    COMMENT 'Timestamp when record was migrated'
)
USING DELTA
COMMENT 'Loan account fact table migrated from legacy CDW_LN_ACCT. Denormalized borrower fields removed.'
PARTITIONED BY (status)
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.columnMapping.mode'         = 'name',
    'delta.minReaderVersion'           = '2',
    'delta.minWriterVersion'           = '5'
);

ALTER TABLE loan_modernized.loan_accounts
    ADD CONSTRAINT loan_accounts_acct_not_null EXPECT (account_number IS NOT NULL)
    VIOLATION (FAIL UPDATE);

ALTER TABLE loan_modernized.loan_accounts
    ADD CONSTRAINT loan_accounts_positive_balance EXPECT (current_balance >= 0)
    VIOLATION (DROP ROW);
