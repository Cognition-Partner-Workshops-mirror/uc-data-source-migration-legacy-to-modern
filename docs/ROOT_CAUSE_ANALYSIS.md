# Root Cause Analysis — Top 3 Critical Data Anomalies

This document traces the three most critical anomalies from the [Data Anomaly Report](DATA_ANOMALY_REPORT.md) through the codebase to identify exactly where each anomaly causes a runtime failure or incorrect API response.

---

## RCA-1: VARCHAR Numeric Fields Cause Unhandled `NumberFormatException` (ANO-001)

### Symptom

Any non-numeric string in a monetary or numeric legacy column causes the entire API request to fail with a 500 Internal Server Error.

### Code Path Trace

1. **Entry point:** `LoanController.getAllLoans()` → `LoanService.getAllLoans()` (line 48)

2. **Data fetch:** `loanAccountRepository.findAll()` returns all `LegacyLoanAccount` entities. Every field is a `String` (see `LegacyLoanAccount.java` — all `@Column` mappings are `String`).

3. **Translation:** For each account, `toLoanSummary(acct, product)` is called (line 54). This calls:
   - `parseLegacyAmount(acct.getOriginalAmount())` — line 108
   - `parseLegacyAmount(acct.getCurrentBalance())` — line 109
   - `parseLegacyDecimal(acct.getInterestRate())` — line 110
   - `parseLegacyAmount(acct.getMonthlyPayment())` — line 111

4. **Failure point — `LoanService.java:154`:**
   ```java
   private BigDecimal parseLegacyAmount(String amount) {
       if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(amount.replace(",", ""));
   }
   ```
   The null/blank check handles empty values, but if `amount` contains `"$285,000"`, `"N/A"`, `"TBD"`, or any non-numeric content after comma removal, `new BigDecimal(...)` throws `NumberFormatException`.

5. **Same pattern — `LoanService.java:164`:**
   ```java
   private Integer parseLegacyInteger(String value) {
       if (value == null || value.isBlank()) return null;
       return Integer.parseInt(value.trim());
   }
   ```
   Called for `BORR_CRDT_SCR` (credit score) and `LN_DLQ_DAYS` (delinquency days). Any non-integer string throws `NumberFormatException`.

6. **No exception handler:** Neither `LoanController` nor `BorrowerController` has `@ExceptionHandler` or `@ControllerAdvice`. The `NumberFormatException` propagates up as an unhandled exception, resulting in Spring's default 500 error response with a stack trace (if `server.error.include-stacktrace` is enabled).

7. **Blast radius:** Because `getAllLoans()` maps ALL records in a single stream (line 53-55), a single corrupt record causes the entire list endpoint to fail. There is no per-record error isolation.

### Root Cause

The parsing methods assume all legacy string data is well-formed after null/blank checks. The legacy schema (`schema-legacy.sql`) defines all columns as `VARCHAR` with no CHECK constraints, meaning any string value can be stored. The service layer has no try-catch around the parsing calls, and the controller layer has no global exception handler.

### Where It Would Manifest

| Endpoint | Trigger | Result |
|---|---|---|
| `GET /api/loans` | Any loan with malformed amount/rate | 500 error, no loans returned |
| `GET /api/loans/{id}` | Specific loan with bad data | 500 error |
| `GET /api/borrowers` | Borrower with non-numeric credit score | 500 error, no borrowers returned |
| `GET /api/borrowers/{id}` | Specific borrower + their loans | 500 error |
| `GET /api/loans/{id}/payments` | Payment with malformed amount | 500 error |

---

## RCA-2: String Date Fields — Incorrect Sort Order and Migration Failure (ANO-002)

### Symptom

Payment history can be returned in incorrect chronological order. Date fields are exposed as raw legacy format strings in API responses. Migration to the modern schema will fail on date parsing.

### Code Path Trace

1. **Repository query — `LegacyPaymentRepository.java:14`:**
   ```java
   List<LegacyPayment> findByLoanAccountNumberOrderByPaymentDateDesc(String loanAccountNumber);
   ```
   Spring Data JPA translates this to `ORDER BY PMT_DT DESC`. Since `PMT_DT` is `VARCHAR(10)`, this is a **lexicographic sort**, not a chronological sort.

2. **Lexicographic sort failure cases:**
   - `"9/01/2025"` sorts AFTER `"12/01/2025"` (character `'9'` > `'1'`)
   - `"01/15/2026"` sorts BEFORE `"12/15/2025"` (character `'0'` < `'1'`)
   - Even with consistent zero-padding, cross-year sorting fails: `"01/01/2026"` < `"12/31/2025"` lexicographically

3. **Dates passed through without parsing — `LoanService.java:113, 138`:**
   ```java
   dto.setOriginationDate(acct.getOriginationDate());  // line 113
   dto.setPaymentDate(pmt.getPaymentDate());            // line 138
   ```
   The `LoanSummaryDto.originationDate` and `PaymentDto.paymentDate` are both `String` types. The raw legacy format `"02/15/2019"` is returned directly in the API JSON response. API consumers expecting ISO-8601 (`2019-02-15`) will fail to parse these.

4. **Column mappings confirm the gap — `column_mappings.md:12`:**
   ```
   | BORR_DOB_DT | VARCHAR(10) | date_of_birth | DATE | Parse MM/DD/YYYY → DATE |
   ```
   The mapping document specifies 16 date columns across 4 tables that require `MM/DD/YYYY → DATE` parsing. None of this parsing is implemented in the current service layer.

5. **Migration target schema — `modern_tables.sql:62`:**
   ```sql
   origination_date DATE NOT NULL,
   ```
   The modern schema requires `DATE` type with `NOT NULL`. Any date that fails to parse will block the INSERT. With no parsing logic in place, the migration will fail on every record.

### Root Cause

The legacy CDW stored all dates as `VARCHAR(10)` strings in `MM/DD/YYYY` format. The service layer was written to "pass through" dates as strings rather than parsing them into `java.time.LocalDate`. The JPA repository's `OrderBy` clause operates on the raw string column, which sorts lexicographically rather than chronologically. The column_mappings.md documents the required transformation but it was never implemented.

### Where It Would Manifest

| Scenario | Trigger | Result |
|---|---|---|
| `GET /api/loans/{id}/payments` | Payments spanning year boundary | Payments in wrong order |
| `GET /api/loans/{id}/payments` | Payments in months 1-9 vs 10-12 | Single-digit months sort incorrectly |
| Any API response with dates | Always | Raw `MM/DD/YYYY` format exposed |
| Migration to modern schema | Always | `DateTimeParseException` if format varies |

---

## RCA-3: No Foreign Key Constraints — Orphaned Records and NullPointerException (ANO-003)

### Symptom

Loan accounts referencing non-existent borrowers or products cause `NullPointerException` or silently incorrect API responses. Migration to the modern schema (which has real FKs) will fail with constraint violations.

### Code Path Trace

1. **Schema — `schema-legacy.sql:8`:**
   ```sql
   -- No foreign key constraints
   ```
   The legacy schema explicitly documents that there are no FK constraints. `CDW_LN_ACCT.BORR_ID` is a plain `VARCHAR(20)` with no reference to `CDW_BORR_MSTR.BORR_ID`. Same for `PROD_CD` and `CDW_PMT_HIST.LN_ACCT_NBR`.

2. **Product lookup — `LoanService.java:49-51`:**
   ```java
   Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
           .stream()
           .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));
   ```
   This builds a map of all products by code. If a loan account has `PROD_CD = 'INVALID'`, `products.get("INVALID")` returns `null`.

3. **Null product handling — `LoanService.java:107`:**
   ```java
   dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
   ```
   This handles null gracefully by falling back to the raw code. However, this silently masks a data integrity issue — the API returns a cryptic code like `"INVALID"` instead of a human-readable description, with no indication that the data is bad.

4. **Borrower lookup — `LoanService.java:73-74`:**
   ```java
   LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
           .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));
   ```
   If a loan references `BORR_ID = 'B-99999'` (non-existent), and a caller navigates from `GET /api/loans` (which shows the loan) to `GET /api/borrowers/B-99999`, this throws `RuntimeException` → 500 error. The loan listing itself uses the denormalized `BORR_FST_NM` / `BORR_LST_NM` from the loan table, so it would show the borrower name even if the master record doesn't exist, creating a misleading experience.

5. **Payment to loan linkage — `LoanService.java:91`:**
   ```java
   return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
   ```
   If `CDW_PMT_HIST` has a record with `LN_ACCT_NBR = 'LN-DELETED-001'`, the payment exists in the database but is unreachable through the loan endpoint. Conversely, if someone queries payments for a valid loan, orphaned payments for deleted loans just won't appear — they sit in the table consuming space and causing confusion in aggregate reporting.

6. **Migration target — `modern_tables.sql:79-80`:**
   ```sql
   FOREIGN KEY (borrower_id) REFERENCES borrowers(id),
   FOREIGN KEY (product_id) REFERENCES loan_products(id)
   ```
   During migration, every orphaned record will cause a `ConstraintViolationException` on INSERT. The migration will either fail entirely (if not wrapped in transactions per record) or silently drop orphaned records (if using `ON CONFLICT SKIP`), leading to data loss.

### Root Cause

The legacy CDW was designed as a denormalized data warehouse without referential integrity constraints — a common pattern for warehouses optimized for batch reads. The application treats it as a transactional database with expected relational integrity, but the schema provides no guarantees. The service layer partially handles missing products (null check) but doesn't handle missing borrowers gracefully (throws RuntimeException), and doesn't validate referential integrity at all.

### Where It Would Manifest

| Scenario | Trigger | Result |
|---|---|---|
| `GET /api/loans` | Loan with invalid `PROD_CD` | Raw code in response instead of description |
| `GET /api/borrowers/{id}` | Non-existent borrower ID from loan | 500 error (RuntimeException) |
| Migration to modern schema | Any orphaned record | FK constraint violation, migration blocked |
| Data warehouse reporting | Orphaned payments | Incorrect aggregate totals |

---

## Cross-Reference Summary

| RCA | Anomaly IDs | Primary File | Critical Lines | Failure Mode |
|---|---|---|---|---|
| RCA-1 | ANO-001, ANO-005, ANO-006 | `LoanService.java` | 152-165 | `NumberFormatException` → 500 |
| RCA-2 | ANO-002, ANO-012 | `LoanService.java`, `LegacyPaymentRepository.java` | 113, 138, 14 | Wrong sort order, raw date format |
| RCA-3 | ANO-003, ANO-004 | `LoanService.java` | 49-51, 73-74, 107 | `NullPointerException`/500, silent data issues |
