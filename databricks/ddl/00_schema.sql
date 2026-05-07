-- =============================================================================
-- Schema / Database Creation
-- Run this first to create the target catalog and schema in Databricks
-- =============================================================================

CREATE CATALOG IF NOT EXISTS lending_warehouse;
USE CATALOG lending_warehouse;

CREATE SCHEMA IF NOT EXISTS loan_management
COMMENT 'Modern loan management schema migrated from legacy CDW data warehouse';

USE SCHEMA loan_management;
