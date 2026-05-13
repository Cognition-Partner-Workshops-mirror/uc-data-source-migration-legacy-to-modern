-- =============================================================================
-- Delta Lake Database: loan_warehouse
-- =============================================================================
-- Top-level database (schema) for all migrated loan management tables.
-- Run this before executing any table DDL scripts.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS loan_warehouse
COMMENT 'Loan management data warehouse migrated from legacy CDW system. Contains normalized borrower, loan, product, and payment data with proper types and referential integrity.';
