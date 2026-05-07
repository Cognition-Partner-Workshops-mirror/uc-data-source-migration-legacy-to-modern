-- =============================================================================
-- Delta Lake Database Creation and Execution Order
-- =============================================================================
-- This script creates the target database and documents the table creation
-- order based on foreign key dependencies.
--
-- Execution Order:
--   1. Create database
--   2. borrowers        (no dependencies)
--   3. loan_products    (no dependencies)
--   4. loan_accounts    (depends on borrowers, loan_products)
--   5. payments         (depends on loan_accounts)
-- =============================================================================

CREATE DATABASE IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse migrated from legacy CDW system'
LOCATION '/mnt/delta/loan_warehouse';

-- Execute DDL in dependency order:
-- Step 1: Dimension / reference tables (no FK dependencies)
--   RUN: databricks/ddl/borrowers.sql
--   RUN: databricks/ddl/loan_products.sql

-- Step 2: Core fact tables (depend on dimension tables)
--   RUN: databricks/ddl/loan_accounts.sql

-- Step 3: Transaction tables (depend on core fact tables)
--   RUN: databricks/ddl/payments.sql
