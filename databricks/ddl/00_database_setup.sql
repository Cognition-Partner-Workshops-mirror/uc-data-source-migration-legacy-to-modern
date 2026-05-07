-- =============================================================================
-- Database and Schema Setup for Loan Warehouse
-- =============================================================================
-- Run this script first to create the catalog and database.
-- Assumes Unity Catalog is enabled on the Databricks workspace.
-- =============================================================================

-- Create the database (schema) within the default catalog
CREATE DATABASE IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse migrated from legacy CDW tables'
LOCATION 'dbfs:/mnt/loan-warehouse/gold';

-- Verify creation
DESCRIBE DATABASE loan_warehouse;
