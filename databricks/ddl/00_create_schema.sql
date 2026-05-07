-- =============================================================================
-- Databricks Schema (Database) Creation
-- =============================================================================
-- Run this first to create the target schema/database.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse migrated from legacy CDW tables'
WITH DBPROPERTIES (
    'source_system'   = 'CDW Legacy Data Warehouse',
    'migration_date'  = current_date(),
    'owner'           = 'data-engineering'
);
