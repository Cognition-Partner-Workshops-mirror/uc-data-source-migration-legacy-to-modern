-- =============================================================================
-- Schema (Database) Creation for the Modern Loan Warehouse
-- =============================================================================
-- Run this FIRST before executing any table DDL scripts.
-- Creates the Unity Catalog schema that houses all migrated Delta tables.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS loan_warehouse
COMMENT 'Modern loan management warehouse — migrated from legacy CDW tables';
