# Root Cause Analysis — Top 3 Critical Data Anomalies

> **Generated:** 2026-05-08
> **Scope:** Code trace through `LoanService.java`, repository layer, entity mappings, and `data/mappings/column_mappings.md`

---

## RCA-001: SSN Last-4 Contains Phone Number Suffixes (ANO-001)

### Anomaly Summary
All 5 `BORR_SSN_LST4` values in `CDW_LN_ACCT` match the last 4 digits of the corresponding borrower's phone number, not their SSN.

### Code Trace

**1. Data Entry Point — `schema-legacy.sql:57`**
```sql
BORR_SSN_LST4   VARCHAR(4),
```
The column is a VARCHAR(4) with no validation constraint. Any 4-character string is accepted.

**2. Entity Mapping — `LegacyLoanAccount.java:29-30`**
```java
@Column(name = "BORR_SSN_LST4")
private String borrowerSsnLast4;
```
The JPA entity maps this column directly to a `String` field. No validation annotation (`@Pattern`, `@Size`, etc.) is present.

**3. Column Mapping Specification — `column_mappings.md:51`**
```
| BORR_SSN_LST4 | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK |
```
The migration mapping explicitly drops this field, acknowledging it is denormalized. However, the current live code still reads and serves this data.

**4. Service Layer — `LoanService.java:103-118` (`toLoanSummary`)**
The `toLoanSummary()` method does NOT use `borrowerSsnLast4`, so this field does not appear in the loan summary API response. However, the entity loads it from the database and it is available for any downstream code that accesses `LegacyLoanAccount.getBorrowerSsnLast4()`.

**5. No Cross-Validation Exists**
There is no code that validates `BORR_SSN_LST4` against the encrypted SSN (`BORR_SSN_ENCR`) in `CDW_BORR_MSTR`. The borrower repository (`LegacyBorrowerRepository.java`) has no method to look up or verify SSN-related fields.

### Root Cause
The legacy ETL process that populates `CDW_LN_ACCT` extracted the wrong field from the source system. Instead of extracting the last 4 digits of `BORR_SSN_ENCR` (after decryption), it extracted the last 4 characters of `BORR_PH_NBR`. This is a classic ETL column-mapping error. The `VARCHAR` typing and lack of constraints allowed the incorrect data to persist undetected.

### Where This Would Cause a Runtime Failure
- **Direct failure:** No immediate runtime exception since the field is a `String` and is currently unused by the API.
- **Incorrect API response:** If any future code exposes `borrowerSsnLast4` (e.g., for identity verification), it will return phone digits masquerading as SSN digits — a PII compliance violation.
- **Migration corruption:** If migration code (Task 2 in `MIGRATION_TASKS.md`) were to use `BORR_SSN_LST4` to verify borrower identity during foreign key resolution, it would match on wrong data and potentially link records incorrectly.

---

## RCA-002: Payment Component Mismatch ($400 Discrepancy) (ANO-002)

### Anomaly Summary
For loan `LN-2019-00142`, the sum `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT` equals $1,887.02, but `PMT_AMT` is $1,487.02 — a $400.00 discrepancy in both payment records.

### Code Trace

**1. Data Entry Point — `data-legacy.sql:27-28`**
```sql
INSERT INTO CDW_PMT_HIST VALUES ('PMT-2025120001', 'LN-2019-00142', '12/15/2025',
  '1,487.02', '456.78', '1,074.69', '355.55', '0.00', ...);
```
The `PMT_AMT` is `1,487.02`. The components are `456.78 + 1,074.69 + 355.55 = 1,887.02`.

**2. Schema — `schema-legacy.sql:84-98`**
```sql
PMT_AMT         VARCHAR(15),        -- total payment as string
PMT_PRIN_AMT    VARCHAR(15),        -- principal portion
PMT_INT_AMT     VARCHAR(15),        -- interest portion
PMT_ESCROW_AMT  VARCHAR(15),        -- escrow portion
```
No CHECK constraint enforcing `PMT_AMT = PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT`.

**3. Entity Mapping — `LegacyPayment.java:25-35`**
```java
@Column(name = "PMT_AMT")
private String totalAmount;
@Column(name = "PMT_PRIN_AMT")
private String principalAmount;
@Column(name = "PMT_INT_AMT")
private String interestAmount;
@Column(name = "PMT_ESCROW_AMT")
private String escrowAmount;
```
All mapped as independent `String` fields. No cross-field validation.

**4. Service Layer — `LoanService.java:134-147` (`toPaymentDto`)**
```java
dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
```
Each component is parsed independently. No validation checks that components sum to the total. The `PaymentDto` is returned to the API consumer with inconsistent financial data.

**5. Column Mapping Specification — `column_mappings.md:82-86`**
```
| PMT_AMT      | VARCHAR(15) | total_amount     | DECIMAL(10,2) | Remove commas, parse → decimal |
| PMT_PRIN_AMT | VARCHAR(15) | principal_amount | DECIMAL(10,2) | Remove commas, parse → decimal |
```
The migration spec treats each field independently — no cross-field validation is specified.

### Root Cause
The source system likely calculates `PMT_AMT` as the borrower's contractual monthly payment ($1,487.02, matching `CDW_LN_ACCT.LN_PMT_AMT`), but the component breakdown was generated by a separate amortization calculation that includes escrow. The mismatch suggests the total was sourced from the loan terms while the components came from the payment processing engine, and they were never reconciled. The $400 excess in the components likely means the escrow amount ($355.55) was double-counted or the P&I split was computed against a different base.

### Where This Would Cause a Runtime Failure
- **Incorrect API response:** `GET /api/loans/{loanId}/payments` returns `PaymentDto` where `totalAmount` (1,487.02) does not equal `principalAmount + interestAmount + escrowAmount` (1,887.02). Any front-end that displays a payment breakdown will show numbers that don't add up.
- **Migration data loss:** When migrating to the modern `payments` table (which has `DECIMAL` columns), the inconsistency will be preserved silently since there's no constraint in the migration spec.
- **Financial reconciliation failure:** Downstream accounting systems consuming this API will flag a $400 discrepancy per payment period.

---

## RCA-003: Numeric Strings with Commas — Unhandled Parse Failures (ANO-004)

### Anomaly Summary
All monetary amounts, credit scores, term months, and percentages are stored as `VARCHAR` strings. Amounts include comma formatting (e.g., `'285,000'`) that will cause `NumberFormatException` if parsed without preprocessing.

### Code Trace

**1. Data Entry Point — `data-legacy.sql` (throughout)**
```sql
-- Amounts with commas
'285,000', '271,432.56', '1,487.02'
-- Integers as strings
'745', '360', '15'
-- Decimals as strings
'4.750', '82.5'
```

**2. Schema — `schema-legacy.sql` (throughout)**
```sql
BORR_CRDT_SCR   VARCHAR(5),         -- credit score as string
BORR_ANN_INCM   VARCHAR(15),        -- annual income as string with commas
LN_ORIG_AMT     VARCHAR(15),        -- original amount as string
LN_INT_RT       VARCHAR(8),         -- interest rate as string "5.250"
```
Every numeric value is `VARCHAR`. The schema comments acknowledge the pattern but don't enforce any format.

**3. Service Layer — `LoanService.java:152-165` (parsing methods)**
```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));
}

private BigDecimal parseLegacyDecimal(String value) {
    if (value == null || value.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(value.trim());
}

private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());
}
```

**Key vulnerabilities in the parsing methods:**

| Method | Handles null/blank | Handles commas | Handles non-numeric | Catches exceptions |
|--------|-------------------|----------------|---------------------|-------------------|
| `parseLegacyAmount` | Yes (returns ZERO) | Yes (removes commas) | No | No |
| `parseLegacyDecimal` | Yes (returns ZERO) | **No** | No | No |
| `parseLegacyInteger` | Yes (returns null) | **No** | No | No |

**4. Specific failure paths:**

- **`parseLegacyDecimal`** is used for interest rates (`acct.getInterestRate()`). If a rate were stored with an unexpected character (e.g., `'4.750%'` with a percent sign), it would throw `NumberFormatException` — unhandled.
- **`parseLegacyInteger`** is used for credit scores (`borrower.getCreditScore()`). If a credit score were stored as `'N/A'` or blank, `Integer.parseInt("N/A")` throws `NumberFormatException`. The null/blank check handles those cases, but non-numeric non-blank strings are not caught.
- **`parseLegacyAmount`** handles commas correctly but does not catch `NumberFormatException` for other malformed inputs (e.g., `'$285,000'` with a dollar sign, or `'285,000-'` with a trailing dash from mainframe data).

**5. Column Mapping Specification — `column_mappings.md:20-22`**
```
| BORR_CRDT_SCR | VARCHAR(5) | credit_score    | INTEGER      | Parse string → integer |
| BORR_ANN_INCM | VARCHAR(15)| annual_income   | DECIMAL(12,2)| Remove commas, parse → decimal |
```
The mapping spec acknowledges the transformation but doesn't specify error handling for malformed data.

### Root Cause
The legacy CDW schema was designed as a staging/reporting layer where all data arrives as flat strings from mainframe COBOL systems (which natively format numbers with commas). The application was built to read directly from this staging layer rather than a properly typed operational database. The `LoanService` parsing methods were written for the "happy path" — they handle null/blank but not malformed data. No try-catch blocks protect against `NumberFormatException`.

### Where This Would Cause a Runtime Failure
- **Unhandled `NumberFormatException`:** Any non-numeric, non-null value in an amount field will crash the corresponding API endpoint with a 500 Internal Server Error. For example, if `BORR_ANN_INCM` contains `'N/A'` instead of a number, calling `GET /api/borrowers/B-10005` will throw an unhandled exception.
- **Silent zero-substitution:** Null or blank amounts are silently converted to `BigDecimal.ZERO`, which could misrepresent a missing payment as a $0 payment — a material difference for financial reporting.
- **`parseLegacyDecimal` does not strip commas:** If an interest rate or LTV value were stored with comma formatting (e.g., `'1,234'`), it would throw `NumberFormatException` since `parseLegacyDecimal` only trims whitespace but does not remove commas.

---

## Summary of Recommended Code Changes

| Priority | Action | File(s) |
|----------|--------|---------|
| 1 | Add try-catch with logging around all `parseLegacy*` methods | `LoanService.java` |
| 2 | Add payment component sum validation in `toPaymentDto()` | `LoanService.java` |
| 3 | Add referential integrity checks (borrower ID, product code, loan account) | `LoanService.java` |
| 4 | Add date format validation for all `MM/DD/YYYY` string fields | `LoanService.java` (new validation utility) |
| 5 | Add delinquency/status cross-field validation | `LoanService.java` |
| 6 | Flag `BORR_SSN_LST4` as untrusted; exclude from migration | Migration scripts |
