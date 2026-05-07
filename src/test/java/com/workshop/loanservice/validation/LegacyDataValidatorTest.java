package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.validation.ValidationResult.Severity;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.Set;

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
    class SafeParseAmountTests {

        @Test
        void parsesValidAmountWithCommas() {
            assertEquals(new BigDecimal("285000"), validator.safeParseAmount("285,000"));
        }

        @Test
        void parsesValidAmountWithDecimal() {
            assertEquals(new BigDecimal("1487.02"), validator.safeParseAmount("1,487.02"));
        }

        @Test
        void parsesAmountWithDollarSign() {
            assertEquals(new BigDecimal("285000"), validator.safeParseAmount("$285,000"));
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
        void returnsZeroForNonNumeric() {
            assertEquals(BigDecimal.ZERO, validator.safeParseAmount("N/A"));
        }

        @Test
        void returnsZeroForTextWithNumbers() {
            assertEquals(BigDecimal.ZERO, validator.safeParseAmount("about 285,000"));
        }
    }

    @Nested
    class SafeParseDecimalTests {

        @Test
        void parsesValidDecimal() {
            assertEquals(new BigDecimal("4.750"), validator.safeParseDecimal("4.750"));
        }

        @Test
        void parsesDecimalWithWhitespace() {
            assertEquals(new BigDecimal("4.750"), validator.safeParseDecimal("  4.750  "));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.safeParseDecimal(null));
        }

        @Test
        void returnsZeroForNonNumeric() {
            assertEquals(BigDecimal.ZERO, validator.safeParseDecimal("TBD"));
        }
    }

    @Nested
    class SafeParseIntegerTests {

        @Test
        void parsesValidInteger() {
            assertEquals(745, validator.safeParseInteger("745"));
        }

        @Test
        void parsesIntegerWithWhitespace() {
            assertEquals(745, validator.safeParseInteger("  745  "));
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
        void parsesIntegerWithCommas() {
            assertEquals(1000, validator.safeParseInteger("1,000"));
        }
    }

    @Nested
    class SafeParseDateTests {

        @Test
        void parsesValidLegacyDate() {
            assertNotNull(validator.safeParseLegacyDate("03/15/1978"));
        }

        @Test
        void returnsNullForInvalidDate() {
            assertNull(validator.safeParseLegacyDate("13/45/2020"));
        }

        @Test
        void returnsNullForIsoFormat() {
            assertNull(validator.safeParseLegacyDate("2020-01-15"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.safeParseLegacyDate(null));
        }

        @Test
        void returnsNullForGarbage() {
            assertNull(validator.safeParseLegacyDate("TBD"));
        }

        @Test
        void formatsValidDateToIso() {
            assertEquals("1978-03-15", validator.safeFormatDate("03/15/1978"));
        }

        @Test
        void returnsOriginalForInvalidDate() {
            assertEquals("invalid-date", validator.safeFormatDate("invalid-date"));
        }
    }

    // =========================================================================
    // Borrower Validation Tests
    // =========================================================================

    @Nested
    class BorrowerValidationTests {

        @Test
        void validBorrowerProducesNoWarnings() {
            LegacyBorrower borrower = createValidBorrower();
            ValidationResult result = validator.validateBorrower(borrower);
            assertFalse(result.hasWarnings());
        }

        @Test
        void nullFirstNameProducesCriticalWarning() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setFirstName(null);
            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasWarnings(Severity.CRITICAL));
            assertEquals("BORR_FST_NM", result.getWarnings(Severity.CRITICAL).get(0).field());
        }

        @Test
        void nullLastNameProducesCriticalWarning() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setLastName(null);
            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasWarnings(Severity.CRITICAL));
            assertEquals("BORR_LST_NM", result.getWarnings(Severity.CRITICAL).get(0).field());
        }

        @Test
        void invalidDateOfBirthProducesHighWarning() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setDateOfBirth("2020-01-15");
            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasWarnings(Severity.HIGH));
            assertEquals("BORR_DOB_DT", result.getWarnings(Severity.HIGH).get(0).field());
        }

        @Test
        void nonNumericCreditScoreProducesCriticalWarning() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("N/A");
            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasWarnings(Severity.CRITICAL));
            assertEquals("BORR_CRDT_SCR", result.getWarnings(Severity.CRITICAL).get(0).field());
        }

        @Test
        void outOfRangeCreditScoreProducesMediumWarning() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("999");
            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasWarnings(Severity.MEDIUM));
            assertEquals("BORR_CRDT_SCR", result.getWarnings(Severity.MEDIUM).get(0).field());
        }

        @Test
        void lowCreditScoreProducesMediumWarning() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("100");
            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasWarnings(Severity.MEDIUM));
        }

        @Test
        void unknownStatusCodeProducesMediumWarning() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setStatusCode("XYZ");
            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasWarnings(Severity.MEDIUM));
            assertEquals("BORR_STAT_CD", result.getWarnings(Severity.MEDIUM).get(0).field());
        }

        @Test
        void nonNumericAnnualIncomeProducesCriticalWarning() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setAnnualIncome("high");
            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasWarnings(Severity.CRITICAL));
            assertEquals("BORR_ANN_INCM", result.getWarnings(Severity.CRITICAL).get(0).field());
        }
    }

    // =========================================================================
    // Loan Account Validation Tests
    // =========================================================================

    @Nested
    class LoanAccountValidationTests {

        private final Set<String> validBorrowerIds = Set.of("B-10001", "B-10002");
        private final Set<String> validProductCodes = Set.of("FXD30", "FXD15");

        @Test
        void validLoanProducesNoWarnings() {
            LegacyLoanAccount loan = createValidLoanAccount();
            ValidationResult result = validator.validateLoanAccount(loan, validBorrowerIds, validProductCodes);
            assertFalse(result.hasWarnings());
        }

        @Test
        void orphanedBorrowerIdProducesHighWarning() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setBorrowerId("B-99999");
            ValidationResult result = validator.validateLoanAccount(loan, validBorrowerIds, validProductCodes);
            assertTrue(result.hasWarnings(Severity.HIGH));
            assertTrue(result.getWarnings(Severity.HIGH).stream()
                    .anyMatch(w -> w.field().equals("BORR_ID") && w.message().contains("Orphaned")));
        }

        @Test
        void orphanedProductCodeProducesHighWarning() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setProductCode("INVALID");
            ValidationResult result = validator.validateLoanAccount(loan, validBorrowerIds, validProductCodes);
            assertTrue(result.hasWarnings(Severity.HIGH));
            assertTrue(result.getWarnings(Severity.HIGH).stream()
                    .anyMatch(w -> w.field().equals("PROD_CD") && w.message().contains("Orphaned")));
        }

        @Test
        void nonNumericAmountProducesCriticalWarning() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setOriginalAmount("$285,000");
            ValidationResult result = validator.validateLoanAccount(loan, validBorrowerIds, validProductCodes);
            assertFalse(result.hasWarnings(Severity.CRITICAL),
                    "Dollar-sign amounts should be accepted after cleaning");
        }

        @Test
        void completelyInvalidAmountProducesCriticalWarning() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setOriginalAmount("TBD");
            ValidationResult result = validator.validateLoanAccount(loan, validBorrowerIds, validProductCodes);
            assertTrue(result.hasWarnings(Severity.CRITICAL));
            assertTrue(result.getWarnings(Severity.CRITICAL).stream()
                    .anyMatch(w -> w.field().equals("LN_ORIG_AMT")));
        }

        @Test
        void invalidDateProducesHighWarning() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setOriginationDate("2019-02-15");
            ValidationResult result = validator.validateLoanAccount(loan, validBorrowerIds, validProductCodes);
            assertTrue(result.hasWarnings(Severity.HIGH));
            assertTrue(result.getWarnings(Severity.HIGH).stream()
                    .anyMatch(w -> w.field().equals("LN_ORIG_DT")));
        }

        @Test
        void unknownLoanStatusProducesMediumWarning() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setStatusCode("XYZ");
            ValidationResult result = validator.validateLoanAccount(loan, validBorrowerIds, validProductCodes);
            assertTrue(result.hasWarnings(Severity.MEDIUM));
            assertTrue(result.getWarnings(Severity.MEDIUM).stream()
                    .anyMatch(w -> w.field().equals("LN_STAT_CD")));
        }

        @Test
        void unknownPropertyTypeProducesMediumWarning() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setPropertyType("ZZZ");
            ValidationResult result = validator.validateLoanAccount(loan, validBorrowerIds, validProductCodes);
            assertTrue(result.hasWarnings(Severity.MEDIUM));
            assertTrue(result.getWarnings(Severity.MEDIUM).stream()
                    .anyMatch(w -> w.field().equals("PROP_TYP_CD")));
        }
    }

    // =========================================================================
    // Denormalized Data Validation Tests
    // =========================================================================

    @Nested
    class DenormalizedDataValidationTests {

        @Test
        void matchingDataProducesNoWarnings() {
            LegacyLoanAccount loan = createValidLoanAccount();
            LegacyBorrower borrower = createValidBorrower();
            ValidationResult result = validator.validateLoanAccountDenormalizedData(loan, borrower);
            // SSN/phone match will still trigger
            assertTrue(result.getWarnings().stream()
                    .noneMatch(w -> w.field().equals("BORR_FST_NM") || w.field().equals("BORR_LST_NM")));
        }

        @Test
        void mismatchedFirstNameProducesMediumWarning() {
            LegacyLoanAccount loan = createValidLoanAccount();
            LegacyBorrower borrower = createValidBorrower();
            borrower.setFirstName("Jim");
            ValidationResult result = validator.validateLoanAccountDenormalizedData(loan, borrower);
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("BORR_FST_NM") && w.severity() == Severity.MEDIUM));
        }

        @Test
        void mismatchedLastNameProducesMediumWarning() {
            LegacyLoanAccount loan = createValidLoanAccount();
            LegacyBorrower borrower = createValidBorrower();
            borrower.setLastName("Smith");
            ValidationResult result = validator.validateLoanAccountDenormalizedData(loan, borrower);
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("BORR_LST_NM") && w.severity() == Severity.MEDIUM));
        }

        @Test
        void ssnMatchingPhoneLastFourProducesHighWarning() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setBorrowerSsnLast4("0142");
            LegacyBorrower borrower = createValidBorrower();
            borrower.setPhoneNumber("217-555-0142");
            ValidationResult result = validator.validateLoanAccountDenormalizedData(loan, borrower);
            assertTrue(result.hasWarnings(Severity.HIGH));
            assertTrue(result.getWarnings(Severity.HIGH).stream()
                    .anyMatch(w -> w.field().equals("BORR_SSN_LST4")
                            && w.message().contains("SSN last-4 matches phone")));
        }

        @Test
        void ssnNotMatchingPhoneProducesNoSsnWarning() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setBorrowerSsnLast4("9999");
            LegacyBorrower borrower = createValidBorrower();
            borrower.setPhoneNumber("217-555-0142");
            ValidationResult result = validator.validateLoanAccountDenormalizedData(loan, borrower);
            assertFalse(result.getWarnings().stream()
                    .anyMatch(w -> w.field().equals("BORR_SSN_LST4")));
        }

        @Test
        void nullBorrowerProducesNoWarnings() {
            LegacyLoanAccount loan = createValidLoanAccount();
            ValidationResult result = validator.validateLoanAccountDenormalizedData(loan, null);
            assertFalse(result.hasWarnings());
        }
    }

    // =========================================================================
    // Payment Validation Tests
    // =========================================================================

    @Nested
    class PaymentValidationTests {

        private final Set<String> validLoanAccountNumbers = Set.of("LN-2019-00142", "LN-2020-00398");

        @Test
        void validPaymentProducesNoWarnings() {
            LegacyPayment payment = createValidPayment();
            ValidationResult result = validator.validatePayment(payment, validLoanAccountNumbers);
            assertFalse(result.hasWarnings());
        }

        @Test
        void orphanedLoanAccountProducesHighWarning() {
            LegacyPayment payment = createValidPayment();
            payment.setLoanAccountNumber("LN-9999-00000");
            ValidationResult result = validator.validatePayment(payment, validLoanAccountNumbers);
            assertTrue(result.hasWarnings(Severity.HIGH));
            assertTrue(result.getWarnings(Severity.HIGH).stream()
                    .anyMatch(w -> w.field().equals("LN_ACCT_NBR") && w.message().contains("Orphaned")));
        }

        @Test
        void paymentComponentMismatchProducesCriticalWarning() {
            LegacyPayment payment = createValidPayment();
            // Set components that don't sum to total
            payment.setTotalAmount("1,487.02");
            payment.setPrincipalAmount("456.78");
            payment.setInterestAmount("1,074.69");
            payment.setEscrowAmount("355.55");
            payment.setLateFee("0.00");
            // Sum = 456.78 + 1074.69 + 355.55 + 0.00 = 1887.02 != 1487.02

            ValidationResult result = validator.validatePayment(payment, validLoanAccountNumbers);
            assertTrue(result.hasWarnings(Severity.CRITICAL));
            assertTrue(result.getWarnings(Severity.CRITICAL).stream()
                    .anyMatch(w -> w.field().equals("PMT_AMT")
                            && w.message().contains("component mismatch")));
        }

        @Test
        void paymentComponentsMatchingTotalProducesNoMismatchWarning() {
            LegacyPayment payment = createValidPayment();
            // Components sum correctly: 100 + 200 + 50 + 10 = 360
            payment.setTotalAmount("360.00");
            payment.setPrincipalAmount("100.00");
            payment.setInterestAmount("200.00");
            payment.setEscrowAmount("50.00");
            payment.setLateFee("10.00");

            ValidationResult result = validator.validatePayment(payment, validLoanAccountNumbers);
            assertFalse(result.getWarnings().stream()
                    .anyMatch(w -> w.message().contains("component mismatch")));
        }

        @Test
        void nonNumericPaymentAmountProducesCriticalWarning() {
            LegacyPayment payment = createValidPayment();
            payment.setTotalAmount("PENDING");
            ValidationResult result = validator.validatePayment(payment, validLoanAccountNumbers);
            assertTrue(result.hasWarnings(Severity.CRITICAL));
            assertTrue(result.getWarnings(Severity.CRITICAL).stream()
                    .anyMatch(w -> w.field().equals("PMT_AMT")));
        }

        @Test
        void invalidPaymentDateProducesHighWarning() {
            LegacyPayment payment = createValidPayment();
            payment.setPaymentDate("2025-12-15");
            ValidationResult result = validator.validatePayment(payment, validLoanAccountNumbers);
            assertTrue(result.hasWarnings(Severity.HIGH));
            assertTrue(result.getWarnings(Severity.HIGH).stream()
                    .anyMatch(w -> w.field().equals("PMT_DT")));
        }

        @Test
        void unknownPaymentTypeProducesMediumWarning() {
            LegacyPayment payment = createValidPayment();
            payment.setTypeCode("XXX");
            ValidationResult result = validator.validatePayment(payment, validLoanAccountNumbers);
            assertTrue(result.hasWarnings(Severity.MEDIUM));
            assertTrue(result.getWarnings(Severity.MEDIUM).stream()
                    .anyMatch(w -> w.field().equals("PMT_TYP_CD")));
        }

        @Test
        void unknownPaymentStatusProducesMediumWarning() {
            LegacyPayment payment = createValidPayment();
            payment.setStatusCode("XXX");
            ValidationResult result = validator.validatePayment(payment, validLoanAccountNumbers);
            assertTrue(result.hasWarnings(Severity.MEDIUM));
            assertTrue(result.getWarnings(Severity.MEDIUM).stream()
                    .anyMatch(w -> w.field().equals("PMT_STAT_CD")));
        }

        @Test
        void nullRequiredFieldsProduceCriticalWarnings() {
            LegacyPayment payment = createValidPayment();
            payment.setPaymentSequenceNumber(null);
            payment.setLoanAccountNumber(null);
            ValidationResult result = validator.validatePayment(payment, validLoanAccountNumbers);
            assertTrue(result.hasWarnings(Severity.CRITICAL));
            long criticalCount = result.getWarnings(Severity.CRITICAL).stream()
                    .filter(w -> w.field().equals("PMT_SEQ_NBR") || w.field().equals("LN_ACCT_NBR"))
                    .count();
            assertEquals(2, criticalCount);
        }
    }

    // =========================================================================
    // ValidationResult Tests
    // =========================================================================

    @Nested
    class ValidationResultTests {

        @Test
        void mergesCombinesWarnings() {
            ValidationResult r1 = new ValidationResult();
            r1.addWarning(Severity.HIGH, "T1", "R1", "F1", "msg1", "v1");

            ValidationResult r2 = new ValidationResult();
            r2.addWarning(Severity.LOW, "T2", "R2", "F2", "msg2", "v2");

            r1.merge(r2);
            assertEquals(2, r1.warningCount());
        }

        @Test
        void filtersBySeverity() {
            ValidationResult result = new ValidationResult();
            result.addWarning(Severity.CRITICAL, "T", "R", "F1", "msg1", "v1");
            result.addWarning(Severity.LOW, "T", "R", "F2", "msg2", "v2");
            result.addWarning(Severity.CRITICAL, "T", "R", "F3", "msg3", "v3");

            assertEquals(2, result.getWarnings(Severity.CRITICAL).size());
            assertEquals(1, result.getWarnings(Severity.LOW).size());
            assertEquals(0, result.getWarnings(Severity.MEDIUM).size());
        }

        @Test
        void hasWarningsBySeverity() {
            ValidationResult result = new ValidationResult();
            result.addWarning(Severity.HIGH, "T", "R", "F", "msg", "v");

            assertTrue(result.hasWarnings(Severity.HIGH));
            assertFalse(result.hasWarnings(Severity.CRITICAL));
        }
    }

    // =========================================================================
    // Test Helpers
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
        LegacyLoanAccount l = new LegacyLoanAccount();
        l.setLoanAccountNumber("LN-2019-00142");
        l.setBorrowerId("B-10001");
        l.setBorrowerFirstName("James");
        l.setBorrowerLastName("Mitchell");
        l.setBorrowerSsnLast4("0142");
        l.setProductCode("FXD30");
        l.setOriginalAmount("285,000");
        l.setCurrentBalance("271,432.56");
        l.setInterestRate("4.750");
        l.setTermMonths("360");
        l.setMonthlyPayment("1,487.02");
        l.setOriginationDate("02/15/2019");
        l.setMaturityDate("02/15/2049");
        l.setFirstPaymentDate("03/15/2019");
        l.setNextPaymentDate("01/15/2026");
        l.setStatusCode("ACT");
        l.setDelinquencyDays("0");
        l.setEscrowBalance("3,245.80");
        l.setLtvPercent("82.5");
        l.setPropertyAddress("742 Elm Street");
        l.setPropertyCity("Springfield");
        l.setPropertyState("IL");
        l.setPropertyZip("62701");
        l.setPropertyType("SFR");
        l.setAppraisedValue("345,000");
        l.setCreatedDate("02/01/2019");
        l.setUpdatedDate("12/01/2025");
        return l;
    }

    private LegacyPayment createValidPayment() {
        LegacyPayment p = new LegacyPayment();
        p.setPaymentSequenceNumber("PMT-2025120001");
        p.setLoanAccountNumber("LN-2019-00142");
        p.setPaymentDate("12/15/2025");
        // Components that sum correctly: 100 + 200 + 50 + 0 = 350
        p.setTotalAmount("350.00");
        p.setPrincipalAmount("100.00");
        p.setInterestAmount("200.00");
        p.setEscrowAmount("50.00");
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
