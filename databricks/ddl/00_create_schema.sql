-- =============================================================================
-- Databricks Schema (Database) Creation
-- =============================================================================
-- Creates the loan_management schema in the Unity Catalog.
-- Run this BEFORE creating any tables.
-- All Delta Lake tables are scoped under this schema for logical grouping.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS loan_management
COMMENT 'Modern loan management schema migrated from legacy CDW (Corporate Data Warehouse). Contains normalized borrower, loan product, loan account, and payment tables with proper data types and referential integrity.';
