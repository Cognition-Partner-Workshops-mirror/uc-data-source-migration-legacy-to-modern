-- =============================================================================
-- Schema/Database Creation for the Loan Warehouse
-- =============================================================================
-- Run this first to create the catalog and schema used by all migration tables.
-- =============================================================================

-- Create the schema (database) if it does not exist
CREATE SCHEMA IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse migrated from legacy CDW tables';

-- Execution order for table creation:
--   1. borrowers.sql        (no dependencies)
--   2. loan_products.sql    (no dependencies)
--   3. loan_accounts.sql    (depends on borrowers, loan_products)
--   4. payments.sql         (depends on loan_accounts)
