-- =============================================================================
-- MIGRATION AUDIT SCHEMA
-- =============================================================================
-- Tracks validation errors/warnings and row-level migration audit trail.
-- migration_errors: captures every field-level issue found during pre-flight
--                   or actual migration (preserves raw values for debugging).
-- migration_audit:  maps legacy source rows to their modern target rows,
--                   preserving the legacy PMT_SEQ_NBR → payments.id mapping
--                   that would otherwise be lost (per column_mappings.md line 79).
-- =============================================================================

CREATE TABLE migration_errors (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    source_table VARCHAR(50) NOT NULL,
    source_pk VARCHAR(50) NOT NULL,
    column_name VARCHAR(50) NOT NULL,
    raw_value VARCHAR(200),
    error_message VARCHAR(500) NOT NULL,
    severity VARCHAR(10) NOT NULL,  -- ERROR, WARNING
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE migration_audit (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    source_table VARCHAR(50) NOT NULL,
    source_pk VARCHAR(50) NOT NULL,
    target_table VARCHAR(50) NOT NULL,
    target_pk BIGINT NOT NULL,
    migrated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
