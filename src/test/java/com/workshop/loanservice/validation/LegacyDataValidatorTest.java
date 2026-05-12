package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.validation.DataQualityIssue.Severity;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for LegacyDataValidator covering each anomaly type from
 * docs/DATA_ANOMALY_REPORT.md: payment sum mismatch, numeric parsing,
 * null required fields, date validation, delinquency/status inconsistency,
 * denormalized name divergence, credit score range, and late payment detection.
 */
class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // Safe parsing utility tests (ANO-003)
    // =========================================================================

    @Nested
    @DisplayName("ANO-003: Numeric string parsing safety")
    class NumericParsingSafety {

        @Test
        @DisplayName("safeParseAmount handles valid comma-separated amounts")
        void safeParseAmount_validCommaAmount() {
            assertEquals(new BigDecimal("285000"), validator.safeParseAmount("285,000"));
            assertEquals(new BigDecimal("1487.02"), validator.safeParseAmount("1,487.02"));
        }

        @Test
        @DisplayName("safeParseAmount returns null for unparseable values instead of throwing")
        void safeParseAmount_unparseableReturnsNull() {
            // Currency symbol prefix — common legacy data issue
            assertNull(validator.safeParseAmount("$92,500"));
            // Letters in numeric field
            assertNull(validator.safeParseAmount("N/A"));
            // Double decimal point
            assertNull(validator.safeParseAmount("100.00.00"));
            // Random text
            assertNull(validator.safeParseAmount("TBD"));
        }

        @Test
        @DisplayName("safeParseAmount returns null for null and blank")
        void safeParseAmount_nullAndBlank() {
            assertNull(validator.safeParseAmount(null));
            assertNull(validator.safeParseAmount(""));
            assertNull(validator.safeParseAmount("   "));
        }

        @Test
        @DisplayName("safeParseDecimal handles valid decimal strings")
        void safeParseDecimal_valid() {
            assertEquals(new BigDecimal("5.250"), validator.safeParseDecimal("5.250"));
            assertEquals(new BigDecimal("82.5"), validator.safeParseDecimal("82.5"));
        }

        @Test
        @DisplayName("safeParseDecimal returns null for unparseable values")
        void safeParseDecimal_unparseable() {
            // Percentage symbol — common legacy data issue
            assertNull(validator.safeParseDecimal("82.5%"));
            assertNull(validator.safeParseDecimal("abc"));
        }

        @Test
        @DisplayName("safeParseInt handles valid integer strings")
        void safeParseInt_valid() {
            assertEquals(360, validator.safeParseInt("360"));
            assertEquals(0, validator.safeParseInt("0"));
            assertEquals(15, validator.safeParseInt("15"));
        }

        @Test
        @DisplayName("safeParseInt returns null for unparseable values")
        void safeParseInt_unparseable() {
            assertNull(validator.safeParseInt("abc"));
            assertNull(validator.safeParseInt("3.5"));
            assertNull(validator.safeParseInt("N/A"));
        }

        @Test
        @DisplayName("safeParseLegacyDate handles valid MM/dd/yyyy dates")
        void safeParseLegacyDate_valid() {
            assertNotNull(validator.safeParseLegacyDate("03/15/1978"));
            assertNotNull(validator.safeParseLegacyDate("12/31/2025"));
        }

        @Test
        @DisplayName("safeParseLegacyDate returns null for invalid dates")
        void safeParseLegacyDate_invalid() {
            // Wrong format (ISO)
            assertNull(validator.safeParseLegacyDate("2025-03-15"));
            // Invalid day (Feb 30 does not exist in any year)
            assertNull(validator.safeParseLegacyDate("02/30/2021"));
            // Random text
            assertNull(validator.safeParseLegacyDate("not-a-date"));
            assertNull(validator.safeParseLegacyDate(null));
        }
    }

    // =========================================================================
    // Borrower validation tests
    // =========================================================================

    @Nested
    @DisplayName("Borrower validation")
    class BorrowerValidation {

        @Test
        @DisplayName("ANO-005: Detects null required fields on borrower")
        void detectsNullRequiredFields() {
            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-TEST");
            // Leave firstName, lastName, email null

            List<DataQualityIssue> issues = validator.validateBorrower(borrower);

            // Should flag null first name, last name, and email
            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("BORR_FST_NM") && i.getSeverity() == Severity.HIGH));
            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("BORR_LST_NM") && i.getSeverity() == Severity.HIGH));
            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("BORR_EMAIL_ADDR") && i.getSeverity() == Severity.MEDIUM));
        }

        @Test
        @DisplayName("ANO-003: Detects unparseable credit score")
        void detectsUnparseableCreditScore() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("N/A");

            List<DataQualityIssue> issues = validator.validateBorrower(borrower);

            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("BORR_CRDT_SCR")
                            && i.getSeverity() == Severity.CRITICAL
                            && i.getDescription().contains("Unparseable")));
        }

        @Test
        @DisplayName("ANO-010: Detects out-of-range credit score")
        void detectsOutOfRangeCreditScore() {
            LegacyBorrower borrower = createValidBorrower();
            // Credit score above valid FICO range (300-850)
            borrower.setCreditScore("999");

            List<DataQualityIssue> issues = validator.validateBorrower(borrower);

            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("BORR_CRDT_SCR")
                            && i.getSeverity() == Severity.LOW
                            && i.getDescription().contains("out of range")));
        }

        @Test
        @DisplayName("ANO-003: Detects unparseable annual income")
        void detectsUnparseableAnnualIncome() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setAnnualIncome("$92,500");

            List<DataQualityIssue> issues = validator.validateBorrower(borrower);

            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("BORR_ANN_INCM")
                            && i.getSeverity() == Severity.CRITICAL));
        }

        @Test
        @DisplayName("ANO-008: Detects invalid date format on borrower")
        void detectsInvalidDateFormat() {
            LegacyBorrower borrower = createValidBorrower();
            // ISO format instead of expected MM/DD/YYYY
            borrower.setDateOfBirth("1978-03-15");

            List<DataQualityIssue> issues = validator.validateBorrower(borrower);

            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("BORR_DOB_DT")
                            && i.getDescription().contains("Unparseable date")));
        }

        @Test
        @DisplayName("Valid borrower produces no issues")
        void validBorrowerNoIssues() {
            LegacyBorrower borrower = createValidBorrower();

            List<DataQualityIssue> issues = validator.validateBorrower(borrower);

            assertTrue(issues.isEmpty(), "Valid borrower should have no issues but got: " + issues);
        }
    }

    // =========================================================================
    // Loan account validation tests
    // =========================================================================

    @Nested
    @DisplayName("Loan account validation")
    class LoanAccountValidation {

        @Test
        @DisplayName("ANO-004: Detects delinquency days vs active status inconsistency")
        void detectsDelinquencyStatusInconsistency() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setDelinquencyDays("15");
            acct.setStatusCode("ACT");

            List<DataQualityIssue> issues = validator.validateLoanAccount(acct);

            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("LN_DLQ_DAYS/LN_STAT_CD")
                            && i.getSeverity() == Severity.HIGH
                            && i.getDescription().contains("delinquency days but status is ACT")));
        }

        @Test
        @DisplayName("ANO-005: Detects null required fields on loan account")
        void detectsNullRequiredLoanFields() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-TEST");
            // Leave borrowerId, productCode null

            List<DataQualityIssue> issues = validator.validateLoanAccount(acct);

            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("BORR_ID") && i.getSeverity() == Severity.HIGH));
            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("PROD_CD") && i.getSeverity() == Severity.HIGH));
        }

        @Test
        @DisplayName("ANO-003: Detects unparseable loan amount")
        void detectsUnparseableLoanAmount() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setOriginalAmount("$285,000");

            List<DataQualityIssue> issues = validator.validateLoanAccount(acct);

            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("LN_ORIG_AMT")
                            && i.getSeverity() == Severity.CRITICAL));
        }

        @Test
        @DisplayName("Detects unknown loan status code")
        void detectsUnknownLoanStatus() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setStatusCode("XYZ");

            List<DataQualityIssue> issues = validator.validateLoanAccount(acct);

            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("LN_STAT_CD")
                            && i.getDescription().contains("Unknown loan status")));
        }

        @Test
        @DisplayName("Detects maturity date before origination date")
        void detectsInvalidDateRange() {
            LegacyLoanAccount acct = createValidLoanAccount();
            // Maturity before origination
            acct.setOriginationDate("02/15/2049");
            acct.setMaturityDate("02/15/2019");

            List<DataQualityIssue> issues = validator.validateLoanAccount(acct);

            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("LN_ORIG_DT/LN_MAT_DT")
                            && i.getDescription().contains("not after origination")));
        }

        @Test
        @DisplayName("Valid loan account produces no issues")
        void validLoanNoIssues() {
            LegacyLoanAccount acct = createValidLoanAccount();

            List<DataQualityIssue> issues = validator.validateLoanAccount(acct);

            assertTrue(issues.isEmpty(), "Valid loan should have no issues but got: " + issues);
        }
    }

    // =========================================================================
    // Denormalized name validation tests (ANO-007)
    // =========================================================================

    @Nested
    @DisplayName("ANO-007: Denormalized borrower name divergence")
    class DenormalizedNameValidation {

        @Test
        @DisplayName("Detects first name divergence between loan and borrower master")
        void detectsFirstNameDivergence() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setBorrowerFirstName("Jim");

            LegacyBorrower borrower = createValidBorrower();
            borrower.setFirstName("James");

            List<DataQualityIssue> issues = validator.validateDenormalizedBorrowerName(acct, borrower);

            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("BORR_FST_NM")
                            && i.getDescription().contains("diverges")));
        }

        @Test
        @DisplayName("Detects orphaned loan — borrower not found (ANO-006)")
        void detectsOrphanedLoan() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setBorrowerId("B-NONEXISTENT");

            List<DataQualityIssue> issues = validator.validateDenormalizedBorrowerName(acct, null);

            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("BORR_ID")
                            && i.getSeverity() == Severity.HIGH
                            && i.getDescription().contains("non-existent borrower")));
        }

        @Test
        @DisplayName("Matching names produce no issues")
        void matchingNamesNoIssues() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setBorrowerFirstName("James");
            acct.setBorrowerLastName("Mitchell");

            LegacyBorrower borrower = createValidBorrower();
            borrower.setFirstName("James");
            borrower.setLastName("Mitchell");

            List<DataQualityIssue> issues = validator.validateDenormalizedBorrowerName(acct, borrower);

            assertTrue(issues.isEmpty(), "Matching names should have no issues but got: " + issues);
        }
    }

    // =========================================================================
    // Payment validation tests
    // =========================================================================

    @Nested
    @DisplayName("Payment validation")
    class PaymentValidation {

        @Test
        @DisplayName("ANO-001: Detects payment component sum mismatch")
        void detectsPaymentSumMismatch() {
            LegacyPayment pmt = createValidPayment();
            // Total = 1,487.02 but components sum to 1,887.02 (off by 400)
            pmt.setTotalAmount("1,487.02");
            pmt.setPrincipalAmount("456.78");
            pmt.setInterestAmount("1,074.69");
            pmt.setEscrowAmount("355.55");
            pmt.setLateFee("0.00");

            List<DataQualityIssue> issues = validator.validatePayment(pmt);

            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("PMT_AMT")
                            && i.getSeverity() == Severity.CRITICAL
                            && i.getDescription().contains("do not sum to total")));
        }

        @Test
        @DisplayName("ANO-001: Accepts payment where components sum correctly")
        void acceptsValidPaymentSum() {
            LegacyPayment pmt = createValidPayment();
            // Components sum correctly: 1842.56 + 815.50 + 266.12 + 0.00 = 2924.18
            pmt.setTotalAmount("2,924.18");
            pmt.setPrincipalAmount("1,842.56");
            pmt.setInterestAmount("815.50");
            pmt.setEscrowAmount("266.12");
            pmt.setLateFee("0.00");

            List<DataQualityIssue> issues = validator.validatePayment(pmt);

            assertTrue(issues.stream().noneMatch(i ->
                    i.getField().equals("PMT_AMT")
                            && i.getDescription().contains("do not sum")),
                    "Valid payment sum should not be flagged");
        }

        @Test
        @DisplayName("ANO-003: Detects unparseable payment amounts")
        void detectsUnparseablePaymentAmounts() {
            LegacyPayment pmt = createValidPayment();
            pmt.setTotalAmount("$1,487.02");

            List<DataQualityIssue> issues = validator.validatePayment(pmt);

            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("PMT_AMT")
                            && i.getSeverity() == Severity.CRITICAL
                            && i.getDescription().contains("Unparseable")));
        }

        @Test
        @DisplayName("ANO-005: Detects null required loan account number")
        void detectsNullLoanAccountNumber() {
            LegacyPayment pmt = createValidPayment();
            pmt.setLoanAccountNumber(null);

            List<DataQualityIssue> issues = validator.validatePayment(pmt);

            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("LN_ACCT_NBR") && i.getSeverity() == Severity.HIGH));
        }

        @Test
        @DisplayName("ANO-009: Detects late payment receipt")
        void detectsLatePaymentReceipt() {
            LegacyPayment pmt = createValidPayment();
            pmt.setPaymentDate("12/01/2025");
            pmt.setReceivedDate("12/05/2025");

            List<DataQualityIssue> issues = validator.validatePayment(pmt);

            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("PMT_RECV_DT")
                            && i.getDescription().contains("days after due date")));
        }

        @Test
        @DisplayName("Detects unknown payment type code")
        void detectsUnknownPaymentType() {
            LegacyPayment pmt = createValidPayment();
            pmt.setTypeCode("ZZZ");

            List<DataQualityIssue> issues = validator.validatePayment(pmt);

            assertTrue(issues.stream().anyMatch(i ->
                    i.getField().equals("PMT_TYP_CD")
                            && i.getDescription().contains("Unknown payment type")));
        }

        @Test
        @DisplayName("Valid payment produces no issues")
        void validPaymentNoIssues() {
            LegacyPayment pmt = createValidPayment();

            List<DataQualityIssue> issues = validator.validatePayment(pmt);

            assertTrue(issues.isEmpty(), "Valid payment should have no issues but got: " + issues);
        }
    }

    // =========================================================================
    // Test data builders — create valid baseline entities for mutation testing
    // =========================================================================

    private LegacyBorrower createValidBorrower() {
        LegacyBorrower b = new LegacyBorrower();
        b.setBorrowerId("B-10001");
        b.setFirstName("James");
        b.setLastName("Mitchell");
        b.setMiddleInitial("R");
        b.setSsnEncrypted("ENC_XXX_001");
        b.setDateOfBirth("03/15/1978");
        b.setAddressLine1("742 Elm Street");
        b.setCity("Springfield");
        b.setStateCode("IL");
        b.setZipCode("62701");
        b.setPhoneNumber("217-555-0142");
        b.setEmail("j.mitchell@email.com");
        b.setCreditScore("745");
        b.setEmploymentStatus("EMPLOYED");
        b.setAnnualIncome("92,500");
        b.setCreatedDate("01/15/2019");
        b.setUpdatedDate("11/03/2025");
        b.setStatusCode("ACT");
        b.setRecordType("PRI");
        return b;
    }

    private LegacyLoanAccount createValidLoanAccount() {
        LegacyLoanAccount a = new LegacyLoanAccount();
        a.setLoanAccountNumber("LN-2019-00142");
        a.setBorrowerId("B-10001");
        a.setBorrowerFirstName("James");
        a.setBorrowerLastName("Mitchell");
        a.setBorrowerSsnLast4("0142");
        a.setProductCode("FXD30");
        a.setOriginalAmount("285,000");
        a.setCurrentBalance("271,432.56");
        a.setInterestRate("4.750");
        a.setTermMonths("360");
        a.setMonthlyPayment("1,487.02");
        a.setOriginationDate("02/15/2019");
        a.setMaturityDate("02/15/2049");
        a.setFirstPaymentDate("03/15/2019");
        a.setNextPaymentDate("01/15/2026");
        a.setStatusCode("ACT");
        a.setDelinquencyDays("0");
        a.setEscrowBalance("3,245.80");
        a.setLtvPercent("82.5");
        a.setPropertyAddress("742 Elm Street");
        a.setPropertyCity("Springfield");
        a.setPropertyState("IL");
        a.setPropertyZip("62701");
        a.setPropertyType("SFR");
        a.setAppraisedValue("345,000");
        a.setCreatedDate("02/01/2019");
        a.setUpdatedDate("12/01/2025");
        return a;
    }

    private LegacyPayment createValidPayment() {
        LegacyPayment p = new LegacyPayment();
        p.setPaymentSequenceNumber("PMT-TEST001");
        p.setLoanAccountNumber("LN-2019-00142");
        p.setPaymentDate("12/15/2025");
        // Components sum correctly: 1842.56 + 815.50 + 266.12 + 0.00 = 2924.18
        p.setTotalAmount("2,924.18");
        p.setPrincipalAmount("1,842.56");
        p.setInterestAmount("815.50");
        p.setEscrowAmount("266.12");
        p.setLateFee("0.00");
        p.setTypeCode("REG");
        p.setStatusCode("PST");
        p.setReceivedDate("12/14/2025");
        p.setProcessedDate("12/15/2025");
        p.setCreatedDate("12/15/2025");
        p.setUpdatedDate("12/15/2025");
        return p;
    }
}
