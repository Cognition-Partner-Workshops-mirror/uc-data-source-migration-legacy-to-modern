-- =============================================================================
-- Database / Schema Setup
-- =============================================================================
-- Creates the loan_warehouse database (schema) in the Unity Catalog.
-- Run this before any table DDL scripts.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan management data warehouse migrated from legacy CDW tables'
LOCATION 'dbfs:/mnt/delta/loan_warehouse';
