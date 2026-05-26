-- =============================================================================
-- Delta Lake Database: loan_warehouse
-- =============================================================================
-- Creates the target database (schema) in Databricks for the migrated
-- loan management data. Run this before executing any table DDL scripts.
--
-- The database uses Unity Catalog-compatible naming: catalog.schema.table
-- Adjust the catalog name as needed for your Databricks workspace.
-- =============================================================================

-- Create the database if it does not exist
CREATE DATABASE IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan warehouse migrated from legacy CDW schema. Contains normalized borrower, loan product, loan account, and payment data with proper types and referential integrity.'
LOCATION 'dbfs:/mnt/delta/loan_warehouse';

-- Verify database creation
DESCRIBE DATABASE loan_warehouse;
