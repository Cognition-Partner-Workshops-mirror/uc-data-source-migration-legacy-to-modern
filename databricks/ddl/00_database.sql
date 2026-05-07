-- =============================================================================
-- Database / Schema Setup
-- =============================================================================
-- Run this first to create the target database in Databricks Unity Catalog.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse — migrated from legacy CDW schema'
LOCATION 'dbfs:/mnt/delta/loan_warehouse';
