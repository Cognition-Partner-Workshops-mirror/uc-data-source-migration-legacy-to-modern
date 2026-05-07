-- =============================================================================
-- Schema / Database Setup
-- =============================================================================
-- Run this first to create the target catalog and schema in Unity Catalog.
-- Adjust catalog name as needed for your Databricks workspace.
-- =============================================================================

CREATE CATALOG IF NOT EXISTS loan_catalog;
USE CATALOG loan_catalog;

CREATE SCHEMA IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse migrated from legacy CDW system. Contains normalized borrower, loan, product, and payment tables with proper data types.';

USE SCHEMA loan_warehouse;
