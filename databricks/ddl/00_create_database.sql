-- =============================================================================
-- Databricks Database / Schema Setup
-- =============================================================================
-- Creates the target database (Unity Catalog schema) for the migrated
-- loan warehouse tables. Run this before any table DDL scripts.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse migrated from legacy CDW tables'
LOCATION 'dbfs:/mnt/delta/loan_warehouse';
