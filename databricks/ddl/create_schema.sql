-- =============================================================================
-- Create the loan_warehouse schema (database) in Databricks Unity Catalog
-- Run this BEFORE any table DDL scripts.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse migrated from legacy CDW tables';
