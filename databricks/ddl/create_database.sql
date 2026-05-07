-- =============================================================================
-- Database / Schema Creation
-- =============================================================================
-- Run this first to create the loan_warehouse database before creating tables.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse migrated from legacy CDW system'
LOCATION '/mnt/delta/loan_warehouse';

-- Execute table DDL in dependency order:
-- 1. borrowers.sql        (no dependencies)
-- 2. loan_products.sql    (no dependencies)
-- 3. loan_accounts.sql    (depends on borrowers, loan_products)
-- 4. payments.sql         (depends on loan_accounts)
