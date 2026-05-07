-- =============================================================================
-- Delta Lake Table: loan_accounts
-- Source: CDW_LN_ACCT (denormalized borrower fields dropped; FK used instead)
-- Partitioned by: status (Active/Closed/Default/Forbearance)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.loan_accounts (
    loan_id             BIGINT          GENERATED ALWAYS AS IDENTITY,
    account_number      STRING          NOT NULL,
    borrower_id         BIGINT          NOT NULL, -- FK resolved from legacy BORR_ID via borrowers.external_id lookup
    product_id          BIGINT          NOT NULL, -- FK resolved from legacy PROD_CD via loan_products.code lookup
    original_amount     DECIMAL(12, 2)  NOT NULL,
    current_balance     DECIMAL(12, 2)  NOT NULL,
    interest_rate       DECIMAL(5, 3)   NOT NULL,
    term_months         INT             NOT NULL,
    monthly_payment     DECIMAL(10, 2)  NOT NULL,
    origination_date    DATE            NOT NULL,
    maturity_date       DATE            NOT NULL,
    first_payment_date  DATE,
    next_payment_date   DATE,
    status              STRING          NOT NULL, -- Expanded: ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE
    delinquency_days    INT             DEFAULT 0, -- Quality check flags active loans with delinquency_days > 0
    escrow_balance      DECIMAL(10, 2),
    ltv_percent         DECIMAL(5, 2),
    property_address    STRING,
    property_city       STRING,
    property_state      STRING,
    property_zip        STRING,
    property_type       STRING,         -- Expanded: SFR->Single Family, CND->Condominium, MFR->Multi-Family, TWN->Townhouse
    appraised_value     DECIMAL(12, 2),
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP,
    _legacy_acct_nbr    STRING          COMMENT 'Original CDW_LN_ACCT.LN_ACCT_NBR for lineage',
    _ingested_at        TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Row ingestion timestamp',

    CONSTRAINT loan_accounts_pk PRIMARY KEY (loan_id),
    CONSTRAINT loan_accounts_acct_uq UNIQUE (account_number),
    CONSTRAINT loan_accounts_borrower_fk FOREIGN KEY (borrower_id)
        REFERENCES loan_warehouse.borrowers (borrower_id),
    CONSTRAINT loan_accounts_product_fk FOREIGN KEY (product_id)
        REFERENCES loan_warehouse.loan_products (product_id)
)
USING DELTA
PARTITIONED BY (status)
COMMENT 'Loan account fact table migrated from CDW_LN_ACCT. Partitioned by loan status for efficient filtering.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.pipeline.source'          = 'CDW_LN_ACCT'
);
