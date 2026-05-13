-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Payment History)
-- =============================================================================
-- Mapping reference: data/mappings/column_mappings.md § CDW_PMT_HIST → payments
-- Key transformations:
--   - LN_ACCT_NBR → loan_account_id FK lookup via loan_accounts.account_number
--   - All VARCHAR amounts → DECIMAL (commas stripped)
--   - All VARCHAR dates → DATE (MM/DD/YYYY parsed)
--   - PMT_TYP_CD → type (expanded: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT)
--   - PMT_STAT_CD → status (expanded: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING)
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    id                  BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_sequence_nbr STRING                      COMMENT 'Original PMT_SEQ_NBR from CDW_PMT_HIST for traceability',
    loan_account_id     BIGINT          NOT NULL    COMMENT 'FK to loan_accounts.id (resolved from LN_ACCT_NBR via account_number lookup)',
    payment_date        DATE            NOT NULL    COMMENT 'Parsed from PMT_DT (MM/DD/YYYY → DATE)',
    total_amount        DECIMAL(10, 2)  NOT NULL    COMMENT 'Parsed from PMT_AMT (remove commas → DECIMAL)',
    principal_amount    DECIMAL(10, 2)              COMMENT 'Parsed from PMT_PRIN_AMT (remove commas → DECIMAL)',
    interest_amount     DECIMAL(10, 2)              COMMENT 'Parsed from PMT_INT_AMT (remove commas → DECIMAL)',
    escrow_amount       DECIMAL(10, 2)              COMMENT 'Parsed from PMT_ESCROW_AMT (remove commas → DECIMAL)',
    late_fee            DECIMAL(10, 2)  DEFAULT 0   COMMENT 'Parsed from PMT_LATE_FEE (remove commas → DECIMAL)',
    type                STRING          NOT NULL    COMMENT 'Expanded from PMT_TYP_CD: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT',
    status              STRING          NOT NULL    COMMENT 'Expanded from PMT_STAT_CD: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING',
    received_date       DATE                        COMMENT 'Parsed from PMT_RECV_DT (MM/DD/YYYY → DATE)',
    processed_date      DATE                        COMMENT 'Parsed from PMT_PROC_DT (MM/DD/YYYY → DATE)',
    created_at          TIMESTAMP       NOT NULL    COMMENT 'Parsed from PMT_CRET_DT (MM/DD/YYYY → TIMESTAMP)',
    updated_at          TIMESTAMP       NOT NULL    COMMENT 'Parsed from PMT_UPDT_DT (MM/DD/YYYY → TIMESTAMP)',
    _ingestion_ts       TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Pipeline ingestion timestamp',
    _source_system      STRING          DEFAULT 'CDW_PMT_HIST'      COMMENT 'Source table identifier'
)
USING DELTA
-- Partitioned by status to optimize lookups for posted vs. pending/reversed payments.
-- Payment date ordering handled via Z-ORDER in optimize commands.
PARTITIONED BY (status)
COMMENT 'Payment history table migrated from legacy CDW_PMT_HIST. All VARCHAR fields converted to proper types. Component sum validation applied during ingestion.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);
