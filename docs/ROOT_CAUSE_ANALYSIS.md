# Root Cause Analysis — Top 3 Critical Data Anomalies

**Generated:** 2026-05-07
**Related:** [DATA_ANOMALY_REPORT.md](DATA_ANOMALY_REPORT.md)

---

## RCA-1: SSN Last-4 Contains Phone Number Digits (ANO-001)

### Anomaly Summary

The `BORR_SSN_LST4` field in `CDW_LN_ACCT` contains the last 4 digits of the borrower's phone number for all 5 loan records (100% of records affected).

### Code Path Trace

1. **Data ingestion:** The `CDW_LN_ACCT` table is loaded from `data-legacy.sql` at application startup via Spring SQL init (`spring.sql.init.data-locations`).

2. **Entity mapping:** `LegacyLoanAccount.java` maps the column at line 29-30:
   ```java
   @Column(name = "BORR_SSN_LST4")
   private String borrowerSsnLast4;
   ```
   The field is read as a plain string with no validation.

3. **Service layer usage:** `LoanService.java` does **not** currently use `borrowerSsnLast4` in any DTO mapping — it is loaded by JPA but never exposed to the API. The `toLoanSummary()` method (line 103-118) only reads `getBorrowerFirstName()` and `getBorrowerLastName()` from the loan account.

4. **Column mappings:** `data/mappings/column_mappings.md` line 51 marks this field as "*(dropped)*" in the modern schema, meaning it would be silently discarded during migration without anyone noticing the corruption.

### Root Cause

The legacy CDW ETL pipeline that populated `CDW_LN_ACCT` has a **column mapping error** in its source-to-target specification. The source field for `BORR_SSN_LST4` is mapped to the phone number column (`BORR_PH_NBR`) instead of the encrypted SSN column (`BORR_SSN_ENCR`). This is confirmed by the exact 4-digit match between every borrower's phone suffix and their `BORR_SSN_LST4` value.

### Where It Would Cause Runtime Failure

- **Current service:** No immediate runtime failure because the field is not used in DTO construction. However, any future code that uses `getBorrowerSsnLast4()` for identity verification (e.g., a "verify last 4 of SSN" API endpoint) would return phone digits, causing verification failures.
- **Data migration:** The column mappings document marks this field as dropped, so the corrupted data would be silently discarded. If a future task adds SSN last-4 to the modern schema, re-extracting from the CDW would reintroduce the same bug unless the ETL is fixed.
- **Downstream consumers:** Any system reading directly from `CDW_LN_ACCT` for KYC (Know Your Customer) checks uses wrong PII data.

### Recommended Resolution

1. Add a validation check in the service layer that flags when `BORR_SSN_LST4` matches the last 4 of the borrower's phone number.
2. Do not use `BORR_SSN_LST4` from `CDW_LN_ACCT` for any identity verification until the upstream ETL is fixed.
3. File a defect against the CDW ETL team to correct the source mapping.

---

## RCA-2: Payment Component Amounts Do Not Sum to Total (ANO-002)

### Anomaly Summary

Three payment records have component amounts (principal + interest + escrow + late fee) that do not match the stated total:
- PMT-2025120001: sum=1,887.02 vs total=1,487.02 (diff=+400.00)
- PMT-2025110001: sum=1,887.02 vs total=1,487.02 (diff=+400.00)
- PMT-2025110003: sum=1,124.55 vs total=1,077.05 (diff=+47.50)

### Code Path Trace

1. **Data ingestion:** Payment records are loaded from `data-legacy.sql` lines 27-36 into `CDW_PMT_HIST`.

2. **Entity mapping:** `LegacyPayment.java` maps all amount fields as plain strings:
   ```java
   @Column(name = "PMT_AMT")      private String totalAmount;      // line 25-26
   @Column(name = "PMT_PRIN_AMT") private String principalAmount;  // line 28-29
   @Column(name = "PMT_INT_AMT")  private String interestAmount;   // line 31-32
   @Column(name = "PMT_ESCROW_AMT") private String escrowAmount;   // line 34-35
   @Column(name = "PMT_LATE_FEE") private String lateFee;          // line 37-38
   ```

3. **Service layer transformation:** `LoanService.toPaymentDto()` (line 134-147) independently parses each amount:
   ```java
   dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
   dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
   dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
   dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
   dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
   ```
   Each field is parsed independently with **no cross-field consistency check**. The mismatched values are faithfully converted and returned to the API consumer.

4. **API exposure:** `LoanController.getPayments()` (line 33-36) returns the list directly. An API consumer calling `GET /api/loans/LN-2019-00142/payments` receives payments where `totalAmount != principalAmount + interestAmount + escrowAmount + lateFee`.

### Root Cause

Two distinct root causes:

**PMT-2025120001 and PMT-2025110001 (diff=400.00):** The `PMT_AMT` (total) field appears to represent only the principal + interest portion (1,487.02 is the monthly payment amount from `CDW_LN_ACCT.LN_PMT_AMT`), while the components include escrow (355.55) that is collected separately. The CDW has an **inconsistent definition** of "total payment" — the total field excludes escrow, but the escrow component is populated. The 400.00 difference is approximately `355.55 (escrow) + 44.45` which doesn't match exactly either — indicating the components themselves may be independently sourced from different CDW subsystems.

**PMT-2025110003 (diff=47.50):** The `PMT_AMT` represents the standard payment amount (1,077.05 = monthly payment from `CDW_LN_ACCT`), but a late fee of 47.50 was assessed and recorded in `PMT_LATE_FEE` without updating the total. The late fee was added by a different process (collections/fee assessment) that did not reconcile with the payment record total.

### Where It Would Cause Runtime Failure

- **API response:** `GET /api/loans/{id}/payments` returns inconsistent financial data. Any frontend that displays a payment breakdown and computes `total = sum(components)` will show conflicting numbers.
- **Financial reporting:** Aggregating `totalAmount` across payments produces different sums than aggregating individual components, creating reconciliation failures.
- **Data migration:** The modern schema (`payments` table) has both `total_amount` and component fields as `DECIMAL NOT NULL`. Migrating these records preserves the inconsistency in the new typed schema, making it harder to detect later.

### Recommended Resolution

1. Add a validation check in `toPaymentDto()` that computes the expected total from components and logs a warning when they differ.
2. Include a `componentMismatch` flag or `validationWarnings` list in the `PaymentDto` so API consumers can detect questionable records.
3. For the service layer: when components sum differs from total, trust the components and recompute the total (or vice versa, based on business rules).

---

## RCA-3: No Null/Type Validation on Numeric String Parsing (ANO-003)

### Anomaly Summary

All financial and numeric fields in the legacy schema are nullable VARCHAR with no format constraints. The service layer parsing methods silently convert nulls/blanks to zero or null without validation or logging.

### Code Path Trace

1. **Schema definition:** `schema-legacy.sql` defines all columns as nullable VARCHAR:
   ```sql
   LN_ORIG_AMT  VARCHAR(15),  -- original amount as string
   LN_CURR_BAL  VARCHAR(15),  -- current balance as string
   BORR_CRDT_SCR VARCHAR(5),  -- credit score as string
   ```
   No NOT NULL or CHECK constraints exist on any column.

2. **Service layer parsing:** `LoanService.java` has three parsing methods:

   **`parseLegacyAmount()` (line 152-155):**
   ```java
   private BigDecimal parseLegacyAmount(String amount) {
       if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(amount.replace(",", ""));
   }
   ```
   - Null/blank → silently returns `ZERO` (a $0 loan amount is a data lie, not a safe default)
   - Malformed string (e.g., `"N/A"`, `"$285,000"`, `"TBD"`) → unhandled `NumberFormatException` crashes the entire API call

   **`parseLegacyDecimal()` (line 157-160):**
   ```java
   private BigDecimal parseLegacyDecimal(String value) {
       if (value == null || value.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(value.trim());
   }
   ```
   - Same null→ZERO issue; a 0% interest rate is misleading
   - Does NOT strip commas — would fail on comma-formatted inputs despite being used for the same types of data

   **`parseLegacyInteger()` (line 162-165):**
   ```java
   private Integer parseLegacyInteger(String value) {
       if (value == null || value.isBlank()) return null;
       return Integer.parseInt(value.trim());
   }
   ```
   - Null/blank → returns Java `null`, which can cause `NullPointerException` in downstream code that auto-unboxes to `int`
   - Non-numeric string → unhandled `NumberFormatException`

3. **Call sites in `toLoanSummary()` (line 103-118):**
   ```java
   dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));   // null → $0.00
   dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));   // null → $0.00
   dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));      // null → 0.000%
   dto.setMonthlyPayment(parseLegacyAmount(acct.getMonthlyPayment()));   // null → $0.00
   ```

4. **Call site in `toBorrowerDto()` (line 129):**
   ```java
   dto.setCreditScore(parseLegacyInteger(borrower.getCreditScore()));    // null → null Integer
   ```
   The `BorrowerDto.creditScore` is `Integer` (boxed), so null is acceptable at the DTO level. But JSON serialization may produce `"creditScore": null` which API consumers may not handle.

### Root Cause

The service layer was written with an **optimistic assumption** that legacy data will always be well-formed. The parsing methods handle the null/blank case but treat it as a normal condition (returning zero) rather than an anomaly. There is no try-catch around `new BigDecimal()` or `Integer.parseInt()`, so a single malformed record crashes the entire API endpoint (all loans fail, not just the bad one).

### Where It Would Cause Runtime Failure

- **`NumberFormatException`:** If any CDW record contains a non-numeric value in an amount field (common in real CDWs: `"PENDING"`, `"N/A"`, `"#REF!"`, currency symbols), the entire `GET /api/loans` or `GET /api/borrowers` endpoint returns HTTP 500. There is no per-record error isolation.
- **Silent zeros:** A loan with null `LN_ORIG_AMT` appears as a $0 loan in the API, which is valid JSON but incorrect business data. Consumers cannot distinguish "data missing" from "genuinely zero."
- **Null propagation:** `parseLegacyInteger` returning null flows into `BorrowerDto.creditScore` as null. If any consumer does `if (dto.getCreditScore() > 700)`, it throws `NullPointerException`.

### Recommended Resolution

1. Wrap all parsing methods in try-catch blocks that catch `NumberFormatException`.
2. For required financial fields (loan amounts, payment amounts), throw a domain-specific validation exception rather than returning zero.
3. For optional fields (credit score), return null but document the nullable contract in the DTO.
4. Add per-record error isolation: if one loan record fails validation, log it and skip it rather than failing the entire list endpoint.
5. Add a `LegacyDataValidator` component that validates records at ingestion time before they reach the translation methods.
