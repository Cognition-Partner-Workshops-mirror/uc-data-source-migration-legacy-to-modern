package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // SAFE PARSING TESTS
    // =========================================================================

    @Nested
    @DisplayName("Amount Parsing")
    class AmountParsing {

        @Test
        @DisplayName("parses standard comma-formatted amount")
        void parsesStandardAmount() {
            List<DataQualityIssue> issues = new ArrayList<>();
            BigDecimal result = validator.safeParseAmount(
                    "285,000", "TEST", "COL", "REC-1", issues);
            assertEquals(new BigDecimal("285000"), result);
            assertTrue(issues.isEmpty());
        }

        @Test
        @DisplayName("parses amount with decimals")
        void parsesAmountWithDecimals() {
            List<DataQualityIssue> issues = new ArrayList<>();
            BigDecimal result = validator.safeParseAmount(
                    "271,432.56", "TEST", "COL", "REC-1", issues);
            assertEquals(new BigDecimal("271432.56"), result);
            assertTrue(issues.isEmpty());
        }

        @Test
        @DisplayName("returns zero for null input")
        void returnsZeroForNull() {
            List<DataQualityIssue> issues = new ArrayList<>();
            BigDecimal result = validator.safeParseAmount(
                    null, "TEST", "COL", "REC-1", issues);
            assertEquals(BigDecimal.ZERO, result);
            assertTrue(issues.isEmpty());
        }

        @Test
        @DisplayName("returns zero for blank input")
        void returnsZeroForBlank() {
            List<DataQualityIssue> issues = new ArrayList<>();
            BigDecimal result = validator.safeParseAmount(
                    "   ", "TEST", "COL", "REC-1", issues);
            assertEquals(BigDecimal.ZERO, result);
            assertTrue(issues.isEmpty());
        }

        @Test
        @DisplayName("handles dollar sign in amount gracefully")
        void handlesDollarSign() {
            List<DataQualityIssue> issues = new ArrayList<>();
            BigDecimal result = validator.safeParseAmount(
                    "$285,000", "TEST", "COL", "REC-1", issues);
            assertEquals(new BigDecimal("285000"), result);
            assertTrue(issues.isEmpty());
        }

        @Test
        @DisplayName("reports issue for completely unparseable amount")
        void reportsUnparseableAmount() {
            List<DataQualityIssue> issues = new ArrayList<>();
            BigDecimal result = validator.safeParseAmount(
                    "N/A", "CDW_LN_ACCT", "LN_CURR_BAL", "LN-001", issues);
            assertEquals(BigDecimal.ZERO, result);
            assertEquals(1, issues.size());
            assertEquals(DataQualityIssue.Severity.HIGH, issues.get(0).getSeverity());
            assertTrue(issues.get(0).getDescription().contains("Failed to parse amount"));
        }

        @Test
        @DisplayName("handles percentage sign in value")
        void handlesPercentSign() {
            List<DataQualityIssue> issues = new ArrayList<>();
            BigDecimal result = validator.safeParseDecimal(
                    "82.5%", "TEST", "COL", "REC-1", issues);
            assertEquals(new BigDecimal("82.5"), result);
            assertTrue(issues.isEmpty());
        }
    }

    @Nested
    @DisplayName("Integer Parsing")
    class IntegerParsing {

        @Test
        @DisplayName("parses valid integer string")
        void parsesValidInteger() {
            List<DataQualityIssue> issues = new ArrayList<>();
            Integer result = validator.safeParseInteger(
                    "745", "TEST", "COL", "REC-1", issues);
            assertEquals(745, result);
            assertTrue(issues.isEmpty());
        }

        @Test
        @DisplayName("returns null for null input")
        void returnsNullForNull() {
            List<DataQualityIssue> issues = new ArrayList<>();
            Integer result = validator.safeParseInteger(
                    null, "TEST", "COL", "REC-1", issues);
            assertNull(result);
            assertTrue(issues.isEmpty());
        }

        @Test
        @DisplayName("reports issue for non-integer string")
        void reportsNonInteger() {
            List<DataQualityIssue> issues = new ArrayList<>();
            Integer result = validator.safeParseInteger(
                    "7.5", "CDW_BORR_MSTR", "BORR_CRDT_SCR", "B-001", issues);
            assertNull(result);
            assertEquals(1, issues.size());
            assertEquals(DataQualityIssue.Severity.HIGH, issues.get(0).getSeverity());
        }

        @Test
        @DisplayName("reports issue for text value")
        void reportsTextValue() {
            List<DataQualityIssue> issues = new ArrayList<>();
            Integer result = validator.safeParseInteger(
                    "EXCELLENT", "CDW_BORR_MSTR", "BORR_CRDT_SCR", "B-001", issues);
            assertNull(result);
            assertEquals(1, issues.size());
        }
    }

    @Nested
    @DisplayName("Date Parsing")
    class DateParsing {

        @Test
        @DisplayName("parses valid MM/DD/YYYY date")
        void parsesValidDate() {
            List<DataQualityIssue> issues = new ArrayList<>();
            LocalDate result = validator.safeParseDate(
                    "03/15/1978", "TEST", "COL", "REC-1", issues);
            assertEquals(LocalDate.of(1978, 3, 15), result);
            assertTrue(issues.isEmpty());
        }

        @Test
        @DisplayName("returns null for null input")
        void returnsNullForNull() {
            List<DataQualityIssue> issues = new ArrayList<>();
            LocalDate result = validator.safeParseDate(
                    null, "TEST", "COL", "REC-1", issues);
            assertNull(result);
            assertTrue(issues.isEmpty());
        }

        @Test
        @DisplayName("reports issue for ISO format date")
        void reportsIsoFormat() {
            List<DataQualityIssue> issues = new ArrayList<>();
            LocalDate result = validator.safeParseDate(
                    "2025-12-01", "CDW_PMT_HIST", "PMT_DT", "PMT-001", issues);
            assertNull(result);
            assertEquals(1, issues.size());
            assertTrue(issues.get(0).getDescription().contains("Failed to parse date"));
        }

        @Test
        @DisplayName("reports issue for invalid date with month 13")
        void reportsInvalidDate() {
            List<DataQualityIssue> issues = new ArrayList<>();
            LocalDate result = validator.safeParseDate(
                    "13/15/2021", "TEST", "COL", "REC-1", issues);
            assertNull(result);
            assertEquals(1, issues.size());
        }

        @Test
        @DisplayName("reports issue for partial date")
        void reportsPartialDate() {
            List<DataQualityIssue> issues = new ArrayList<>();
            LocalDate result = validator.safeParseDate(
                    "12/2025", "TEST", "COL", "REC-1", issues);
            assertNull(result);
            assertEquals(1, issues.size());
        }
    }

    // =========================================================================
    // ENTITY VALIDATION TESTS
    // =========================================================================

    @Nested
    @DisplayName("Borrower Validation")
    class BorrowerValidation {

        @Test
        @DisplayName("valid borrower produces no issues")
        void validBorrowerNoIssues() {
            LegacyBorrower borrower = createValidBorrower();
            List<DataQualityIssue> issues = validator.validateBorrower(borrower);
            assertTrue(issues.isEmpty());
        }

        @Test
        @DisplayName("detects null first name")
        void detectsNullFirstName() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setFirstName(null);
            List<DataQualityIssue> issues = validator.validateBorrower(borrower);
            assertFalse(issues.isEmpty());
            assertTrue(issues.stream().anyMatch(i ->
                    i.getColumn().equals("BORR_FST_NM") && i.getSeverity() == DataQualityIssue.Severity.HIGH));
        }

        @Test
        @DisplayName("detects null last name")
        void detectsNullLastName() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setLastName(null);
            List<DataQualityIssue> issues = validator.validateBorrower(borrower);
            assertFalse(issues.isEmpty());
            assertTrue(issues.stream().anyMatch(i ->
                    i.getColumn().equals("BORR_LST_NM")));
        }

        @Test
        @DisplayName("detects non-numeric credit score")
        void detectsNonNumericCreditScore() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("EXCELLENT");
            List<DataQualityIssue> issues = validator.validateBorrower(borrower);
            assertFalse(issues.isEmpty());
            assertTrue(issues.stream().anyMatch(i ->
                    i.getColumn().equals("BORR_CRDT_SCR")));
        }

        @Test
        @DisplayName("detects credit score outside valid range")
        void detectsCreditScoreOutOfRange() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("999");
            List<DataQualityIssue> issues = validator.validateBorrower(borrower);
            assertFalse(issues.isEmpty());
            assertTrue(issues.stream().anyMatch(i ->
                    i.getColumn().equals("BORR_CRDT_SCR")
                            && i.getSeverity() == DataQualityIssue.Severity.MEDIUM));
        }

        @Test
        @DisplayName("detects invalid annual income format")
        void detectsInvalidIncome() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setAnnualIncome("$92,500.00 USD");
            List<DataQualityIssue> issues = validator.validateBorrower(borrower);
            assertFalse(issues.isEmpty());
            assertTrue(issues.stream().anyMatch(i ->
                    i.getColumn().equals("BORR_ANN_INCM")));
        }

        @Test
        @DisplayName("detects invalid date of birth format")
        void detectsInvalidDob() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setDateOfBirth("1978-03-15");
            List<DataQualityIssue> issues = validator.validateBorrower(borrower);
            assertFalse(issues.isEmpty());
            assertTrue(issues.stream().anyMatch(i ->
                    i.getColumn().equals("BORR_DOB_DT")));
        }

        @Test
        @DisplayName("detects invalid status code")
        void detectsInvalidStatus() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setStatusCode("XYZ");
            List<DataQualityIssue> issues = validator.validateBorrower(borrower);
            assertFalse(issues.isEmpty());
            assertTrue(issues.stream().anyMatch(i ->
                    i.getColumn().equals("BORR_STAT_CD")));
        }
    }

    @Nested
    @DisplayName("Loan Account Validation")
    class LoanAccountValidation {

        @Test
        @DisplayName("valid loan account produces no critical issues")
        void validLoanNoIssues() {
            LegacyLoanAccount account = createValidLoanAccount();
            List<DataQualityIssue> issues = validator.validateLoanAccount(account);
            assertTrue(issues.stream().noneMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.CRITICAL));
        }

        @Test
        @DisplayName("detects null borrower ID")
        void detectsNullBorrowerId() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setBorrowerId(null);
            List<DataQualityIssue> issues = validator.validateLoanAccount(account);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getColumn().equals("BORR_ID")
                            && i.getSeverity() == DataQualityIssue.Severity.CRITICAL));
        }

        @Test
        @DisplayName("detects invalid amount format")
        void detectsInvalidAmountFormat() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setOriginalAmount("TWO HUNDRED THOUSAND");
            List<DataQualityIssue> issues = validator.validateLoanAccount(account);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getColumn().equals("LN_ORIG_AMT")));
        }

        @Test
        @DisplayName("detects invalid interest rate")
        void detectsInvalidInterestRate() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setInterestRate("VARIABLE");
            List<DataQualityIssue> issues = validator.validateLoanAccount(account);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getColumn().equals("LN_INT_RT")));
        }

        @Test
        @DisplayName("detects invalid loan status code")
        void detectsInvalidStatus() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setStatusCode("BAD");
            List<DataQualityIssue> issues = validator.validateLoanAccount(account);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getColumn().equals("LN_STAT_CD")));
        }

        @Test
        @DisplayName("detects invalid origination date format")
        void detectsInvalidDate() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setOriginationDate("2019-02-15");
            List<DataQualityIssue> issues = validator.validateLoanAccount(account);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getColumn().equals("LN_ORIG_DT")));
        }

        @Test
        @DisplayName("detects delinquency/status inconsistency")
        void detectsDelinquencyInconsistency() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setDelinquencyDays("15");
            account.setStatusCode("ACT");
            List<DataQualityIssue> issues = validator.validateLoanAccount(account);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getColumn().equals("LN_DLQ_DAYS")
                            && i.getDescription().contains("Delinquency days=15 but status is ACT")));
        }

        @Test
        @DisplayName("no delinquency warning when days is zero")
        void noWarningForZeroDays() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setDelinquencyDays("0");
            account.setStatusCode("ACT");
            List<DataQualityIssue> issues = validator.validateLoanAccount(account);
            assertTrue(issues.stream().noneMatch(i ->
                    i.getColumn().equals("LN_DLQ_DAYS")));
        }
    }

    @Nested
    @DisplayName("Payment Validation")
    class PaymentValidation {

        @Test
        @DisplayName("valid payment produces no issues")
        void validPaymentNoIssues() {
            LegacyPayment payment = createValidPayment();
            List<DataQualityIssue> issues = validator.validatePayment(payment);
            assertTrue(issues.isEmpty());
        }

        @Test
        @DisplayName("detects null loan account number")
        void detectsNullLoanAccount() {
            LegacyPayment payment = createValidPayment();
            payment.setLoanAccountNumber(null);
            List<DataQualityIssue> issues = validator.validatePayment(payment);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getColumn().equals("LN_ACCT_NBR")
                            && i.getSeverity() == DataQualityIssue.Severity.CRITICAL));
        }

        @Test
        @DisplayName("detects payment component sum mismatch")
        void detectsPaymentSumMismatch() {
            LegacyPayment payment = createValidPayment();
            // total=1,487.02, but components sum to 1,887.02
            payment.setTotalAmount("1,487.02");
            payment.setPrincipalAmount("456.78");
            payment.setInterestAmount("1,074.69");
            payment.setEscrowAmount("355.55");
            payment.setLateFee("0.00");
            List<DataQualityIssue> issues = validator.validatePayment(payment);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getSeverity() == DataQualityIssue.Severity.CRITICAL
                            && i.getDescription().contains("does not match total")));
        }

        @Test
        @DisplayName("no mismatch for correctly summing payments")
        void noMismatchForCorrectSum() {
            LegacyPayment payment = createValidPayment();
            // total = 2,924.18, components: 1,842.56 + 815.50 + 266.12 + 0.00 = 2,924.18
            payment.setTotalAmount("2,924.18");
            payment.setPrincipalAmount("1,842.56");
            payment.setInterestAmount("815.50");
            payment.setEscrowAmount("266.12");
            payment.setLateFee("0.00");
            List<DataQualityIssue> issues = validator.validatePayment(payment);
            assertTrue(issues.stream().noneMatch(i ->
                    i.getDescription().contains("does not match total")));
        }

        @Test
        @DisplayName("detects invalid payment status code")
        void detectsInvalidPaymentStatus() {
            LegacyPayment payment = createValidPayment();
            payment.setStatusCode("XXX");
            List<DataQualityIssue> issues = validator.validatePayment(payment);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getColumn().equals("PMT_STAT_CD")));
        }

        @Test
        @DisplayName("detects invalid payment type code")
        void detectsInvalidPaymentType() {
            LegacyPayment payment = createValidPayment();
            payment.setTypeCode("ABC");
            List<DataQualityIssue> issues = validator.validatePayment(payment);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getColumn().equals("PMT_TYP_CD")));
        }

        @Test
        @DisplayName("detects invalid payment date format")
        void detectsInvalidPaymentDate() {
            LegacyPayment payment = createValidPayment();
            payment.setPaymentDate("2025-12-15");
            List<DataQualityIssue> issues = validator.validatePayment(payment);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getColumn().equals("PMT_DT")));
        }

        @Test
        @DisplayName("detects unparseable total amount")
        void detectsUnparseableTotalAmount() {
            LegacyPayment payment = createValidPayment();
            payment.setTotalAmount("PENDING");
            List<DataQualityIssue> issues = validator.validatePayment(payment);
            assertTrue(issues.stream().anyMatch(i ->
                    i.getColumn().equals("PMT_AMT")));
        }
    }

    // =========================================================================
    // HELPER METHODS
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
        b.setAddressLine2("Apt 3B");
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
        p.setLoanAccountNumber("LN-2020-00398");
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
