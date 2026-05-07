package com.workshop.loanservice.service;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // ANO-001: Amount Parsing — currency symbols, whitespace, commas, garbage
    // =========================================================================
    @Nested
    class AmountParsing {

        @Test
        void parsesStandardCommaAmount() {
            BigDecimal result = validator.parseAmount("285,000", "TEST-01", "LN_ORIG_AMT");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        void parsesAmountWithDecimalAndCommas() {
            BigDecimal result = validator.parseAmount("1,487.02", "TEST-01", "LN_PMT_AMT");
            assertEquals(new BigDecimal("1487.02"), result);
        }

        @Test
        void parsesAmountWithDollarSign() {
            BigDecimal result = validator.parseAmount("$525,000", "TEST-01", "LN_ORIG_AMT");
            assertEquals(new BigDecimal("525000"), result);
        }

        @Test
        void parsesAmountWithSpaceSeparator() {
            BigDecimal result = validator.parseAmount("285 000", "TEST-01", "LN_ORIG_AMT");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        void returnsZeroForNullAmount() {
            BigDecimal result = validator.parseAmount(null, "TEST-01", "LN_ORIG_AMT");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void returnsZeroForBlankAmount() {
            BigDecimal result = validator.parseAmount("", "TEST-01", "LN_ORIG_AMT");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void returnsZeroForNonNumericSentinel() {
            BigDecimal result = validator.parseAmount("N/A", "TEST-01", "LN_ORIG_AMT");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void parsesNegativeAmount() {
            BigDecimal result = validator.parseAmount("-1,000", "TEST-01", "LN_ORIG_AMT");
            assertEquals(new BigDecimal("-1000"), result);
        }

        @Test
        void parsesLargeAmountWithMultipleCommas() {
            BigDecimal result = validator.parseAmount("1,500,000", "TEST-01", "PROD_MAX_AMT");
            assertEquals(new BigDecimal("1500000"), result);
        }
    }

    // =========================================================================
    // ANO-001: Decimal Parsing — interest rates, LTV
    // =========================================================================
    @Nested
    class DecimalParsing {

        @Test
        void parsesStandardDecimal() {
            BigDecimal result = validator.parseDecimal("4.750", "TEST-01", "LN_INT_RT");
            assertEquals(new BigDecimal("4.750"), result);
        }

        @Test
        void returnsZeroForNullDecimal() {
            BigDecimal result = validator.parseDecimal(null, "TEST-01", "LN_INT_RT");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void returnsZeroForUnparseableDecimal() {
            BigDecimal result = validator.parseDecimal("ABC", "TEST-01", "LN_INT_RT");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void trimsWhitespace() {
            BigDecimal result = validator.parseDecimal("  3.125 ", "TEST-01", "LN_INT_RT");
            assertEquals(new BigDecimal("3.125"), result);
        }
    }

    // =========================================================================
    // ANO-001: Integer Parsing — credit scores, term months, delinquency days
    // =========================================================================
    @Nested
    class IntegerParsing {

        @Test
        void parsesStandardInteger() {
            Integer result = validator.parseInteger("360", "TEST-01", "LN_TERM_MOS");
            assertEquals(360, result);
        }

        @Test
        void returnsNullForNullInput() {
            Integer result = validator.parseInteger(null, "TEST-01", "LN_TERM_MOS");
            assertNull(result);
        }

        @Test
        void returnsNullForNonNumeric() {
            Integer result = validator.parseInteger("N/A", "TEST-01", "BORR_CRDT_SCR");
            assertNull(result);
        }

        @Test
        void trimsWhitespace() {
            Integer result = validator.parseInteger("  180 ", "TEST-01", "LN_TERM_MOS");
            assertEquals(180, result);
        }
    }

    // =========================================================================
    // ANO-002: Date Parsing — MM/DD/YYYY, ISO, fallback, invalid
    // =========================================================================
    @Nested
    class DateParsing {

        @Test
        void parsesStandardMmDdYyyy() {
            LocalDate result = validator.parseDate("03/15/1978", "TEST-01", "BORR_DOB_DT");
            assertEquals(LocalDate.of(1978, 3, 15), result);
        }

        @Test
        void parsesIsoFormat() {
            LocalDate result = validator.parseDate("2019-02-15", "TEST-01", "LN_ORIG_DT");
            assertEquals(LocalDate.of(2019, 2, 15), result);
        }

        @Test
        void returnsNullForNullDate() {
            LocalDate result = validator.parseDate(null, "TEST-01", "BORR_DOB_DT");
            assertNull(result);
        }

        @Test
        void returnsNullForBlankDate() {
            LocalDate result = validator.parseDate("", "TEST-01", "BORR_DOB_DT");
            assertNull(result);
        }

        @Test
        void returnsNullForGarbageDate() {
            LocalDate result = validator.parseDate("NOT_A_DATE", "TEST-01", "BORR_DOB_DT");
            assertNull(result);
        }

        @Test
        void formatsDateToIso() {
            String result = validator.formatDateToIso("03/15/1978", "TEST-01", "BORR_DOB_DT");
            assertEquals("1978-03-15", result);
        }

        @Test
        void formatDateToIsoReturnsNullForNull() {
            String result = validator.formatDateToIso(null, "TEST-01", "BORR_DOB_DT");
            assertNull(result);
        }

        @Test
        void formatDateToIsoReturnsRawOnFailure() {
            String result = validator.formatDateToIso("GARBAGE", "TEST-01", "BORR_DOB_DT");
            assertEquals("GARBAGE", result);
        }
    }

    // =========================================================================
    // ANO-004: Status Code Validation
    // =========================================================================
    @Nested
    class StatusCodeValidation {

        @Test
        void acceptsValidLoanStatus() {
            String result = validator.validateLoanStatus("ACT", "TEST-01");
            assertEquals("ACT", result);
        }

        @Test
        void normalizesLowerCaseStatus() {
            String result = validator.validateLoanStatus("act", "TEST-01");
            assertEquals("ACT", result);
        }

        @Test
        void acceptsAllValidLoanStatuses() {
            assertAll(
                () -> assertEquals("ACT", validator.validateLoanStatus("ACT", "T")),
                () -> assertEquals("CLO", validator.validateLoanStatus("CLO", "T")),
                () -> assertEquals("DFT", validator.validateLoanStatus("DFT", "T")),
                () -> assertEquals("FRB", validator.validateLoanStatus("FRB", "T"))
            );
        }

        @Test
        void returnsNormalizedUnknownStatus() {
            String result = validator.validateLoanStatus("ACTV", "TEST-01");
            assertEquals("ACTV", result);
        }

        @Test
        void handlesNullStatus() {
            String result = validator.validateLoanStatus(null, "TEST-01");
            assertNull(result);
        }

        @Test
        void validatesPaymentStatuses() {
            assertAll(
                () -> assertEquals("PST", validator.validatePaymentStatus("PST", "T")),
                () -> assertEquals("REV", validator.validatePaymentStatus("REV", "T")),
                () -> assertEquals("NSF", validator.validatePaymentStatus("NSF", "T")),
                () -> assertEquals("PND", validator.validatePaymentStatus("PND", "T"))
            );
        }

        @Test
        void validatesPaymentTypes() {
            assertAll(
                () -> assertEquals("REG", validator.validatePaymentType("REG", "T")),
                () -> assertEquals("EXT", validator.validatePaymentType("EXT", "T")),
                () -> assertEquals("PRT", validator.validatePaymentType("PRT", "T")),
                () -> assertEquals("PRE", validator.validatePaymentType("PRE", "T"))
            );
        }

        @Test
        void validatesPropertyTypes() {
            assertAll(
                () -> assertEquals("SFR", validator.validatePropertyType("SFR", "T")),
                () -> assertEquals("CND", validator.validatePropertyType("CND", "T")),
                () -> assertEquals("MFR", validator.validatePropertyType("MFR", "T")),
                () -> assertEquals("TWN", validator.validatePropertyType("TWN", "T"))
            );
        }
    }

    // =========================================================================
    // ANO-006: Required Field Validation
    // =========================================================================
    @Nested
    class RequiredFieldValidation {

        @Test
        void borrowerWithAllRequiredFieldsPasses() {
            LegacyBorrower b = createValidBorrower();
            List<String> violations = validator.validateBorrowerRequired(b);
            assertTrue(violations.isEmpty());
        }

        @Test
        void borrowerWithNullFirstNameFails() {
            LegacyBorrower b = createValidBorrower();
            b.setFirstName(null);
            List<String> violations = validator.validateBorrowerRequired(b);
            assertEquals(1, violations.size());
            assertTrue(violations.get(0).contains("BORR_FST_NM"));
        }

        @Test
        void borrowerWithNullLastNameFails() {
            LegacyBorrower b = createValidBorrower();
            b.setLastName(null);
            List<String> violations = validator.validateBorrowerRequired(b);
            assertEquals(1, violations.size());
            assertTrue(violations.get(0).contains("BORR_LST_NM"));
        }

        @Test
        void borrowerWithBlankSsnFails() {
            LegacyBorrower b = createValidBorrower();
            b.setSsnEncrypted("");
            List<String> violations = validator.validateBorrowerRequired(b);
            assertEquals(1, violations.size());
            assertTrue(violations.get(0).contains("BORR_SSN_ENCR"));
        }

        @Test
        void loanAccountWithAllRequiredFieldsPasses() {
            LegacyLoanAccount la = createValidLoanAccount();
            List<String> violations = validator.validateLoanAccountRequired(la);
            assertTrue(violations.isEmpty());
        }

        @Test
        void loanAccountWithNullBorrowerIdFails() {
            LegacyLoanAccount la = createValidLoanAccount();
            la.setBorrowerId(null);
            List<String> violations = validator.validateLoanAccountRequired(la);
            assertEquals(1, violations.size());
            assertTrue(violations.get(0).contains("BORR_ID"));
        }

        @Test
        void loanAccountWithNullStatusFails() {
            LegacyLoanAccount la = createValidLoanAccount();
            la.setStatusCode(null);
            List<String> violations = validator.validateLoanAccountRequired(la);
            assertEquals(1, violations.size());
            assertTrue(violations.get(0).contains("LN_STAT_CD"));
        }

        @Test
        void paymentWithAllRequiredFieldsPasses() {
            LegacyPayment p = createValidPayment();
            List<String> violations = validator.validatePaymentRequired(p);
            assertTrue(violations.isEmpty());
        }

        @Test
        void paymentWithNullLoanAccountNumberFails() {
            LegacyPayment p = createValidPayment();
            p.setLoanAccountNumber(null);
            List<String> violations = validator.validatePaymentRequired(p);
            assertEquals(1, violations.size());
            assertTrue(violations.get(0).contains("LN_ACCT_NBR"));
        }
    }

    // =========================================================================
    // ANO-007: Credit Score Validation
    // =========================================================================
    @Nested
    class CreditScoreValidation {

        @Test
        void validCreditScore() {
            Integer result = validator.validateCreditScore("745", "TEST-01");
            assertEquals(745, result);
        }

        @Test
        void creditScoreBelowRange() {
            Integer result = validator.validateCreditScore("200", "TEST-01");
            assertEquals(200, result);
        }

        @Test
        void creditScoreAboveRange() {
            Integer result = validator.validateCreditScore("900", "TEST-01");
            assertEquals(900, result);
        }

        @Test
        void nullCreditScore() {
            Integer result = validator.validateCreditScore(null, "TEST-01");
            assertNull(result);
        }

        @Test
        void nonNumericCreditScore() {
            Integer result = validator.validateCreditScore("N/A", "TEST-01");
            assertNull(result);
        }
    }

    // =========================================================================
    // ANO-008: Payment Amount Reconciliation
    // =========================================================================
    @Nested
    class PaymentReconciliation {

        @Test
        void balancedPaymentPasses() {
            LegacyPayment p = createValidPayment();
            p.setTotalAmount("1,000.00");
            p.setPrincipalAmount("500.00");
            p.setInterestAmount("400.00");
            p.setEscrowAmount("100.00");
            p.setLateFee("0.00");
            assertTrue(validator.validatePaymentAmountReconciliation(p));
        }

        @Test
        void unbalancedPaymentFails() {
            LegacyPayment p = createValidPayment();
            p.setTotalAmount("1,487.02");
            p.setPrincipalAmount("456.78");
            p.setInterestAmount("1,074.69");
            p.setEscrowAmount("355.55");
            p.setLateFee("0.00");
            assertFalse(validator.validatePaymentAmountReconciliation(p));
        }

        @Test
        void paymentWithSmallRoundingDifferencePasses() {
            LegacyPayment p = createValidPayment();
            p.setTotalAmount("1,000.01");
            p.setPrincipalAmount("500.00");
            p.setInterestAmount("400.00");
            p.setEscrowAmount("100.00");
            p.setLateFee("0.00");
            assertTrue(validator.validatePaymentAmountReconciliation(p));
        }
    }

    // =========================================================================
    // ANO-009: Delinquency-Status Consistency
    // =========================================================================
    @Nested
    class DelinquencyStatusConsistency {

        @Test
        void activeWithZeroDelinquencyPasses() {
            LegacyLoanAccount la = createValidLoanAccount();
            la.setStatusCode("ACT");
            la.setDelinquencyDays("0");
            assertTrue(validator.validateDelinquencyStatusConsistency(la));
        }

        @Test
        void activeWithDelinquencyDaysFails() {
            LegacyLoanAccount la = createValidLoanAccount();
            la.setStatusCode("ACT");
            la.setDelinquencyDays("15");
            assertFalse(validator.validateDelinquencyStatusConsistency(la));
        }

        @Test
        void highDelinquencyWithActiveStatusFails() {
            LegacyLoanAccount la = createValidLoanAccount();
            la.setStatusCode("ACT");
            la.setDelinquencyDays("90");
            assertFalse(validator.validateDelinquencyStatusConsistency(la));
        }

        @Test
        void highDelinquencyWithDefaultStatusPasses() {
            LegacyLoanAccount la = createValidLoanAccount();
            la.setStatusCode("DFT");
            la.setDelinquencyDays("120");
            assertTrue(validator.validateDelinquencyStatusConsistency(la));
        }
    }

    // =========================================================================
    // ANO-010: LTV Consistency
    // =========================================================================
    @Nested
    class LtvConsistency {

        @Test
        void consistentLtvPasses() {
            LegacyLoanAccount la = createValidLoanAccount();
            la.setCurrentBalance("200,000");
            la.setAppraisedValue("400,000");
            la.setLtvPercent("50.0");
            assertTrue(validator.validateLtvConsistency(la));
        }

        @Test
        void inconsistentLtvFails() {
            LegacyLoanAccount la = createValidLoanAccount();
            la.setCurrentBalance("200,000");
            la.setAppraisedValue("400,000");
            la.setLtvPercent("82.5");
            // Computed = 200000/400000*100 = 50.0, stored = 82.5, delta = 32.5 > 5.0
            assertFalse(validator.validateLtvConsistency(la));
        }

        @Test
        void zeroAppraisedValueFails() {
            LegacyLoanAccount la = createValidLoanAccount();
            la.setCurrentBalance("200,000");
            la.setAppraisedValue("0");
            la.setLtvPercent("50.0");
            assertFalse(validator.validateLtvConsistency(la));
        }
    }

    // =========================================================================
    // Safe String Handling
    // =========================================================================
    @Nested
    class SafeStringHandling {

        @Test
        void returnsValueForNonBlank() {
            assertEquals("James", validator.safeString("James", "Unknown"));
        }

        @Test
        void returnsDefaultForNull() {
            assertEquals("Unknown", validator.safeString(null, "Unknown"));
        }

        @Test
        void returnsDefaultForBlank() {
            assertEquals("Unknown", validator.safeString("   ", "Unknown"));
        }

        @Test
        void trimsValue() {
            assertEquals("James", validator.safeString("  James  ", "Unknown"));
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
        b.setCreditScore("745");
        b.setStatusCode("ACT");
        return b;
    }

    private LegacyLoanAccount createValidLoanAccount() {
        LegacyLoanAccount la = new LegacyLoanAccount();
        la.setLoanAccountNumber("LN-2019-00142");
        la.setBorrowerId("B-10001");
        la.setBorrowerFirstName("James");
        la.setBorrowerLastName("Mitchell");
        la.setProductCode("FXD30");
        la.setOriginalAmount("285,000");
        la.setCurrentBalance("271,432.56");
        la.setInterestRate("4.750");
        la.setTermMonths("360");
        la.setMonthlyPayment("1,487.02");
        la.setStatusCode("ACT");
        la.setDelinquencyDays("0");
        la.setLtvPercent("82.5");
        la.setPropertyAddress("742 Elm Street");
        la.setPropertyCity("Springfield");
        la.setPropertyState("IL");
        la.setPropertyZip("62701");
        la.setPropertyType("SFR");
        la.setAppraisedValue("345,000");
        la.setOriginationDate("02/15/2019");
        return la;
    }

    private LegacyPayment createValidPayment() {
        LegacyPayment p = new LegacyPayment();
        p.setPaymentSequenceNumber("PMT-2025120001");
        p.setLoanAccountNumber("LN-2019-00142");
        p.setPaymentDate("12/15/2025");
        p.setTotalAmount("1,487.02");
        p.setPrincipalAmount("456.78");
        p.setInterestAmount("1,074.69");
        p.setEscrowAmount("355.55");
        p.setLateFee("0.00");
        p.setTypeCode("REG");
        p.setStatusCode("PST");
        return p;
    }
}
