-- =============================================================================
-- Delta Lake Table: borrowers
-- Source: CDW_BORR_MSTR
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    borrower_id       BIGINT        GENERATED ALWAYS AS IDENTITY, -- Auto-increment PK replacing legacy string BORR_ID
    external_id       STRING        NOT NULL, -- Maps from BORR_ID; preserved for cross-reference with legacy systems
    first_name        STRING        NOT NULL,
    last_name         STRING        NOT NULL,
    middle_initial    STRING,
    ssn_hash          STRING,
    date_of_birth     DATE,
    address_line1     STRING,
    address_line2     STRING,
    city              STRING,
    state             STRING,
    zip_code          STRING,
    phone             STRING,
    email             STRING,
    credit_score      INT,              -- Parsed from VARCHAR; valid FICO range 300-850 enforced by quality checks
    employment_status STRING,
    annual_income     DECIMAL(12, 2),   -- Parsed from comma-formatted string (e.g. "92,500" -> 92500.00)
    status            STRING        NOT NULL, -- Expanded from abbreviation: ACT->ACTIVE, INA->INACTIVE
    created_at        TIMESTAMP,
    updated_at        TIMESTAMP,
    _legacy_borr_id   STRING        COMMENT 'Original CDW_BORR_MSTR.BORR_ID for lineage',
    _ingested_at      TIMESTAMP     DEFAULT current_timestamp() COMMENT 'Row ingestion timestamp',

    CONSTRAINT borrowers_pk PRIMARY KEY (borrower_id),
    CONSTRAINT borrowers_ext_uq UNIQUE (external_id)
)
USING DELTA
COMMENT 'Borrower dimension table migrated from CDW_BORR_MSTR'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.pipeline.source'          = 'CDW_BORR_MSTR'
);
