-- =============================================================================
-- Schema Setup: loan_warehouse
-- =============================================================================
-- Run this first to create the Unity Catalog schema before creating tables.
-- Adjust the catalog name as needed for your Databricks workspace.
-- =============================================================================

CREATE CATALOG IF NOT EXISTS loan_migration;

USE CATALOG loan_migration;

CREATE SCHEMA IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse migrated from legacy CDW tables. Contains normalized borrower, loan product, loan account, and payment data with proper types and referential integrity.';

USE SCHEMA loan_warehouse;
