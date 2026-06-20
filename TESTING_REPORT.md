# Testing Report — Legacy-to-Modern Data Source Migration

## Overview

This report documents the tests added as part of the data source migration from
the legacy CDW (all-VARCHAR) schema to the modern normalized schema with proper
Java types (LocalDate, BigDecimal, Long, enums).

## Test Suites

### 1. Data Reconciliation Tests (`DataReconciliationTest.java`)

**Location:** `src/test/java/com/workshop/loanservice/migration/DataReconciliationTest.java`

**Purpose:** Validates that the migration from legacy CDW tables to modern schema
preserves all records and transforms field values correctly.

| Test | What It Validates |
|------|-------------------|
| `borrowerRecordCountMatches` | Legacy and modern borrower tables have the same row count |
| `loanProductRecordCountMatches` | Legacy and modern loan_products tables have the same row count |
| `loanAccountRecordCountMatches` | Legacy and modern loan_accounts tables have the same row count |
| `paymentRecordCountMatches` | Legacy and modern payments tables have the same row count |
| `borrowerFieldsTransformedCorrectly` | Verifies date parsing (MM/DD/YYYY → LocalDate), integer parsing, amount parsing (comma-stripped → BigDecimal), and status expansion (ACT → ACTIVE) |
| `borrowerWithNullMiddleInitialHandled` | NULL optional fields are preserved without errors |
| `loanProductFieldsTransformedCorrectly` | Amount parsing, integer conversion, boolean status (ACT → true), date parsing |
| `loanAccountFieldsTransformedCorrectly` | FK resolution (borrower by external_id, product by code), all amount/date/integer transformations, status and property type expansion |
| `loanAccountDelinquencyDaysPreserved` | Non-zero delinquency days transferred correctly |
| `paymentFieldsTransformedCorrectly` | Payment amounts, dates, type expansion (REG → REGULAR), status expansion (PST → POSTED) |
| `paymentWithLateFeePreserved` | Non-zero late fees are preserved (verifies $47.50 late fee) |
| `allBorrowersFkRelationshipsResolved` | Every loan_account has a valid borrower FK |
| `allProductFkRelationshipsResolved` | Every loan_account has a valid product FK |
| `allPaymentLoanAccountFkResolved` | Every payment has a valid loan_account FK |
| `condominiumPropertyTypeExpanded` | CND → "Condominium" expansion |
| `townhousePropertyTypeExpanded` | TWN → "Townhouse" expansion |

### 2. Golden-File Validation Tests (`GoldenFileValidationTest.java`)

**Location:** `src/test/java/com/workshop/loanservice/goldenfile/GoldenFileValidationTest.java`

**Purpose:** Validates that API responses after migration to the modern schema
produce the same JSON output as the legacy service. Golden files represent the
"before" baseline; tests assert the "after" matches.

| Test | Endpoint | Golden File |
|------|----------|-------------|
| `getAllLoansMatchesGoldenFile` | `GET /api/loans` | `get_all_loans.json` |
| `getLoanByIdMatchesGoldenFile` | `GET /api/loans/LN-2019-00142` | `get_loan_LN-2019-00142.json` |
| `getAllBorrowersMatchesGoldenFile` | `GET /api/borrowers` | `get_all_borrowers.json` |
| `getBorrowerByIdMatchesGoldenFile` | `GET /api/borrowers/B-10001` | `get_borrower_B-10001.json` |
| `getPaymentsByLoanMatchesGoldenFile` | `GET /api/loans/LN-2019-00142/payments` | `get_payments_LN-2019-00142.json` |

**Golden files location:** `src/test/resources/golden/`

### 3. Context Loading Test (`LoanServiceApplicationTests.java`)

**Location:** `src/test/java/com/workshop/loanservice/LoanServiceApplicationTests.java`

**Purpose:** Verifies the Spring Boot application context loads successfully with
both legacy and modern schemas initialized and migration executed.

## Test Execution

```bash
mvn test
```

**Result:** 22 tests, 0 failures, 0 errors

## What the Tests Cover

1. **Data integrity** — No records lost during migration (count parity)
2. **Type transformations** — Dates, amounts, integers, booleans parsed correctly
3. **Status/code expansion** — Abbreviated codes mapped to readable values
4. **Normalization** — Denormalized borrower fields correctly replaced by FK relationships
5. **FK resolution** — Legacy string IDs resolved to modern BIGINT auto-increment FKs
6. **API parity** — JSON responses match before/after migration (golden-file comparison)
7. **Edge cases** — NULL handling, zero values, non-zero late fees, delinquency days
