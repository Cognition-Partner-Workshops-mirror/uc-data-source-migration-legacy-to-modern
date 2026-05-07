# Databricks Migration Runbook

## Overview

This runbook documents the complete migration of the legacy CDW (Corporate Data Warehouse) loan management tables to a modern Delta Lake schema on Databricks. It covers every transformation decision, column mapping, type conversion, partitioning rationale, and the recommended execution order.

---

## Table of Contents

1. [Source System Summary](#1-source-system-summary)
2. [Target Schema Design](#2-target-schema-design)
3. [Column Mapping Reference](#3-column-mapping-reference)
4. [Type Conversion Rules](#4-type-conversion-rules)
5. [Status Code Expansion](#5-status-code-expansion)
6. [Denormalization Removal](#6-denormalization-removal)
7. [Partitioning Strategy](#7-partitioning-strategy)
8. [Execution Order](#8-execution-order)
9. [Data Quality Validation](#9-data-quality-validation)
10. [Rollback Procedure](#10-rollback-procedure)
11. [Operational Notes](#11-operational-notes)

---

See the previous `docs/DATABRICKS_MIGRATION_RUNBOOK.md` (now removed) for the full body. The complete sections 1-11 should be moved here verbatim as part of this rename.
