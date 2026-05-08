-- =============================================================================
-- Create the loan_warehouse database (Unity Catalog schema)
-- =============================================================================
-- Run this before any table DDL. In Databricks Unity Catalog this creates a
-- schema under the active catalog. Adjust the catalog name as needed for your
-- environment (e.g., dev, staging, prod).
-- =============================================================================

CREATE DATABASE IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse — migrated from legacy CDW tables'
LOCATION 'dbfs:/mnt/loan_warehouse';
