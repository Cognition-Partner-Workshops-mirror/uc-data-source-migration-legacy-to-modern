-- =============================================================================
-- Database / Schema Creation for the Loan Warehouse
-- =============================================================================
-- Creates the Unity Catalog schema that houses all migrated loan tables.
-- Run this before executing any table DDL scripts.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse migrated from legacy CDW tables'
LOCATION 'dbfs:/mnt/delta/loan_warehouse';
