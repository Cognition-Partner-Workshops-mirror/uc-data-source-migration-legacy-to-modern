-- =============================================================================
-- Databricks Schema (Database) for the Loan Warehouse
-- =============================================================================
-- Run this FIRST to create the target catalog/schema before creating tables.
-- Adjust the catalog name if using Unity Catalog (e.g. main.loan_warehouse).
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse — migrated from legacy CDW tables'
WITH DBPROPERTIES (
    'source_system' = 'CDW Legacy Data Warehouse',
    'migration_version' = '1.0',
    'migration_date' = '2026-05-07'
);
