-- =============================================================================
-- Create the target Unity Catalog schema for the modern loan warehouse.
-- Run this ONCE before executing individual table DDL scripts.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse migrated from legacy CDW tables';
