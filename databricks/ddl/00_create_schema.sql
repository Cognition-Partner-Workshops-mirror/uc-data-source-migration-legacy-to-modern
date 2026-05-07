-- =============================================================================
-- Create Unity Catalog Schema
-- =============================================================================
-- Run this first to create the target catalog and schema.
-- Adjust catalog name as needed for your Databricks workspace.
-- =============================================================================

CREATE CATALOG IF NOT EXISTS loan_catalog;
USE CATALOG loan_catalog;

CREATE SCHEMA IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse migrated from legacy CDW tables';
