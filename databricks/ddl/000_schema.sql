-- =============================================================================
-- Schema / Database Setup
-- =============================================================================
-- Run this first to create the target catalog and schema in Databricks.
-- Adjust catalog name as needed for your environment.
-- =============================================================================

CREATE CATALOG IF NOT EXISTS loan_catalog;
USE CATALOG loan_catalog;

CREATE SCHEMA IF NOT EXISTS loan_modernized
COMMENT 'Modern loan management schema migrated from legacy CDW tables';

USE SCHEMA loan_modernized;
