package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

class DataQualityValidatorTest {

    private DataQualityValidator validator;

    @BeforeEach
    void setUp() {
        validator = new DataQualityValidator();
    }

    // =========================================================================
    // Safe parsing tests
    // =========================================================================

    @Nested
    class SafeParseAmountTests {

        @Test
        void parsesAmountWithCommas() {
            assertEquals(new BigDecimal("285000"), validator.safeParseAmount("285,000"));
        }

        @Test
        void parsesAmountWithCommasAndDecimals() {
            assertEquals(new BigDecimal("1487.02"), validator.safeParseAmount("1,487.02"));
        }

        @Test
        void parsesAmountWithDollarSign() {
            assertEquals(new BigDecimal("92500"), validator.safeParseAmount("$92,500"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.safeParseAmount(null));
        }

        @Test
        void returnsZeroForBlank() {
            assertEquals(BigDecimal.ZERO, validator.safeParseAmount("  "));
        }

        @Test
        void returnsNullForInvalidAmount() {
            assertNull(validator.safeParseAmount("N/A"));
        }

        @Test
        void returnsNullForLetterInAmount() {
            assertNull(validator.safeParseAmount("285,O00"));
        }
    }

    @Nested
    class SafeParseDecimalTests {

        @Test
        void parsesDecimalString() {
            assertEquals(new BigDecimal("4.750"), validator.safeParseDecimal("4.750"));
        }

        @Test
        void handlesCommaInDecimal() {
            assertEquals(new BigDecimal("4750"), validator.safeParseDecimal("4,750"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.safeParseDecimal(null));
        }

        @Test
        void returnsNullForInvalidDecimal() {
            assertNull(validator.safeParseDecimal("abc"));
        }
    }

    @Nested
    class SafeParseIntegerTests {

        @Test
        void parsesIntegerString() {
            assertEquals(745, validator.safeParseInteger("745"));
        }

        @Test
        void handlesLeadingTrailingWhitespace() {
            assertEquals(745, validator.safeParseInteger("  745  "));
        }

        @Test
        void handlesDecimalPoint() {
            assertEquals(745, validator.safeParseInteger("745.0"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.safeParseInteger(null));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.safeParseInteger(""));
        }

        @Test
        void returnsNullForNonNumeric() {
            assertNull(validator.safeParseInteger("N/A"));
        }

        @Test
        void returnsNullForPending() {
            assertNull(validator.safeParseInteger("pending"));
        }
    }

    @Nested
    class SafeParseLegacyDateTests {

        @Test
        void parsesValidDate() {
            LocalDate result = validator.safeParseLegacyDate("03/15/1978");
            assertEquals(LocalDate.of(1978, 3, 15), result);
        }

        @Test
        void returnsNullForInvalidDate() {
            assertNull(validator.safeParseLegacyDate("13/32/2025"));
        }

        @Test
        void returnsNullForIsoFormat() {
            assertNull(validator.safeParseLegacyDate("2025-03-15"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.safeParseLegacyDate(null));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.safeParseLegacyDate("  "));
        }
    }

    // =========================================================================
    // Borrower validation tests
    // =========================================================================

    @Nested
    class BorrowerValidationTests {

        @Test
        void validBorrowerHasNoIssues() {
            LegacyBorrower borrower = createValidBorrower();
            List<DataQualityIssue> issues = validator.validateBorrower(borrower);
            assertTrue(issues.isEmpty(), "Valid borrower should have no issues, got: " + issues);
        }

        @Test
        void detectsNullFirstName() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setFirstName(null);
            List<DataQualityIssue> issues = validator.validateBorrower(borrower);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.CRITICAL
                            && i.getColumn().equals("BORR_FST_NM")));
        }

        @Test
        void detectsNullLastName() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setLastName(null);
            List<DataQualityIssue> issues = validator.validateBorrower(borrower);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.CRITICAL
                            && i.getColumn().equals("BORR_LST_NM")));
        }

        @Test
        void detectsInvalidCreditScore() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("N/A");
            List<DataQualityIssue> issues = validator.validateBorrower(borrower);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.HIGH
                            && i.getColumn().equals("BORR_CRDT_SCR")));
        }

        @Test
        void detectsCreditScoreOutOfRange() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("200");
            List<DataQualityIssue> issues = validator.validateBorrower(borrower);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.MEDIUM
                            && i.getColumn().equals("BORR_CRDT_SCR")));
        }

        @Test
        void detectsInvalidAnnualIncome() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setAnnualIncome("lots of money");
            List<DataQualityIssue> issues = validator.validateBorrower(borrower);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.HIGH
                            && i.getColumn().equals("BORR_ANN_INCM")));
        }

        @Test
        void detectsNegativeAnnualIncome() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setAnnualIncome("-50,000");
            List<DataQualityIssue> issues = validator.validateBorrower(borrower);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.HIGH
                            && i.getColumn().equals("BORR_ANN_INCM")));
        }

        @Test
        void detectsInvalidDateOfBirth() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setDateOfBirth("2025-01-01");
            List<DataQualityIssue> issues = validator.validateBorrower(borrower);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.HIGH
                            && i.getColumn().equals("BORR_DOB_DT")));
        }

        @Test
        void detectsUnknownEmploymentStatus() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setEmploymentStatus("FREELANCE");
            List<DataQualityIssue> issues = validator.validateBorrower(borrower);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.MEDIUM
                            && i.getColumn().equals("BORR_EMP_STAT")));
        }
    }

    // =========================================================================
    // Loan account validation tests
    // =========================================================================

    @Nested
    class LoanAccountValidationTests {

        private final Set<String> validBorrowerIds = Set.of("B-10001", "B-10002");
        private final Set<String> validProductCodes = Set.of("FXD30", "FXD15", "ARM51");

        @Test
        void validLoanAccountHasNoIssues() {
            LegacyLoanAccount account = createValidLoanAccount();
            List<DataQualityIssue> issues = validator.validateLoanAccount(
                    account, validBorrowerIds, validProductCodes);
            assertTrue(issues.isEmpty(), "Valid loan account should have no issues, got: " + issues);
        }

        @Test
        void detectsOrphanedBorrowerId() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setBorrowerId("B-99999");
            List<DataQualityIssue> issues = validator.validateLoanAccount(
                    account, validBorrowerIds, validProductCodes);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.CRITICAL
                            && i.getColumn().equals("BORR_ID")
                            && i.getMessage().contains("Orphaned")));
        }

        @Test
        void detectsOrphanedProductCode() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setProductCode("INVALID");
            List<DataQualityIssue> issues = validator.validateLoanAccount(
                    account, validBorrowerIds, validProductCodes);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.CRITICAL
                            && i.getColumn().equals("PROD_CD")
                            && i.getMessage().contains("Orphaned")));
        }

        @Test
        void detectsInvalidStatusCode() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setStatusCode("XYZ");
            List<DataQualityIssue> issues = validator.validateLoanAccount(
                    account, validBorrowerIds, validProductCodes);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.HIGH
                            && i.getColumn().equals("LN_STAT_CD")));
        }

        @Test
        void detectsDelinquencyWithActiveStatus() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setDelinquencyDays("15");
            account.setStatusCode("ACT");
            List<DataQualityIssue> issues = validator.validateLoanAccount(
                    account, validBorrowerIds, validProductCodes);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.HIGH
                            && i.getColumn().equals("LN_DLQ_DAYS")
                            && i.getMessage().contains("delinquency")));
        }

        @Test
        void detectsUnparseableAmount() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setOriginalAmount("$lots");
            List<DataQualityIssue> issues = validator.validateLoanAccount(
                    account, validBorrowerIds, validProductCodes);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.HIGH
                            && i.getColumn().equals("LN_ORIG_AMT")));
        }

        @Test
        void detectsInvalidInterestRate() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setInterestRate("abc");
            List<DataQualityIssue> issues = validator.validateLoanAccount(
                    account, validBorrowerIds, validProductCodes);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.HIGH
                            && i.getColumn().equals("LN_INT_RT")));
        }

        @Test
        void detectsUnknownPropertyType() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setPropertyType("ZZZ");
            List<DataQualityIssue> issues = validator.validateLoanAccount(
                    account, validBorrowerIds, validProductCodes);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.MEDIUM
                            && i.getColumn().equals("PROP_TYP_CD")));
        }

        @Test
        void detectsInvalidOriginationDate() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setOriginationDate("not-a-date");
            List<DataQualityIssue> issues = validator.validateLoanAccount(
                    account, validBorrowerIds, validProductCodes);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.HIGH
                            && i.getColumn().equals("LN_ORIG_DT")));
        }
    }

    // =========================================================================
    // Payment validation tests
    // =========================================================================

    @Nested
    class PaymentValidationTests {

        private final Set<String> validLoanAccountNumbers = Set.of("LN-2019-00142", "LN-2020-00398");

        @Test
        void validPaymentHasNoIssues() {
            LegacyPayment payment = createValidPayment();
            List<DataQualityIssue> issues = validator.validatePayment(payment, validLoanAccountNumbers);
            assertTrue(issues.isEmpty(), "Valid payment should have no issues, got: " + issues);
        }

        @Test
        void detectsOrphanedLoanAccount() {
            LegacyPayment payment = createValidPayment();
            payment.setLoanAccountNumber("LN-9999-00000");
            List<DataQualityIssue> issues = validator.validatePayment(payment, validLoanAccountNumbers);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.CRITICAL
                            && i.getColumn().equals("LN_ACCT_NBR")
                            && i.getMessage().contains("Orphaned")));
        }

        @Test
        void detectsPaymentComponentSumMismatch() {
            LegacyPayment payment = createValidPayment();
            payment.setTotalAmount("1,487.02");
            payment.setPrincipalAmount("456.78");
            payment.setInterestAmount("1,074.69");
            payment.setEscrowAmount("355.55");
            payment.setLateFee("0.00");
            // components sum to 1,887.02, not 1,487.02
            List<DataQualityIssue> issues = validator.validatePayment(payment, validLoanAccountNumbers);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.CRITICAL
                            && i.getColumn().equals("PMT_AMT")
                            && i.getMessage().contains("do not sum")));
        }

        @Test
        void detectsLateFeeExcludedFromTotal() {
            LegacyPayment payment = createValidPayment();
            payment.setTotalAmount("1,077.05");
            payment.setPrincipalAmount("295.82");
            payment.setInterestAmount("781.23");
            payment.setEscrowAmount("0.00");
            payment.setLateFee("47.50");
            // components sum to 1,124.55, not 1,077.05
            List<DataQualityIssue> issues = validator.validatePayment(payment, validLoanAccountNumbers);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.CRITICAL
                            && i.getColumn().equals("PMT_AMT")
                            && i.getMessage().contains("do not sum")));
        }

        @Test
        void acceptsMatchingPaymentComponents() {
            LegacyPayment payment = createValidPayment();
            payment.setTotalAmount("2,924.18");
            payment.setPrincipalAmount("1,842.56");
            payment.setInterestAmount("815.50");
            payment.setEscrowAmount("266.12");
            payment.setLateFee("0.00");
            List<DataQualityIssue> issues = validator.validatePayment(payment, validLoanAccountNumbers);
            assertTrue(issues.stream().noneMatch(i -> i.getColumn().equals("PMT_AMT")),
                    "Matching payment should not have sum mismatch issue");
        }

        @Test
        void detectsInvalidPaymentType() {
            LegacyPayment payment = createValidPayment();
            payment.setTypeCode("XYZ");
            List<DataQualityIssue> issues = validator.validatePayment(payment, validLoanAccountNumbers);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.HIGH
                            && i.getColumn().equals("PMT_TYP_CD")));
        }

        @Test
        void detectsInvalidPaymentStatus() {
            LegacyPayment payment = createValidPayment();
            payment.setStatusCode("ZZZ");
            List<DataQualityIssue> issues = validator.validatePayment(payment, validLoanAccountNumbers);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.HIGH
                            && i.getColumn().equals("PMT_STAT_CD")));
        }

        @Test
        void detectsInvalidPaymentDate() {
            LegacyPayment payment = createValidPayment();
            payment.setPaymentDate("2025-12-01");
            List<DataQualityIssue> issues = validator.validatePayment(payment, validLoanAccountNumbers);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.HIGH
                            && i.getColumn().equals("PMT_DT")));
        }

        @Test
        void detectsUnparseablePaymentAmount() {
            LegacyPayment payment = createValidPayment();
            payment.setTotalAmount("NOT_A_NUMBER");
            List<DataQualityIssue> issues = validator.validatePayment(payment, validLoanAccountNumbers);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.HIGH
                            && i.getColumn().equals("PMT_AMT")));
        }
    }

    // =========================================================================
    // Recompute payment total tests
    // =========================================================================

    @Nested
    class RecomputePaymentTotalTests {

        @Test
        void recomputesTotalFromComponents() {
            LegacyPayment payment = createValidPayment();
            payment.setPrincipalAmount("456.78");
            payment.setInterestAmount("1,074.69");
            payment.setEscrowAmount("355.55");
            payment.setLateFee("0.00");
            BigDecimal recomputed = validator.recomputePaymentTotal(payment);
            assertEquals(new BigDecimal("1887.02"), recomputed);
        }

        @Test
        void handlesNullComponents() {
            LegacyPayment payment = createValidPayment();
            payment.setPrincipalAmount(null);
            payment.setInterestAmount("100.00");
            payment.setEscrowAmount(null);
            payment.setLateFee(null);
            BigDecimal recomputed = validator.recomputePaymentTotal(payment);
            assertEquals(new BigDecimal("100.00"), recomputed);
        }

        @Test
        void handlesAllNullComponents() {
            LegacyPayment payment = createValidPayment();
            payment.setPrincipalAmount(null);
            payment.setInterestAmount(null);
            payment.setEscrowAmount(null);
            payment.setLateFee(null);
            BigDecimal recomputed = validator.recomputePaymentTotal(payment);
            assertEquals(new BigDecimal("0.00"), recomputed);
        }
    }

    // =========================================================================
    // Test data builders
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
        p.setPaymentSequenceNumber("PMT-2025120002");
        p.setLoanAccountNumber("LN-2019-00142");
        p.setPaymentDate("12/01/2025");
        p.setTotalAmount("2,924.18");
        p.setPrincipalAmount("1,842.56");
        p.setInterestAmount("815.50");
        p.setEscrowAmount("266.12");
        p.setLateFee("0.00");
        p.setTypeCode("REG");
        p.setStatusCode("PST");
        p.setReceivedDate("11/30/2025");
        p.setProcessedDate("12/01/2025");
        p.setCreatedDate("12/01/2025");
        p.setUpdatedDate("12/01/2025");
        return p;
    }
}
