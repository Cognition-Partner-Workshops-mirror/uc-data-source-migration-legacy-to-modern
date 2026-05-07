-- =============================================================================
-- Create the loan_warehouse schema (database) in Unity Catalog
-- Run this FIRST before any table DDL.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse — migrated from legacy CDW tables';
