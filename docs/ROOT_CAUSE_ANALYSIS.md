# Root Cause Analysis — Top 3 Critical Data Anomalies

## 1. Payment Component Sum Mismatch (Critical)

### Anomaly
Payment records in `CDW_PMT_HIST` have `PMT_AMT` (total) that does not equal the sum of `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`.

### Code Trace

**Entry Point:** `LoanController.getPayments()` → `LoanService.getPaymentsByLoan()`

```
LoanService.java:90-95
    paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
        .stream()
        .map(this::toPaymentDto)
        .collect(Collectors.toList());
```

**Translation Method:** `LoanService.java:134-146` — `toPaymentDto()`
```java
dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
```

**Root Cause:** The `toPaymentDto()` method performs a direct 1:1 field copy from the legacy entity to the DTO without any cross-field validation. Each amount field is parsed independently via `parseLegacyAmount()`. There is **no integrity check** that verifies `total == sum(components)`.

**Specific Failure Path:**
1. Legacy ETL process populates `PMT_AMT` from one source (e.g., bank statement) and components from another (e.g., amortization schedule)
2. The service reads all fields as independent VARCHARs (no database-level check constraint)
3. `toPaymentDto()` faithfully converts each string to BigDecimal
4. API returns a `PaymentDto` where `totalAmount != principalAmount + interestAmount + escrowAmount + lateFee`
5. Consumers of the API (reporting tools, customer portals) display inconsistent financial data

**Column Mapping Reference:** `data/mappings/column_mappings.md` lines 82-86 define independent transformations for each component with no cross-field rule.

### Where the Failure Manifests
- `GET /api/loans/{loanId}/payments` returns mathematically inconsistent payment breakdowns
- Any downstream system computing "remaining principal" by subtracting principal payments will produce wrong balances
- Financial reconciliation reports will not balance

### Why the Code Doesn't Catch It
- `parseLegacyAmount()` (line 152-155) only validates that the string is parseable — it has no concept of business rules
- `toPaymentDto()` treats each field as independent — no relational validation
- No `@PostLoad` hook or entity listener validates data after hydration from the database

---

## 2. Numeric Parsing Without Error Handling (Critical)

### Anomaly
Financial amounts stored as VARCHAR with commas (`"285,000"`) are parsed via `new BigDecimal(amount.replace(",", ""))` which throws unhandled `NumberFormatException` for malformed data.

### Code Trace

**Entry Points:** All service methods that return DTOs:
- `getAllLoans()` → `toLoanSummary()` → `parseLegacyAmount()`, `parseLegacyDecimal()`
- `getAllBorrowers()` → `toBorrowerDto()` → `parseLegacyInteger()`
- `getPaymentsByLoan()` → `toPaymentDto()` → `parseLegacyAmount()`

**Critical Parse Methods:**

```java
// LoanService.java:152-155
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));  // THROWS on "$", "N/A", etc.
}

// LoanService.java:157-160
private BigDecimal parseLegacyDecimal(String value) {
    if (value == null || value.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(value.trim());  // THROWS on non-numeric content
}

// LoanService.java:162-165
private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());  // THROWS on non-integer strings
}
```

**Root Cause:** The parse methods implement a **null/blank check only**. Any non-null, non-blank value that is not a valid number causes an unhandled `NumberFormatException`. This exception:
1. Propagates up through the stream operation in `getAllLoans()` / `getAllBorrowers()`
2. Terminates the entire stream (no partial results)
3. Reaches the controller with no `@ExceptionHandler` configured
4. Returns HTTP 500 with a stack trace to the client

**Specific Failure Path:**
1. Legacy ETL inserts a record with `LN_CURR_BAL = '$142,567.90'` (dollar sign included)
2. `getAllLoans()` iterates all loan accounts via stream
3. For the problematic account, `parseLegacyAmount("$142,567.90")` executes
4. `"$142,567.90".replace(",", "")` → `"$142567.90"` — comma removed but `$` remains
5. `new BigDecimal("$142567.90")` throws `NumberFormatException`
6. The **entire** `/api/loans` endpoint fails — all loans are unavailable

**Column Mapping Reference:** `data/mappings/column_mappings.md` lines 22, 37-38, 53-57, 64-65, 71, 82-86 all specify "Remove commas, parse → decimal" but don't address other noise characters.

### Where the Failure Manifests
- `GET /api/loans` — returns HTTP 500 if ANY loan has malformed amounts
- `GET /api/borrowers` — returns HTTP 500 if ANY borrower has malformed credit score or income
- `GET /api/loans/{id}/payments` — returns HTTP 500 if ANY payment has malformed amounts
- One bad record makes the entire collection endpoint unusable

### Why the Code Doesn't Catch It
- No try-catch around `BigDecimal` constructor or `Integer.parseInt()`
- Stream operations have no per-element error handling (`.map(this::toLoanSummary)` is all-or-nothing)
- No global exception handler configured in the Spring controller layer
- Legacy CDW systems commonly have data entry errors that produce non-numeric content in numeric fields

---

## 3. Null Values in Required Fields Causing "null" String Pollution (High)

### Anomaly
The schema has no NOT NULL constraints. The service layer concatenates entity fields without null guards, producing the literal string `"null"` in API responses.

### Code Trace

**Critical String Concatenation Points:**

```java
// LoanService.java:106 — Borrower name in loan summary
dto.setBorrowerName(acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName());

// LoanService.java:114-115 — Property address construction
dto.setPropertyAddress(acct.getPropertyAddress() + ", " + acct.getPropertyCity()
        + ", " + acct.getPropertyState() + " " + acct.getPropertyZip());

// LoanService.java:124 — Full name construction (has partial null check)
String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
dto.setFullName(borrower.getFirstName() + middle + " " + borrower.getLastName());
```

**Root Cause:** Java's `+` operator on `String` converts `null` references to the literal string `"null"`. For example:
```java
String first = null;
String result = first + " Smith";  // result = "null Smith"
```

The code at line 106 assumes `getBorrowerFirstName()` and `getBorrowerLastName()` are never null. This assumption is enforced **nowhere**:
- The entity class `LegacyLoanAccount` has no validation annotations
- The schema (`schema-legacy.sql` line 54-56) defines the columns as nullable `VARCHAR(50)`
- The repository returns whatever the database contains

**Specific Failure Path:**
1. A legacy record is inserted with: `INSERT INTO CDW_LN_ACCT VALUES ('LN-ERR-001', 'B-10001', NULL, 'Mitchell', ...)`
2. `loanAccountRepository.findAll()` returns this entity with `borrowerFirstName = null`
3. `toLoanSummary()` executes: `null + " " + "Mitchell"` → `"null Mitchell"`
4. API returns `{"borrowerName": "null Mitchell", ...}` — literal "null" text in the response
5. Customer portal displays "null Mitchell" to the end user

**For property address (line 114-115):**
1. If `propertyCity` is null: `"742 Elm Street" + ", " + null + ", " + "IL" + " " + "62701"`
2. Result: `"742 Elm Street, null, IL 62701"`

**Column Mapping Reference:** `data/mappings/column_mappings.md` shows `BORR_FST_NM`, `BORR_LST_NM` are "Direct copy" — no mention of null handling strategy.

### Where the Failure Manifests
- `GET /api/loans` — `borrowerName` field contains "null" text
- `GET /api/loans/{id}` — `propertyAddress` field contains "null" text
- `GET /api/borrowers` — `fullName` field contains "null" text
- These "null" strings pass all downstream validation (they're valid strings) but are semantically garbage

### Why the Code Doesn't Catch It
- Java's `+` operator silently converts null to "null" instead of throwing NPE
- The `toBorrowerDto()` method (line 123) shows awareness of the null issue for `middleInitial` (has a ternary check) but doesn't apply the same pattern to first/last name
- No input validation layer exists between the repository and the service
- No integration tests verify output format when fields are null

---

## Summary of Root Causes

| Rank | Anomaly | Root Cause | Fix Location |
|------|---------|-----------|--------------|
| 1 | Payment sum mismatch | No cross-field validation in `toPaymentDto()` | `LoanService.java:134-146` |
| 2 | Numeric parse failures | No try-catch in `parseLegacyAmount/Integer/Decimal()` | `LoanService.java:152-165` |
| 3 | Null string pollution | No null guards in string concatenation | `LoanService.java:106, 114-115, 124` |

All three share a common architectural gap: **the service layer trusts the legacy data to be well-formed**. The fix is to add a validation/sanitization layer between the repository and the DTO mapping logic.
