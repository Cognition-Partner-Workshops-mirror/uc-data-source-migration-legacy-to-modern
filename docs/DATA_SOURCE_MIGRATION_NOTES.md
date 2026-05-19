# Data Source Migration Notes

## Overview

This document describes the completed migration from the legacy CDW (Corporate Data Warehouse) schema to a modern normalized schema within the loan-service application.

## What Was Done

### 1. Modern JPA Entities (`entity/`)
Created four properly-typed entities mapped to the normalized schema:
- **`Borrower`** — `LocalDate` for DOB, `BigDecimal` for income, `Integer` for credit score
- **`LoanProduct`** — `Integer` for term months, `Boolean` for is_active, `BigDecimal` for amounts
- **`LoanAccount`** — `@ManyToOne` FK to Borrower and LoanProduct, `BigDecimal` for financials
- **`Payment`** — `@ManyToOne` FK to LoanAccount, `LocalDate` for dates

### 2. Modern Repositories (`repository/`)
Spring Data JPA repositories with FK-based query methods:
- `BorrowerRepository` — `findByExternalId()` for legacy ID lookup
- `LoanProductRepository` — `findByCode()` for product code lookup
- `LoanAccountRepository` — `findByAccountNumber()`, `findByBorrowerExternalId()`
- `PaymentRepository` — `findByLoanAccountAccountNumberOrderByPaymentDateDesc()`

### 3. Data Migration Service (`service/DataMigrationService`)
Four-phase migration pipeline:
1. **Borrowers**: Parse MM/DD/YYYY dates → `LocalDate`, strip commas from income → `BigDecimal`, expand status codes (ACT→ACTIVE)
2. **Products**: Parse term months → `Integer`, convert status code to `Boolean` (ACT→true)
3. **Accounts**: Resolve borrower/product FKs, drop denormalized fields, expand property types (SFR→Single Family)
4. **Payments**: Resolve loan account FK, expand type/status codes (REG→REGULAR, PST→POSTED)

The migration is idempotent — duplicate records are skipped on re-run.

### 4. Modern Loan Service (`service/ModernLoanService`)
Reads from modern tables with no string parsing needed. All translation logic from `LoanService` is eliminated because modern entities already use proper Java types.

### 5. Dual-Read Service (`service/DualReadService`)
Feature-flag controlled service (`datasource.mode` property):
- `legacy` — reads from legacy CDW tables only (default)
- `modern` — reads from modern normalized tables only
- `dual` — reads from both, compares field-by-field, logs discrepancies

The dual-read comparison handles BigDecimal scale differences (285000 vs 285000.00) by using `compareTo()` instead of `equals()`.

### 6. Migration REST API (`controller/MigrationController`)
- `POST /api/migration/run` — Execute the migration
- `GET /api/migration/report` — View last migration report
- `GET /api/migration/mode` — View current data source mode
- `PUT /api/migration/mode?mode=dual` — Switch mode at runtime
- `GET /api/migration/comparison` — View dual-read comparison results

## Transformation Patterns Applied

| Pattern | Legacy Example | Modern Result |
|---------|---------------|---------------|
| Date parsing | `"03/15/1978"` | `1978-03-15` (LocalDate) |
| Amount parsing | `"285,000"` | `285000` (BigDecimal) |
| Status expansion | `"ACT"` | `"ACTIVE"` |
| Property type expansion | `"SFR"` | `"Single Family"` |
| Payment type expansion | `"REG"` | `"REGULAR"` |
| Boolean conversion | `"ACT"` → true | `true` (Boolean) |
| FK resolution | `"B-10001"` (string) | `1` (Long FK) |
| Denormalization removal | borrower fields in loan | FK to borrowers table |

## Validation Results

All 11 tests pass, including:
- Migration count verification (5 borrowers, 5 products, 5 accounts, 10 payments)
- Golden file parity (legacy vs modern API output matches for all endpoints)
- Dual-read mode detects zero differences
- Idempotency (re-running migration skips existing records)
