package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

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
    class ParseLegacyAmountSafeTests {

        @Test
        void parsesAmountWithCommas() {
            assertEquals(new BigDecimal("285000"), validator.parseLegacyAmountSafe("285,000", "field", "rec"));
        }

        @Test
        void parsesAmountWithCommasAndDecimals() {
            assertEquals(new BigDecimal("1487.02"), validator.parseLegacyAmountSafe("1,487.02", "field", "rec"));
        }

        @Test
        void parsesAmountWithDollarSign() {
            assertEquals(new BigDecimal("285000"), validator.parseLegacyAmountSafe("$285,000", "field", "rec"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.parseLegacyAmountSafe(null, "field", "rec"));
        }

        @Test
        void returnsZeroForBlank() {
            assertEquals(BigDecimal.ZERO, validator.parseLegacyAmountSafe("  ", "field", "rec"));
        }

        @Test
        void returnsZeroForUnparseableText() {
            assertEquals(BigDecimal.ZERO, validator.parseLegacyAmountSafe("N/A", "field", "rec"));
        }

        @Test
        void returnsZeroForDashes() {
            assertEquals(BigDecimal.ZERO, validator.parseLegacyAmountSafe("--", "field", "rec"));
        }

        @Test
        void parsesPlainDecimal() {
            assertEquals(new BigDecimal("4.750"), validator.parseLegacyAmountSafe("4.750", "field", "rec"));
        }
    }

    @Nested
    class ParseLegacyDecimalSafeTests {

        @Test
        void parsesDecimalValue() {
            assertEquals(new BigDecimal("5.250"), validator.parseLegacyDecimalSafe("5.250", "field", "rec"));
        }

        @Test
        void parsesDecimalWithWhitespace() {
            assertEquals(new BigDecimal("3.125"), validator.parseLegacyDecimalSafe(" 3.125 ", "field", "rec"));
        }

        @Test
        void returnsZeroForUnparseable() {
            assertEquals(BigDecimal.ZERO, validator.parseLegacyDecimalSafe("TBD", "field", "rec"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.parseLegacyDecimalSafe(null, "field", "rec"));
        }
    }

    @Nested
    class ParseLegacyIntegerSafeTests {

        @Test
        void parsesIntegerString() {
            assertEquals(745, validator.parseLegacyIntegerSafe("745", "field", "rec"));
        }

        @Test
        void parsesIntegerWithWhitespace() {
            assertEquals(780, validator.parseLegacyIntegerSafe(" 780 ", "field", "rec"));
        }

        @Test
        void returnsNullForUnparseable() {
            assertNull(validator.parseLegacyIntegerSafe("N/A", "field", "rec"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.parseLegacyIntegerSafe(null, "field", "rec"));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.parseLegacyIntegerSafe("", "field", "rec"));
        }

        @Test
        void parsesIntegerWithCommas() {
            assertEquals(92500, validator.parseLegacyIntegerSafe("92,500", "field", "rec"));
        }
    }

    @Nested
    class ParseLegacyDateSafeTests {

        @Test
        void parsesValidDate() {
            var date = validator.parseLegacyDateSafe("03/15/1978", "field", "rec");
            assertNotNull(date);
            assertEquals(1978, date.getYear());
            assertEquals(3, date.getMonthValue());
            assertEquals(15, date.getDayOfMonth());
        }

        @Test
        void returnsNullForIsoFormat() {
            assertNull(validator.parseLegacyDateSafe("2025-12-01", "field", "rec"));
        }

        @Test
        void returnsNullForGarbage() {
            assertNull(validator.parseLegacyDateSafe("TBD", "field", "rec"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.parseLegacyDateSafe(null, "field", "rec"));
        }

        @Test
        void returnsNullForInvalidDate() {
            assertNull(validator.parseLegacyDateSafe("13/32/2025", "field", "rec"));
        }
    }

    @Nested
    class FormatDateToIsoTests {

        @Test
        void convertsLegacyDateToIso() {
            assertEquals("2019-02-15", validator.formatDateToIso("02/15/2019", "field", "rec"));
        }

        @Test
        void returnsOriginalForUnparseable() {
            assertEquals("bad-date", validator.formatDateToIso("bad-date", "field", "rec"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.formatDateToIso(null, "field", "rec"));
        }
    }

    // =========================================================================
    // Borrower Validation Tests
    // =========================================================================

    @Nested
    class ValidateBorrowerTests {

        @Test
        void validBorrowerProducesNoWarnings() {
            LegacyBorrower b = buildBorrower("B-10001", "James", "Mitchell", "745", "ACT");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void detectsMissingFirstName() {
            LegacyBorrower b = buildBorrower("B-10001", null, "Mitchell", "745", "ACT");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("missing first name")));
        }

        @Test
        void detectsMissingLastName() {
            LegacyBorrower b = buildBorrower("B-10001", "James", "", "745", "ACT");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("missing last name")));
        }

        @Test
        void detectsCreditScoreOutOfRange() {
            LegacyBorrower b = buildBorrower("B-10001", "James", "Mitchell", "200", "ACT");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("credit score") && w.contains("outside valid range")));
        }

        @Test
        void detectsCreditScoreAboveRange() {
            LegacyBorrower b = buildBorrower("B-10001", "James", "Mitchell", "900", "ACT");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("credit score") && w.contains("outside valid range")));
        }

        @Test
        void detectsUnrecognizedStatusCode() {
            LegacyBorrower b = buildBorrower("B-10001", "James", "Mitchell", "745", "XYZ");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("unrecognized status code")));
        }

        @Test
        void acceptsValidStatusCodes() {
            LegacyBorrower b1 = buildBorrower("B-10001", "James", "Mitchell", "745", "ACT");
            LegacyBorrower b2 = buildBorrower("B-10002", "Sarah", "Chen", "780", "INA");
            assertTrue(validator.validateBorrower(b1).isEmpty());
            assertTrue(validator.validateBorrower(b2).isEmpty());
        }

        private LegacyBorrower buildBorrower(String id, String first, String last, String creditScore, String status) {
            LegacyBorrower b = new LegacyBorrower();
            b.setBorrowerId(id);
            b.setFirstName(first);
            b.setLastName(last);
            b.setCreditScore(creditScore);
            b.setStatusCode(status);
            b.setDateOfBirth("03/15/1978");
            b.setCreatedDate("01/15/2019");
            return b;
        }
    }

    // =========================================================================
    // Loan Account Validation Tests
    // =========================================================================

    @Nested
    class ValidateLoanAccountTests {

        @Test
        void validLoanProducesNoWarnings() {
            LegacyLoanAccount acct = buildLoan("LN-001", "ACT", "0", "SFR",
                    "285,000", "345,000", "82.61");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void detectsInvalidStatusCode() {
            LegacyLoanAccount acct = buildLoan("LN-001", "BAD", "0", "SFR",
                    "285,000", "345,000", "82.61");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("invalid status code")));
        }

        @Test
        void detectsDelinquencyStatusMismatch() {
            LegacyLoanAccount acct = buildLoan("LN-001", "ACT", "15", "SFR",
                    "285,000", "345,000", "82.61");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("delinquent days but status is ACT")));
        }

        @Test
        void noWarningForDelinquencyOnDefaultStatus() {
            LegacyLoanAccount acct = buildLoan("LN-001", "DFT", "90", "SFR",
                    "285,000", "345,000", "82.61");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertFalse(warnings.stream().anyMatch(w -> w.contains("delinquent days")));
        }

        @Test
        void detectsLtvInconsistency() {
            LegacyLoanAccount acct = buildLoan("LN-001", "ACT", "0", "SFR",
                    "285,000", "345,000", "75.0");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("stored LTV") && w.contains("differs")));
        }

        @Test
        void acceptsLtvWithinTolerance() {
            LegacyLoanAccount acct = buildLoan("LN-001", "ACT", "0", "SFR",
                    "285,000", "345,000", "82.61");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertFalse(warnings.stream().anyMatch(w -> w.contains("LTV")));
        }

        @Test
        void detectsUnrecognizedPropertyType() {
            LegacyLoanAccount acct = buildLoan("LN-001", "ACT", "0", "ZZZ",
                    "285,000", "345,000", "82.61");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("unrecognized property type")));
        }

        private LegacyLoanAccount buildLoan(String id, String status, String dlqDays, String propType,
                                              String origAmt, String appraisedVal, String ltv) {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber(id);
            acct.setStatusCode(status);
            acct.setDelinquencyDays(dlqDays);
            acct.setPropertyType(propType);
            acct.setOriginalAmount(origAmt);
            acct.setAppraisedValue(appraisedVal);
            acct.setLtvPercent(ltv);
            acct.setOriginationDate("02/15/2019");
            acct.setMaturityDate("02/15/2049");
            return acct;
        }
    }

    // =========================================================================
    // Payment Validation Tests
    // =========================================================================

    @Nested
    class ValidatePaymentTests {

        @Test
        void validPaymentProducesNoWarnings() {
            LegacyPayment pmt = buildPayment("PMT-001", "REG", "PST",
                    "2,924.18", "1,842.56", "815.50", "266.12", "0.00",
                    "12/01/2025", "12/01/2025", "12/01/2025");
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.isEmpty(), "Expected no warnings but got: " + warnings);
        }

        @Test
        void detectsComponentSumMismatch() {
            LegacyPayment pmt = buildPayment("PMT-001", "REG", "PST",
                    "1,487.02", "456.78", "1,074.69", "355.55", "0.00",
                    "12/15/2025", "12/14/2025", "12/15/2025");
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("component sum") && w.contains("!= total")));
        }

        @Test
        void detectsLateFeeNotInTotal() {
            LegacyPayment pmt = buildPayment("PMT-001", "REG", "PST",
                    "1,077.05", "295.82", "781.23", "0.00", "47.50",
                    "11/01/2025", "11/18/2025", "11/19/2025");
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("component sum") && w.contains("!= total")));
        }

        @Test
        void detectsInvalidPaymentType() {
            LegacyPayment pmt = buildPayment("PMT-001", "BAD", "PST",
                    "1,000.00", "500.00", "500.00", "0.00", "0.00",
                    "12/01/2025", "12/01/2025", "12/01/2025");
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("invalid type code")));
        }

        @Test
        void detectsInvalidPaymentStatus() {
            LegacyPayment pmt = buildPayment("PMT-001", "REG", "BAD",
                    "1,000.00", "500.00", "500.00", "0.00", "0.00",
                    "12/01/2025", "12/01/2025", "12/01/2025");
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("invalid status code")));
        }

        @Test
        void detectsPaymentDateAfterReceivedDate() {
            LegacyPayment pmt = buildPayment("PMT-001", "REG", "PST",
                    "1,000.00", "500.00", "500.00", "0.00", "0.00",
                    "12/01/2025", "11/25/2025", "12/01/2025");
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("received date") && w.contains("before payment date")));
        }

        @Test
        void detectsProcessedDateBeforeReceivedDate() {
            LegacyPayment pmt = buildPayment("PMT-001", "REG", "PST",
                    "1,000.00", "500.00", "500.00", "0.00", "0.00",
                    "12/01/2025", "12/05/2025", "12/03/2025");
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("processed date") && w.contains("before received date")));
        }

        private LegacyPayment buildPayment(String id, String type, String status,
                                             String total, String principal, String interest,
                                             String escrow, String lateFee,
                                             String pmtDate, String recvDate, String procDate) {
            LegacyPayment pmt = new LegacyPayment();
            pmt.setPaymentSequenceNumber(id);
            pmt.setLoanAccountNumber("LN-001");
            pmt.setTypeCode(type);
            pmt.setStatusCode(status);
            pmt.setTotalAmount(total);
            pmt.setPrincipalAmount(principal);
            pmt.setInterestAmount(interest);
            pmt.setEscrowAmount(escrow);
            pmt.setLateFee(lateFee);
            pmt.setPaymentDate(pmtDate);
            pmt.setReceivedDate(recvDate);
            pmt.setProcessedDate(procDate);
            return pmt;
        }
    }

    // =========================================================================
    // Effective Status Resolution Tests
    // =========================================================================

    @Nested
    class ResolveEffectiveLoanStatusTests {

        @Test
        void activeWithZeroDelinquency() {
            assertEquals("Active", validator.resolveEffectiveLoanStatus("ACT", "0", "LN-001"));
        }

        @Test
        void activeWithDelinquency() {
            assertEquals("Active (Delinquent)", validator.resolveEffectiveLoanStatus("ACT", "15", "LN-001"));
        }

        @Test
        void defaultStatusUnchanged() {
            assertEquals("Default", validator.resolveEffectiveLoanStatus("DFT", "90", "LN-001"));
        }

        @Test
        void nullStatusReturnsUnknown() {
            assertEquals("Unknown", validator.resolveEffectiveLoanStatus(null, "0", "LN-001"));
        }

        @Test
        void nullDelinquencyDays() {
            assertEquals("Active", validator.resolveEffectiveLoanStatus("ACT", null, "LN-001"));
        }

        @Test
        void unparseableDelinquencyDays() {
            assertEquals("Active", validator.resolveEffectiveLoanStatus("ACT", "N/A", "LN-001"));
        }

        @Test
        void closedStatus() {
            assertEquals("Closed", validator.resolveEffectiveLoanStatus("CLO", "0", "LN-001"));
        }

        @Test
        void forbearanceStatus() {
            assertEquals("Forbearance", validator.resolveEffectiveLoanStatus("FRB", "30", "LN-001"));
        }

        @Test
        void unknownCodePassedThrough() {
            assertEquals("XYZ", validator.resolveEffectiveLoanStatus("XYZ", "0", "LN-001"));
        }
    }
}
