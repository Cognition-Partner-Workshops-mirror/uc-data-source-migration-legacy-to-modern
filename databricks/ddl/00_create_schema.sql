-- =============================================================================
-- Databricks Schema (Database) Creation
-- =============================================================================
-- Run this first to create the target schema/database in Unity Catalog.
-- Adjust the catalog name to match your Databricks workspace configuration.
-- =============================================================================

CREATE CATALOG IF NOT EXISTS loan_migration;
USE CATALOG loan_migration;

CREATE SCHEMA IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan management data warehouse migrated from legacy CDW tables';
