-- =============================================================================
-- Database / Schema Setup for Loan Warehouse
-- =============================================================================
-- Run this first to create the target catalog and schema in Unity Catalog.
-- Adjust the catalog name to match your Databricks workspace configuration.
-- =============================================================================

CREATE CATALOG IF NOT EXISTS loan_catalog;
USE CATALOG loan_catalog;

CREATE SCHEMA IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse migrated from legacy CDW tables';

USE SCHEMA loan_warehouse;
