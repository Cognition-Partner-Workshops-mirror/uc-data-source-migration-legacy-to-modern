-- =============================================================================
-- Database/Schema Setup for Loan Warehouse
-- =============================================================================
-- Run this first to create the Unity Catalog schema that houses all
-- migrated Delta Lake tables.
-- =============================================================================

CREATE CATALOG IF NOT EXISTS loan_catalog;
USE CATALOG loan_catalog;

CREATE SCHEMA IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan management data warehouse migrated from legacy CDW system';
