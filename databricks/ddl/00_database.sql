-- =============================================================================
-- Delta Lake Database / Schema Definition
-- =============================================================================
-- Creates the loan_warehouse database that holds all migrated tables.
-- Run this BEFORE any table DDL scripts.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan data warehouse migrated from legacy CDW schema'
LOCATION '/mnt/delta/loan_warehouse';
