-- =============================================================================
-- Delta Lake Table: migration_audit_log
-- Tracks every migration run for reconciliation and debugging
-- =============================================================================

CREATE TABLE IF NOT EXISTS loan_warehouse.migration_audit_log (
    run_id              STRING          NOT NULL,
    run_timestamp       TIMESTAMP       NOT NULL,
    source_table        STRING          NOT NULL,
    target_table        STRING          NOT NULL,
    source_row_count    BIGINT,
    target_row_count    BIGINT,
    rejected_row_count  BIGINT          DEFAULT 0,
    warnings_count      BIGINT          DEFAULT 0,
    status              STRING          NOT NULL COMMENT 'SUCCESS, PARTIAL, FAILED',
    error_message       STRING,
    duration_seconds    DOUBLE,
    _ingested_at        TIMESTAMP       DEFAULT current_timestamp()
)
USING DELTA
COMMENT 'Audit log tracking each migration run for reconciliation'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);
