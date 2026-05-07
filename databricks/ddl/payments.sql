-- =============================================================================
-- Delta Lake Table: payments
-- Source: CDW_PMT_HIST (Legacy Payment History)
-- =============================================================================
-- Payment transaction fact table. Partitioned by payment year/month
-- derived from PMT_DT to support efficient time-range queries and
-- incremental loading patterns.
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    payment_key             BIGINT          GENERATED ALWAYS AS IDENTITY,
    legacy_payment_id       STRING          NOT NULL    COMMENT 'Original payment sequence number for traceability (was PMT_SEQ_NBR)',
    loan_account_number     STRING          NOT NULL    COMMENT 'FK to loan_accounts.account_number (was LN_ACCT_NBR)',
    payment_date            DATE            NOT NULL    COMMENT 'Payment date, parsed from MM/DD/YYYY (was PMT_DT)',
    total_amount            DECIMAL(10, 2)  NOT NULL    COMMENT 'Total payment amount, parsed from comma string (was PMT_AMT)',
    principal_amount        DECIMAL(10, 2)              COMMENT 'Principal portion, parsed from comma string (was PMT_PRIN_AMT)',
    interest_amount         DECIMAL(10, 2)              COMMENT 'Interest portion, parsed from comma string (was PMT_INT_AMT)',
    escrow_amount           DECIMAL(10, 2)              COMMENT 'Escrow portion, parsed from comma string (was PMT_ESCROW_AMT)',
    late_fee                DECIMAL(10, 2)  DEFAULT 0   COMMENT 'Late fee amount, parsed from comma string (was PMT_LATE_FEE)',
    type                    STRING          NOT NULL    COMMENT 'Expanded type: REG->Regular, EXT->Extra, PRT->Partial, PRE->Prepayment (was PMT_TYP_CD)',
    status                  STRING          NOT NULL    COMMENT 'Expanded status: PST->Posted, REV->Reversed, NSF->NSF, PND->Pending (was PMT_STAT_CD)',
    received_date           DATE                        COMMENT 'Date payment received, parsed from MM/DD/YYYY (was PMT_RECV_DT)',
    processed_date          DATE                        COMMENT 'Date payment processed, parsed from MM/DD/YYYY (was PMT_PROC_DT)',
    created_at              TIMESTAMP                   COMMENT 'Record creation timestamp, parsed from MM/DD/YYYY (was PMT_CRET_DT)',
    updated_at              TIMESTAMP                   COMMENT 'Last update timestamp, parsed from MM/DD/YYYY (was PMT_UPDT_DT)',
    payment_year_month      STRING                      COMMENT 'Partition key in YYYY-MM format derived from payment_date',
    _migration_source       STRING          DEFAULT 'CDW_PMT_HIST' COMMENT 'Source table for lineage tracking',
    _migrated_at            TIMESTAMP       DEFAULT current_timestamp() COMMENT 'Timestamp of migration run'
)
USING DELTA
PARTITIONED BY (payment_year_month)
COMMENT 'Payment history fact table migrated from legacy CDW_PMT_HIST. Contains payment transactions with amount breakdowns by principal, interest, escrow, and fees.'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'delta.deletedFileRetentionDuration' = 'interval 30 days',
    'delta.logRetentionDuration'       = 'interval 90 days'
);
