package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.validation.ValidationResult.Severity;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // Safe Parsing Tests
    // =========================================================================

    @Nested
    @DisplayName("Amount Parsing")
    class AmountParsing {

        @Test
        void parsesValidAmountWithCommas() {
            assertEquals(new BigDecimal("285000"), validator.safeParseAmount("285,000"));
        }

        @Test
        void parsesValidAmountWithDecimal() {
            assertEquals(new BigDecimal("1487.02"), validator.safeParseAmount("1,487.02"));
        }

        @Test
        void parsesSimpleInteger() {
            assertEquals(new BigDecimal("50000"), validator.safeParseAmount("50,000"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.safeParseAmount(null));
        }

        @Test
        void returnsZeroForBlank() {
            assertEquals(BigDecimal.ZERO, validator.safeParseAmount("   "));
        }

        @Test
        void handlesDollarSign() {
            assertEquals(new BigDecimal("285000"), validator.safeParseAmount("$285,000"));
        }

        @Test
        void returnsNullForTextValue() {
            assertNull(validator.safeParseAmount("N/A"));
        }

        @Test
        void returnsNullForAlphabeticText() {
            assertNull(validator.safeParseAmount("PENDING"));
        }
    }

    @Nested
    @DisplayName("Decimal Parsing")
    class DecimalParsing {

        @Test
        void parsesValidDecimal() {
            assertEquals(new BigDecimal("4.750"), validator.safeParseDecimal("4.750"));
        }

        @Test
        void parsesIntegerAsDecimal() {
            assertEquals(new BigDecimal("5"), validator.safeParseDecimal("5"));
        }

        @Test
        void stripsPercentSign() {
            assertEquals(new BigDecimal("82.5"), validator.safeParseDecimal("82.5%"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.safeParseDecimal(null));
        }

        @Test
        void returnsNullForText() {
            assertNull(validator.safeParseDecimal("TBD"));
        }
    }

    @Nested
    @DisplayName("Integer Parsing")
    class IntegerParsing {

        @Test
        void parsesValidInteger() {
            assertEquals(745, validator.safeParseInteger("745"));
        }

        @Test
        void parsesZero() {
            assertEquals(0, validator.safeParseInteger("0"));
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
        void returnsNullForDecimal() {
            assertNull(validator.safeParseInteger("745.5"));
        }

        @Test
        void returnsNullForNumericWithPlus() {
            assertNull(validator.safeParseInteger("780+"));
        }

        @Test
        void trimsWhitespace() {
            assertEquals(360, validator.safeParseInteger("  360  "));
        }
    }

    @Nested
    @DisplayName("Date Parsing")
    class DateParsing {

        @Test
        void parsesValidDate() {
            assertEquals(LocalDate.of(1978, 3, 15), validator.safeParseLegacyDate("03/15/1978"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.safeParseLegacyDate(null));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.safeParseLegacyDate(""));
        }

        @Test
        void returnsNullForIsoFormat() {
            assertNull(validator.safeParseLegacyDate("1978-03-15"));
        }

        @Test
        void returnsNullForInvalidDate() {
            assertNull(validator.safeParseLegacyDate("13/32/2020"));
        }

        @Test
        void returnsNullForShortYear() {
            assertNull(validator.safeParseLegacyDate("03/15/78"));
        }
    }

    // =========================================================================
    // Borrower Validation Tests
    // =========================================================================

    @Nested
    @DisplayName("Borrower Validation")
    class BorrowerValidation {

        @Test
        void validBorrowerProducesNoWarnings() {
            LegacyBorrower borrower = createValidBorrower();
            ValidationResult result = validator.validateBorrower(borrower);
            assertFalse(result.hasWarnings());
            assertTrue(result.isValid());
        }

        @Test
        void detectsNullFirstName() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setFirstName(null);
            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasWarnings());
            assertEquals(1, result.getWarningsBySeverity(Severity.HIGH).size());
            assertTrue(result.getWarnings().get(0).message().contains("null or blank"));
        }

        @Test
        void detectsNullLastName() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setLastName(null);
            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasWarnings());
            assertEquals("BORR_LST_NM", result.getWarnings().get(0).field());
        }

        @Test
        void detectsInvalidCreditScore() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("N/A");
            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("BORR_CRDT_SCR")));
        }

        @Test
        void detectsOutOfRangeCreditScore() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("200");
            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("BORR_CRDT_SCR")
                            && w.message().contains("outside valid range")));
        }

        @Test
        void detectsInvalidAnnualIncome() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setAnnualIncome("$92,500");
            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("BORR_ANN_INCM")));
        }

        @Test
        void detectsInvalidDateFormat() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setDateOfBirth("1978-03-15");
            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("BORR_DOB_DT")));
        }

        @Test
        void detectsInvalidStatusCode() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setStatusCode("XYZ");
            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("BORR_STAT_CD")));
        }
    }

    // =========================================================================
    // Loan Account Validation Tests
    // =========================================================================

    @Nested
    @DisplayName("Loan Account Validation")
    class LoanAccountValidation {

        @Test
        void validLoanAccountProducesNoHighSeverityWarnings() {
            LegacyLoanAccount account = createValidLoanAccount();
            LegacyBorrower borrower = createValidBorrower();
            // Use a phone number that doesn't match SSN last 4
            borrower.setPhoneNumber("217-555-9999");
            ValidationResult result = validator.validateLoanAccount(account, borrower);
            assertTrue(result.getWarningsBySeverity(Severity.CRITICAL).isEmpty());
        }

        @Test
        void detectsSsnMatchingPhoneSuffix() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setBorrowerSsnLast4("0142");
            LegacyBorrower borrower = createValidBorrower();
            borrower.setPhoneNumber("217-555-0142");
            ValidationResult result = validator.validateLoanAccount(account, borrower);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.severity() == Severity.CRITICAL
                            && w.field().equals("BORR_SSN_LST4")
                            && w.message().contains("phone number suffix")));
        }

        @Test
        void detectsNonNumericSsnLast4() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setBorrowerSsnLast4("ABCD");
            ValidationResult result = validator.validateLoanAccount(account, null);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("BORR_SSN_LST4")
                            && w.message().contains("not exactly 4 digits")));
        }

        @Test
        void detectsDelinquencyWithActiveStatus() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setDelinquencyDays("15");
            account.setStatusCode("ACT");
            ValidationResult result = validator.validateLoanAccount(account, null);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("LN_STAT_CD")
                            && w.message().contains("delinquent")));
        }

        @Test
        void noDelinquencyWarningWhenZeroDays() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setDelinquencyDays("0");
            account.setStatusCode("ACT");
            ValidationResult result = validator.validateLoanAccount(account, null);
            assertFalse(result.getWarnings().stream()
                    .anyMatch(w -> w.message().contains("delinquent")));
        }

        @Test
        void detectsInvalidAmountFormat() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setOriginalAmount("$285,000");
            ValidationResult result = validator.validateLoanAccount(account, null);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("LN_ORIG_AMT")));
        }

        @Test
        void detectsInvalidInterestRate() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setInterestRate("variable");
            ValidationResult result = validator.validateLoanAccount(account, null);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("LN_INT_RT")));
        }

        @Test
        void detectsDenormalizedNameDrift() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setBorrowerFirstName("Jim");
            LegacyBorrower borrower = createValidBorrower();
            borrower.setFirstName("James");
            borrower.setPhoneNumber("217-555-9999");
            ValidationResult result = validator.validateLoanAccount(account, borrower);
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("BORR_FST_NM")
                            && w.message().contains("differs from master")));
        }

        @Test
        void detectsNullBorrowerId() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setBorrowerId(null);
            ValidationResult result = validator.validateLoanAccount(account, null);
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("BORR_ID")));
        }

        @Test
        void detectsInvalidLoanStatusCode() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setStatusCode("XXX");
            ValidationResult result = validator.validateLoanAccount(account, null);
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("LN_STAT_CD")
                            && w.message().contains("Invalid loan status")));
        }
    }

    // =========================================================================
    // Payment Validation Tests
    // =========================================================================

    @Nested
    @DisplayName("Payment Validation")
    class PaymentValidation {

        @Test
        void validPaymentProducesNoWarnings() {
            LegacyPayment payment = createValidPayment();
            ValidationResult result = validator.validatePayment(payment);
            assertFalse(result.hasWarnings());
        }

        @Test
        void detectsComponentSumMismatch() {
            LegacyPayment payment = createValidPayment();
            // Set total lower than component sum
            payment.setTotalAmount("1,487.02");
            payment.setPrincipalAmount("456.78");
            payment.setInterestAmount("1,074.69");
            payment.setEscrowAmount("355.55");
            payment.setLateFee("0.00");
            // Sum: 456.78 + 1074.69 + 355.55 = 1887.02, total = 1487.02
            ValidationResult result = validator.validatePayment(payment);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.severity() == Severity.CRITICAL
                            && w.field().equals("PMT_AMT")
                            && w.message().contains("components sum")));
        }

        @Test
        void noWarningWhenComponentsSumCorrectly() {
            LegacyPayment payment = createValidPayment();
            payment.setTotalAmount("2,924.18");
            payment.setPrincipalAmount("1,842.56");
            payment.setInterestAmount("815.50");
            payment.setEscrowAmount("266.12");
            payment.setLateFee("0.00");
            // Sum: 1842.56 + 815.50 + 266.12 = 2924.18 = total
            ValidationResult result = validator.validatePayment(payment);
            assertFalse(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("PMT_AMT")));
        }

        @Test
        void detectsNullLoanAccountReference() {
            LegacyPayment payment = createValidPayment();
            payment.setLoanAccountNumber(null);
            ValidationResult result = validator.validatePayment(payment);
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("LN_ACCT_NBR")));
        }

        @Test
        void detectsInvalidPaymentTypeCode() {
            LegacyPayment payment = createValidPayment();
            payment.setTypeCode("BAD");
            ValidationResult result = validator.validatePayment(payment);
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("PMT_TYP_CD")));
        }

        @Test
        void detectsInvalidPaymentStatusCode() {
            LegacyPayment payment = createValidPayment();
            payment.setStatusCode("UNK");
            ValidationResult result = validator.validatePayment(payment);
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("PMT_STAT_CD")));
        }

        @Test
        void detectsInvalidAmountInPayment() {
            LegacyPayment payment = createValidPayment();
            payment.setTotalAmount("PENDING");
            ValidationResult result = validator.validatePayment(payment);
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("PMT_AMT")));
        }

        @Test
        void detectsInvalidDateInPayment() {
            LegacyPayment payment = createValidPayment();
            payment.setPaymentDate("2025-12-15");
            ValidationResult result = validator.validatePayment(payment);
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("PMT_DT")));
        }
    }

    // =========================================================================
    // Helper Methods
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
        a.setBorrowerSsnLast4("1234");
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
        p.setPaymentSequenceNumber("PMT-2025120001");
        p.setLoanAccountNumber("LN-2019-00142");
        p.setPaymentDate("12/15/2025");
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
