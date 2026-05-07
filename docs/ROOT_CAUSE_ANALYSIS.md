# Root Cause Analysis — Top 3 Critical Data Anomalies

---

## RCA-001: SSN Last-4 Field Contains Phone Number Digits (ANM-001)

### Anomaly Summary
Every `BORR_SSN_LST4` value in `CDW_LN_ACCT` matches the last four digits of the corresponding borrower's phone number, not their SSN.

### Code Path Trace

**1. Schema (`schema-legacy.sql:57`)**
```sql
BORR_SSN_LST4   VARCHAR(4),
```
The column is defined as a plain VARCHAR(4) with no constraint, check, or comment indicating its source. It sits between `BORR_LST_NM` and `PROD_CD` in the denormalized loan account table.

**2. Entity (`LegacyLoanAccount.java:29-30`)**
```java
@Column(name = "BORR_SSN_LST4")
private String borrowerSsnLast4;
```
Mapped as a plain String field. No validation annotation.

**3. Service (`LoanService.java:103-118`)**
The `toLoanSummary()` method does **not** use `borrowerSsnLast4` at all — it is read from the database but never exposed in the DTO or validated. However, the field is available via the entity getter and could be used by any future code or direct JPA query.

**4. Column Mappings (`data/mappings/column_mappings.md:51`)**
```
| BORR_SSN_LST4 | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK |
```
The mapping document marks this field as "dropped" in the modern schema, meaning it will be discarded during migration. This is correct if the data is bad, but it also means the contamination is silently ignored.

### Root Cause
The legacy ETL process that populates `CDW_LN_ACCT` extracted the wrong field from the source system. The phone number's last 4 digits (`BORR_PH_NBR` substring) were loaded into `BORR_SSN_LST4` instead of the decrypted SSN's last 4 digits. This is a classic ETL column-mapping error in denormalized warehouse loads where similarly-shaped 4-digit values were swapped.

### Where It Would Cause a Runtime Failure
- **Currently:** No runtime failure because the field is unused in the API layer. But it is silently loaded into every `LegacyLoanAccount` entity.
- **Future risk:** Any code that adds identity verification (e.g., "confirm last 4 of SSN") using this field would produce 100% false negatives. If the modern migration had preserved this field instead of dropping it, the contaminated data would propagate to the new system.
- **Compliance risk:** If an auditor queries `CDW_LN_ACCT` directly (bypassing the API) and uses `BORR_SSN_LST4` for identity matching, every match would be against phone numbers, not SSNs.

### Recommended Remediation
1. Add a validation warning in `LegacyDataValidator` that flags `BORR_SSN_LST4` values matching phone last-4.
2. Ensure the modern migration explicitly drops this field (already planned per `column_mappings.md`).
3. If SSN last-4 is needed in the modern schema, derive it from `CDW_BORR_MSTR.BORR_SSN_ENCR` after decryption.

---

## RCA-002: Payment Component Amounts Do Not Sum to Total (ANM-002)

### Anomaly Summary
For payments on loan `LN-2019-00142`, the sum of principal + interest + escrow + late_fee exceeds the total by exactly $400.00. For loan `LN-2018-00089`, the late fee is excluded from the total.

### Code Path Trace

**1. Seed Data (`data-legacy.sql:27-28`)**
```sql
-- PMT-2025120001: total=1,487.02, principal=456.78, interest=1,074.69, escrow=355.55, late=0.00
-- Sum of components: 456.78 + 1,074.69 + 355.55 + 0.00 = 1,887.02 (≠ 1,487.02)
```

**2. Entity (`LegacyPayment.java:25-37`)**
```java
@Column(name = "PMT_AMT")
private String totalAmount;
@Column(name = "PMT_PRIN_AMT")
private String principalAmount;
@Column(name = "PMT_INT_AMT")
private String interestAmount;
@Column(name = "PMT_ESCROW_AMT")
private String escrowAmount;
@Column(name = "PMT_LATE_FEE")
private String lateFee;
```
All fields are independent VARCHARs. No database-level check constraint ensures `PMT_AMT = PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`.

**3. Service (`LoanService.java:134-147`)**
```java
private PaymentDto toPaymentDto(LegacyPayment pmt) {
    dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
    dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
    dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
    dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
    dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
    ...
}
```
Each field is parsed independently. **No cross-validation** is performed. The API returns all five values as-is, and any consumer that sums the components will get a different number than `totalAmount`.

**4. Column Mappings (`data/mappings/column_mappings.md:82-86`)**
Each component maps to its own decimal column in the modern schema. The same inconsistency would be carried forward.

### Root Cause
Two distinct issues:
1. **Principal inflation (PMT-2025120001/PMT-2025110001):** The principal amounts `456.78` and `454.97` should be `56.78` and `54.97`. At 4.75% on a ~$271K balance, monthly interest ≈ $1,074 and escrow ≈ $355, leaving ~$57 for principal. The leading `4` is a data entry error (extra digit).
2. **Late fee exclusion (PMT-2025110003):** The total `1,077.05` equals the regular payment amount but doesn't include the `47.50` late fee. The source system inconsistently includes/excludes late fees from the total.

### Where It Would Cause a Runtime Failure
- **Incorrect API response:** `GET /api/loans/{id}/payments` returns payment data where components don't sum to total. Any frontend that displays both the total and the breakdown will show conflicting numbers.
- **Financial calculations:** Amortization schedule recomputation using the inflated principal would show the loan paying down ~8x faster than reality. Running balance calculations would be incorrect.
- **Migration failure:** If the modern schema adds a check constraint `total = principal + interest + escrow + late_fee`, these records would fail to insert.

### Recommended Remediation
1. Add a `validatePaymentComponents()` method that checks `|total - sum(components)| < 0.01`.
2. When validation fails, log a warning and flag the payment in the DTO response.
3. For the principal data entry error, correct in the seed data or add a heuristic that detects component sums exceeding totals.

---

## RCA-003: No Foreign Key Constraints — Silent Orphan Handling (ANM-003)

### Anomaly Summary
The legacy schema defines zero foreign key constraints. The service layer silently handles missing referenced records, producing degraded API responses without any error indication.

### Code Path Trace

**1. Schema (`schema-legacy.sql:1-9`)**
```sql
-- These tables simulate a legacy data warehouse with:
--   - No foreign key constraints
```
Explicitly documented as a legacy pattern. The `BORR_ID` in `CDW_LN_ACCT` and `LN_ACCT_NBR` in `CDW_PMT_HIST` are plain VARCHAR columns with no REFERENCES clause.

**2. Repository (`LegacyLoanAccountRepository.java:12`)**
```java
List<LegacyLoanAccount> findByBorrowerId(String borrowerId);
```
Spring Data JPA generates `WHERE BORR_ID = ?`. If the borrower doesn't exist in `CDW_BORR_MSTR`, this returns an empty list — no error.

**3. Service — Product lookup (`LoanService.java:61-62`)**
```java
LegacyLoanProduct product = loanProductRepository.findById(acct.getProductCode())
        .orElse(null);
```
A missing product silently becomes `null`.

**4. Service — Null product handling (`LoanService.java:107`)**
```java
dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
```
If the product is null, the raw product code (e.g., `"FXD30"`) is returned as the description. The API consumer receives a cryptic code instead of `"30-Year Fixed Rate Mortgage"` with no indication that the lookup failed.

**5. Service — Borrower-to-loans (`LoanService.java:81-84`)**
```java
List<LoanSummaryDto> loans = loanAccountRepository.findByBorrowerId(borrowerId)
        .stream()
        .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
        .collect(Collectors.toList());
```
`products.get(acct.getProductCode())` returns `null` from the map if the product code doesn't exist, which flows into `toLoanSummary` where `product` is null. This is the same silent degradation.

**6. Service — Payment lookup (`LoanService.java:90-95`)**
```java
public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
    return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
            .stream()
            .map(this::toPaymentDto)
            .collect(Collectors.toList());
}
```
If the `loanAccountNumber` doesn't exist in `CDW_LN_ACCT`, this returns an empty list. A request for payments on a non-existent loan silently succeeds with zero results — indistinguishable from a loan with no payments.

### Root Cause
Legacy data warehouses typically omit foreign keys for ETL performance (bulk loads are faster without constraint checking). The application code was written to tolerate this by using `orElse(null)` patterns, but this converts data integrity errors into silent data quality degradation.

### Where It Would Cause a Runtime Failure or Incorrect API Response
- **Incorrect response:** A loan with an invalid `PROD_CD` returns the raw code as the product description. Consumers expecting human-readable descriptions get cryptic codes.
- **Missing data:** A borrower whose `BORR_ID` was deleted from the master table would still appear in loan accounts. Fetching that borrower by ID would throw `RuntimeException("Borrower not found")`, but their loans would still be accessible via `/api/loans`.
- **Migration failure:** Migrating to a modern schema with proper FK constraints would fail on any orphaned records. The migration would need to either clean up orphans first or defer FK creation.

### Recommended Remediation
1. Add referential integrity validation in the service layer that checks FK relationships.
2. Log warnings for orphaned records instead of silently returning degraded data.
3. Add an `isComplete` or `warnings` field to DTOs so API consumers know when data quality is degraded.
4. Run an orphan detection query before migration to identify records that would violate FK constraints.
