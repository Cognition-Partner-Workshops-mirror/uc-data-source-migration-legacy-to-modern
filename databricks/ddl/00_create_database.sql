-- =============================================================================
-- Create the loan_warehouse database / schema
-- =============================================================================
-- Run this first before creating any tables.
-- Uses Unity Catalog naming: catalog.schema.table
-- Adjust the catalog name to match your Databricks workspace.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse migrated from legacy CDW schema'
LOCATION 'dbfs:/mnt/delta/loan_warehouse';
