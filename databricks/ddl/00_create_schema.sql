-- =============================================================================
-- Create the target schema (database) for the modern loan warehouse
-- =============================================================================
-- Run this FIRST before any table DDL scripts.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse migrated from legacy CDW tables'
LOCATION 'dbfs:/mnt/loan-warehouse/';
