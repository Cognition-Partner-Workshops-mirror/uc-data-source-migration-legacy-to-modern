package com.workshop.loanservice.service;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    @Nested
    class AmountParsingTests {

        @Test
        void parsesValidCommaFormattedAmount() {
            BigDecimal result = validator.parseAndValidateAmount("285,000", "field", "REC-1");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        void parsesValidDecimalAmount() {
            BigDecimal result = validator.parseAndValidateAmount("1,487.02", "field", "REC-1");
            assertEquals(new BigDecimal("1487.02"), result);
        }

        @Test
        void returnsZeroForNullAmount() {
            BigDecimal result = validator.parseAndValidateAmount(null, "field", "REC-1");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void returnsZeroForBlankAmount() {
            BigDecimal result = validator.parseAndValidateAmount("", "field", "REC-1");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void returnsZeroForUnparseableAmount() {
            BigDecimal result = validator.parseAndValidateAmount("N/A", "field", "REC-1");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void stripsDollarSignBeforeParsing() {
            BigDecimal result = validator.parseAndValidateAmount("$285,000", "field", "REC-1");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        void returnsAbsoluteValueForNegativeAmount() {
            BigDecimal result = validator.parseAndValidateAmount("-500", "field", "REC-1");
            assertEquals(new BigDecimal("500"), result);
        }

        @Test
        void handlesWhitespaceInAmount() {
            BigDecimal result = validator.parseAndValidateAmount("  1,000  ", "field", "REC-1");
            assertEquals(new BigDecimal("1000"), result);
        }

        @Test
        void returnsZeroForTextValue() {
            BigDecimal result = validator.parseAndValidateAmount("TBD", "field", "REC-1");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void returnsZeroForPendingValue() {
            BigDecimal result = validator.parseAndValidateAmount("PENDING", "field", "REC-1");
            assertEquals(BigDecimal.ZERO, result);
        }
    }

    @Nested
    class DecimalParsingTests {

        @Test
        void parsesValidDecimal() {
            BigDecimal result = validator.parseAndValidateDecimal("4.750", "rate", "REC-1");
            assertEquals(new BigDecimal("4.750"), result);
        }

        @Test
        void returnsZeroForNullDecimal() {
            BigDecimal result = validator.parseAndValidateDecimal(null, "rate", "REC-1");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void returnsZeroForUnparseableDecimal() {
            BigDecimal result = validator.parseAndValidateDecimal("abc", "rate", "REC-1");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void trimsWhitespaceBeforeParsing() {
            BigDecimal result = validator.parseAndValidateDecimal("  3.125  ", "rate", "REC-1");
            assertEquals(new BigDecimal("3.125"), result);
        }
    }

    @Nested
    class IntegerParsingTests {

        @Test
        void parsesValidInteger() {
            Integer result = validator.parseAndValidateInteger("360", "term", "REC-1");
            assertEquals(360, result);
        }

        @Test
        void returnsNullForNullInteger() {
            Integer result = validator.parseAndValidateInteger(null, "term", "REC-1");
            assertNull(result);
        }

        @Test
        void returnsNullForBlankInteger() {
            Integer result = validator.parseAndValidateInteger("", "term", "REC-1");
            assertNull(result);
        }

        @Test
        void returnsNullForUnparseableInteger() {
            Integer result = validator.parseAndValidateInteger("abc", "term", "REC-1");
            assertNull(result);
        }

        @Test
        void trimsWhitespaceBeforeParsing() {
            Integer result = validator.parseAndValidateInteger("  180  ", "term", "REC-1");
            assertEquals(180, result);
        }
    }

    @Nested
    class DateValidationTests {

        @Test
        void acceptsValidDate() {
            String result = validator.parseAndValidateDate("03/15/1978", "dob", "REC-1");
            assertEquals("03/15/1978", result);
        }

        @Test
        void returnsNullForNullDate() {
            String result = validator.parseAndValidateDate(null, "dob", "REC-1");
            assertNull(result);
        }

        @Test
        void returnsNullForBlankDate() {
            String result = validator.parseAndValidateDate("", "dob", "REC-1");
            assertNull(result);
        }

        @Test
        void rejectsIsoFormatDate() {
            String result = validator.parseAndValidateDate("2025-01-15", "dob", "REC-1");
            assertNull(result);
        }

        @Test
        void rejectsInvalidCalendarDate() {
            String result = validator.parseAndValidateDate("13/32/2025", "dob", "REC-1");
            assertNull(result);
        }

        @Test
        void rejectsTextDate() {
            String result = validator.parseAndValidateDate("TBD", "dob", "REC-1");
            assertNull(result);
        }

        @Test
        void rejectsFebruary30() {
            String result = validator.parseAndValidateDate("02/30/2025", "dob", "REC-1");
            assertNull(result);
        }
    }

    @Nested
    class CreditScoreValidationTests {

        @Test
        void acceptsValidCreditScore() {
            Integer result = validator.validateCreditScore("745", "B-10001");
            assertEquals(745, result);
        }

        @Test
        void returnsNullForNullCreditScore() {
            Integer result = validator.validateCreditScore(null, "B-10001");
            assertNull(result);
        }

        @Test
        void returnsNullForUnparseableCreditScore() {
            Integer result = validator.validateCreditScore("abc", "B-10001");
            assertNull(result);
        }

        @Test
        void parsesButWarnsForOutOfRangeHigh() {
            Integer result = validator.validateCreditScore("999", "B-10001");
            assertEquals(999, result);
        }

        @Test
        void parsesButWarnsForOutOfRangeLow() {
            Integer result = validator.validateCreditScore("100", "B-10001");
            assertEquals(100, result);
        }

        @Test
        void acceptsBoundaryScores() {
            assertEquals(300, validator.validateCreditScore("300", "B-10001"));
            assertEquals(850, validator.validateCreditScore("850", "B-10001"));
        }
    }

    @Nested
    class StatusCodeValidationTests {

        @Test
        void acceptsValidLoanStatus() {
            String result = validator.validateStatusCode("ACT", Set.of("ACT", "CLO"), "status", "REC-1");
            assertEquals("ACT", result);
        }

        @Test
        void returnsNullForNullStatus() {
            String result = validator.validateStatusCode(null, Set.of("ACT", "CLO"), "status", "REC-1");
            assertNull(result);
        }

        @Test
        void returnsNullForBlankStatus() {
            String result = validator.validateStatusCode("", Set.of("ACT", "CLO"), "status", "REC-1");
            assertNull(result);
        }

        @Test
        void returnsUnrecognizedStatusWithWarning() {
            String result = validator.validateStatusCode("XYZ", Set.of("ACT", "CLO"), "status", "REC-1");
            assertEquals("XYZ", result);
        }
    }

    @Nested
    class BorrowerValidationTests {

        @Test
        void validBorrowerProducesNoWarnings() {
            LegacyBorrower borrower = createValidBorrower();
            List<String> warnings = validator.validateBorrower(borrower);
            assertFalse(warnings.stream().anyMatch(w -> w.contains("First name") || w.contains("Last name")));
        }

        @Test
        void detectsNullFirstName() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setFirstName(null);
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("First name")));
        }

        @Test
        void detectsNullLastName() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setLastName(null);
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Last name")));
        }

        @Test
        void detectsNullMiddleInitial() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setMiddleInitial(null);
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Middle initial")));
        }

        private LegacyBorrower createValidBorrower() {
            LegacyBorrower b = new LegacyBorrower();
            b.setBorrowerId("B-10001");
            b.setFirstName("James");
            b.setLastName("Mitchell");
            b.setMiddleInitial("R");
            b.setDateOfBirth("03/15/1978");
            b.setCreditScore("745");
            b.setStatusCode("ACT");
            b.setAnnualIncome("92,500");
            b.setCreatedDate("01/15/2019");
            b.setUpdatedDate("11/03/2025");
            return b;
        }
    }

    @Nested
    class LoanAccountValidationTests {

        @Test
        void validLoanAccountProducesNoWarnings() {
            LegacyLoanAccount acct = createValidLoanAccount();
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.isEmpty(), "Expected no warnings, got: " + warnings);
        }

        @Test
        void detectsNullBorrowerId() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setBorrowerId(null);
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Borrower ID")));
        }

        @Test
        void detectsActiveStatusWithDelinquencyDays() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setStatusCode("ACT");
            acct.setDelinquencyDays("15");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("delinquency days")));
        }

        @Test
        void noDelinquencyWarningForClosedLoan() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setStatusCode("CLO");
            acct.setDelinquencyDays("15");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertFalse(warnings.stream().anyMatch(w -> w.contains("delinquency days")));
        }

        @Test
        void detectsCurrentBalanceExceedingOriginalAmount() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setOriginalAmount("100,000");
            acct.setCurrentBalance("150,000");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Current balance exceeds")));
        }

        @Test
        void detectsNullBorrowerFirstName() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setBorrowerFirstName(null);
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("borrower first name")));
        }

        @Test
        void detectsNullBorrowerLastName() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setBorrowerLastName(null);
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("borrower last name")));
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
    }

    @Nested
    class PaymentValidationTests {

        @Test
        void validBalancedPaymentProducesNoWarnings() {
            LegacyPayment pmt = createBalancedPayment();
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.isEmpty(), "Expected no warnings, got: " + warnings);
        }

        @Test
        void detectsPaymentComponentMismatch() {
            LegacyPayment pmt = createBalancedPayment();
            pmt.setTotalAmount("1,487.02");
            pmt.setPrincipalAmount("456.78");
            pmt.setInterestAmount("1,074.69");
            pmt.setEscrowAmount("355.55");
            pmt.setLateFee("0.00");
            // Sum = 1,887.02, total = 1,487.02, difference = 400.00
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("does not equal total")));
        }

        @Test
        void detectsLateFeeExcludedFromTotal() {
            LegacyPayment pmt = createBalancedPayment();
            pmt.setTotalAmount("1,077.05");
            pmt.setPrincipalAmount("295.82");
            pmt.setInterestAmount("781.23");
            pmt.setEscrowAmount("0.00");
            pmt.setLateFee("47.50");
            // Sum = 1,124.55, total = 1,077.05, difference = 47.50
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("does not equal total")));
        }

        @Test
        void detectsNullLoanAccountNumber() {
            LegacyPayment pmt = createBalancedPayment();
            pmt.setLoanAccountNumber(null);
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("orphaned payment")));
        }

        @Test
        void toleratesSmallRoundingDifferences() {
            LegacyPayment pmt = createBalancedPayment();
            // Total = 100.00, components sum to 100.009 (within 0.01 tolerance)
            pmt.setTotalAmount("100.00");
            pmt.setPrincipalAmount("50.003");
            pmt.setInterestAmount("30.003");
            pmt.setEscrowAmount("20.003");
            pmt.setLateFee("0.00");
            List<String> warnings = validator.validatePayment(pmt);
            assertFalse(warnings.stream().anyMatch(w -> w.contains("does not equal total")));
        }

        private LegacyPayment createBalancedPayment() {
            LegacyPayment p = new LegacyPayment();
            p.setPaymentSequenceNumber("PMT-TEST-001");
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
}
