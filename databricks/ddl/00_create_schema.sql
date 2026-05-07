-- =============================================================================
-- Create the loan_warehouse schema (database) in Unity Catalog
-- =============================================================================
-- Run this first before executing any table DDL scripts.
-- Adjust the catalog name to match your Databricks workspace configuration.
-- =============================================================================

CREATE CATALOG IF NOT EXISTS loan_migration;
USE CATALOG loan_migration;

CREATE SCHEMA IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse migrated from legacy CDW tables. Contains normalized borrower, loan product, loan account, and payment history tables.';

USE SCHEMA loan_warehouse;
