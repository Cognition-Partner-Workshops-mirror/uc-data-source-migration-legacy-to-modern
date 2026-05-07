package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // ANM-002: Numeric String Parsing
    // =========================================================================

    @Nested
    class ParseAmountTests {

        @Test
        void parsesCommaFormattedAmount() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount("285,000", "testField", warnings);
            assertEquals(new BigDecimal("285000"), result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void parsesDecimalAmountWithCommas() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount("1,487.02", "testField", warnings);
            assertEquals(new BigDecimal("1487.02"), result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void returnsNullAndWarnsForNullAmount() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount(null, "testField", warnings);
            assertNull(result);
            assertEquals(1, warnings.size());
            assertEquals("HIGH", warnings.get(0).getSeverity());
            assertTrue(warnings.get(0).getMessage().contains("null"));
        }

        @Test
        void returnsNullAndWarnsForBlankAmount() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount("  ", "testField", warnings);
            assertNull(result);
            assertEquals(1, warnings.size());
            assertEquals("HIGH", warnings.get(0).getSeverity());
        }

        @Test
        void handlesUnparseableAmountWithCurrencySymbol() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount("$285,000", "testField", warnings);
            assertEquals(new BigDecimal("285000"), result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void handlesAlphabeticInput() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount("N/A", "testField", warnings);
            assertNull(result);
            assertEquals(1, warnings.size());
            assertEquals("CRITICAL", warnings.get(0).getSeverity());
            assertTrue(warnings.get(0).getMessage().contains("Unparseable"));
        }

        @Test
        void handlesParenthesesNegativeNotation() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount("(1,487.02)", "testField", warnings);
            assertEquals(new BigDecimal("-1487.02"), result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void parsesZeroAmount() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount("0.00", "testField", warnings);
            assertEquals(new BigDecimal("0.00"), result);
            assertTrue(warnings.isEmpty());
        }
    }

    @Nested
    class ParseDecimalTests {

        @Test
        void parsesDecimalValue() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseDecimal("4.750", "interestRate", warnings);
            assertEquals(new BigDecimal("4.750"), result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void returnsNullForNullDecimal() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseDecimal(null, "interestRate", warnings);
            assertNull(result);
            assertEquals(1, warnings.size());
        }

        @Test
        void handlesUnparseableDecimal() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseDecimal("VARIABLE", "interestRate", warnings);
            assertNull(result);
            assertEquals(1, warnings.size());
            assertEquals("CRITICAL", warnings.get(0).getSeverity());
        }
    }

    @Nested
    class ParseIntegerTests {

        @Test
        void parsesIntegerString() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            Integer result = validator.parseInteger("745", "creditScore", warnings);
            assertEquals(745, result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void returnsNullForNullInteger() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            Integer result = validator.parseInteger(null, "creditScore", warnings);
            assertNull(result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void handlesDecimalStringByTruncating() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            Integer result = validator.parseInteger("745.0", "creditScore", warnings);
            assertEquals(745, result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void handlesUnparseableInteger() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            Integer result = validator.parseInteger("N/A", "creditScore", warnings);
            assertNull(result);
            assertEquals(1, warnings.size());
            assertEquals("CRITICAL", warnings.get(0).getSeverity());
        }

        @Test
        void handlesCommaFormattedInteger() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            Integer result = validator.parseInteger("1,200", "termMonths", warnings);
            assertEquals(1200, result);
            assertTrue(warnings.isEmpty());
        }
    }

    // =========================================================================
    // ANM-004: Date Format Validation
    // =========================================================================

    @Nested
    class ParseDateTests {

        @Test
        void parsesValidLegacyDate() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.parseDate("03/15/1978", "dateOfBirth", warnings);
            assertEquals("1978-03-15", result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void returnsNullForNullDate() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.parseDate(null, "dateOfBirth", warnings);
            assertNull(result);
        }

        @Test
        void warnsForInvalidDateFormat() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.parseDate("2025-12-01", "originationDate", warnings);
            assertNotNull(result);
            assertEquals(1, warnings.size());
            assertEquals("HIGH", warnings.get(0).getSeverity());
            assertTrue(warnings.get(0).getMessage().contains("Invalid date format"));
        }

        @Test
        void warnsForImpossibleDate() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.parseDate("00/15/2025", "paymentDate", warnings);
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).getMessage().contains("Invalid date format"));
        }

        @Test
        void warnsForInvalidMonth() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.parseDate("13/01/2025", "paymentDate", warnings);
            assertEquals(1, warnings.size());
        }
    }

    // =========================================================================
    // ANM-008: Status Code Validation
    // =========================================================================

    @Nested
    class StatusCodeValidationTests {

        @Test
        void acceptsValidLoanStatus() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.validateStatusCode("ACT",
                    validator.getValidLoanStatuses(), "loanStatus", warnings);
            assertEquals("ACT", result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void warnsForUnknownLoanStatus() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.validateStatusCode("XYZ",
                    validator.getValidLoanStatuses(), "loanStatus", warnings);
            assertEquals("XYZ", result);
            assertEquals(1, warnings.size());
            assertEquals("MEDIUM", warnings.get(0).getSeverity());
            assertTrue(warnings.get(0).getMessage().contains("Unrecognized"));
        }

        @Test
        void warnsForNullStatus() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.validateStatusCode(null,
                    validator.getValidLoanStatuses(), "loanStatus", warnings);
            assertNull(result);
            assertEquals(1, warnings.size());
            assertEquals("HIGH", warnings.get(0).getSeverity());
        }

        @Test
        void acceptsValidPaymentStatuses() {
            for (String code : List.of("PST", "REV", "NSF", "PND")) {
                List<DataQualityWarning> warnings = new ArrayList<>();
                String result = validator.validateStatusCode(code,
                        validator.getValidPaymentStatuses(), "paymentStatus", warnings);
                assertEquals(code, result);
                assertTrue(warnings.isEmpty(), "Unexpected warning for valid status: " + code);
            }
        }

        @Test
        void acceptsValidPaymentTypes() {
            for (String code : List.of("REG", "EXT", "PRT", "PRE")) {
                List<DataQualityWarning> warnings = new ArrayList<>();
                String result = validator.validateStatusCode(code,
                        validator.getValidPaymentTypes(), "paymentType", warnings);
                assertEquals(code, result);
                assertTrue(warnings.isEmpty());
            }
        }
    }

    // =========================================================================
    // ANM-001: Payment Component Validation
    // =========================================================================

    @Nested
    class PaymentComponentValidationTests {

        @Test
        void detectsMismatchBetweenComponentsAndTotal() {
            BigDecimal total = new BigDecimal("1487.02");
            BigDecimal principal = new BigDecimal("456.78");
            BigDecimal interest = new BigDecimal("1074.69");
            BigDecimal escrow = new BigDecimal("355.55");
            BigDecimal late = BigDecimal.ZERO;

            List<DataQualityWarning> warnings =
                    validator.validatePaymentComponents(total, principal, interest, escrow, late);

            assertEquals(1, warnings.size());
            assertEquals("CRITICAL", warnings.get(0).getSeverity());
            assertTrue(warnings.get(0).getMessage().contains("does not match total"));
        }

        @Test
        void passesWhenComponentsMatchTotal() {
            BigDecimal total = new BigDecimal("2924.18");
            BigDecimal principal = new BigDecimal("1842.56");
            BigDecimal interest = new BigDecimal("815.50");
            BigDecimal escrow = new BigDecimal("266.12");
            BigDecimal late = BigDecimal.ZERO;

            List<DataQualityWarning> warnings =
                    validator.validatePaymentComponents(total, principal, interest, escrow, late);

            assertTrue(warnings.isEmpty());
        }

        @Test
        void skipsValidationWhenTotalIsNull() {
            List<DataQualityWarning> warnings =
                    validator.validatePaymentComponents(null, BigDecimal.ONE, BigDecimal.ONE, null, null);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void handlesNullEscrowAndLateFee() {
            BigDecimal total = new BigDecimal("100.00");
            BigDecimal principal = new BigDecimal("60.00");
            BigDecimal interest = new BigDecimal("40.00");

            List<DataQualityWarning> warnings =
                    validator.validatePaymentComponents(total, principal, interest, null, null);

            assertTrue(warnings.isEmpty());
        }
    }

    // =========================================================================
    // ANM-005: Required Field Validation
    // =========================================================================

    @Nested
    class RequiredFieldValidationTests {

        @Test
        void warnsForNullRequiredField() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validateRequiredString(null, "firstName", warnings);
            assertEquals(1, warnings.size());
            assertEquals("CRITICAL", warnings.get(0).getSeverity());
        }

        @Test
        void warnsForBlankRequiredField() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validateRequiredString("  ", "firstName", warnings);
            assertEquals(1, warnings.size());
        }

        @Test
        void noWarningForPresentField() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validateRequiredString("James", "firstName", warnings);
            assertTrue(warnings.isEmpty());
        }
    }

    // =========================================================================
    // ANM-003: Orphaned Record Detection (via Borrower Validation)
    // =========================================================================

    @Nested
    class BorrowerValidationTests {

        @Test
        void validBorrowerProducesNoWarnings() {
            LegacyBorrower borrower = createValidBorrower();
            List<DataQualityWarning> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void detectsNullFirstName() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setFirstName(null);
            List<DataQualityWarning> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w ->
                    w.getField().equals("firstName") && w.getSeverity().equals("CRITICAL")));
        }

        @Test
        void detectsNullLastName() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setLastName(null);
            List<DataQualityWarning> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w ->
                    w.getField().equals("lastName") && w.getSeverity().equals("CRITICAL")));
        }

        @Test
        void detectsInvalidCreditScoreRange() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("200");
            List<DataQualityWarning> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w ->
                    w.getField().equals("creditScore") && w.getMessage().contains("out of valid range")));
        }

        @Test
        void detectsInvalidBorrowerStatus() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setStatusCode("XYZ");
            List<DataQualityWarning> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w ->
                    w.getField().equals("borrowerStatusCode")));
        }

        private LegacyBorrower createValidBorrower() {
            LegacyBorrower b = new LegacyBorrower();
            b.setBorrowerId("B-10001");
            b.setFirstName("James");
            b.setLastName("Mitchell");
            b.setEmail("j.mitchell@email.com");
            b.setCreditScore("745");
            b.setStatusCode("ACT");
            return b;
        }
    }

    // =========================================================================
    // ANM-003: Loan Account Validation
    // =========================================================================

    @Nested
    class LoanAccountValidationTests {

        @Test
        void validLoanAccountProducesNoWarnings() {
            LegacyLoanAccount acct = createValidLoanAccount();
            List<DataQualityWarning> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void detectsNullBorrowerId() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setBorrowerId(null);
            List<DataQualityWarning> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w ->
                    w.getField().equals("borrowerId") && w.getSeverity().equals("CRITICAL")));
        }

        @Test
        void detectsInvalidLoanStatus() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setStatusCode("INVALID");
            List<DataQualityWarning> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w ->
                    w.getField().equals("loanStatusCode")));
        }

        @Test
        void detectsInvalidPropertyType() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setPropertyType("MANSION");
            List<DataQualityWarning> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w ->
                    w.getField().equals("propertyType")));
        }

        private LegacyLoanAccount createValidLoanAccount() {
            LegacyLoanAccount a = new LegacyLoanAccount();
            a.setLoanAccountNumber("LN-2019-00142");
            a.setBorrowerId("B-10001");
            a.setProductCode("FXD30");
            a.setStatusCode("ACT");
            a.setPropertyType("SFR");
            return a;
        }
    }

    // =========================================================================
    // ANM-006: Denormalized Data Drift Detection
    // =========================================================================

    @Nested
    class DenormalizedDataValidationTests {

        @Test
        void noWarningsWhenDataMatches() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setBorrowerFirstName("James");
            acct.setBorrowerLastName("Mitchell");

            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setFirstName("James");
            borrower.setLastName("Mitchell");

            List<DataQualityWarning> warnings =
                    validator.validateDenormalizedBorrowerData(acct, borrower);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void detectsFirstNameMismatch() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setBorrowerFirstName("Jim");
            acct.setBorrowerLastName("Mitchell");

            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setFirstName("James");
            borrower.setLastName("Mitchell");

            List<DataQualityWarning> warnings =
                    validator.validateDenormalizedBorrowerData(acct, borrower);
            assertEquals(1, warnings.size());
            assertEquals("HIGH", warnings.get(0).getSeverity());
            assertTrue(warnings.get(0).getMessage().contains("mismatch"));
        }

        @Test
        void detectsLastNameMismatch() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setBorrowerFirstName("James");
            acct.setBorrowerLastName("Smith");

            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setFirstName("James");
            borrower.setLastName("Mitchell");

            List<DataQualityWarning> warnings =
                    validator.validateDenormalizedBorrowerData(acct, borrower);
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).getMessage().contains("mismatch"));
        }

        @Test
        void detectsOrphanedBorrower() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setBorrowerId("B-99999");

            List<DataQualityWarning> warnings =
                    validator.validateDenormalizedBorrowerData(acct, null);
            assertEquals(1, warnings.size());
            assertEquals("CRITICAL", warnings.get(0).getSeverity());
            assertTrue(warnings.get(0).getMessage().contains("Orphaned"));
        }
    }

    // =========================================================================
    // ANM-009: Payment Date Ordering Validation
    // =========================================================================

    @Nested
    class PaymentDateValidationTests {

        @Test
        void noWarningForValidDateOrdering() {
            List<DataQualityWarning> warnings =
                    validator.validatePaymentDates("12/01/2025", "11/30/2025", "12/01/2025");
            assertTrue(warnings.isEmpty());
        }

        @Test
        void warnsWhenReceivedAfterProcessed() {
            List<DataQualityWarning> warnings =
                    validator.validatePaymentDates("12/01/2025", "12/05/2025", "12/03/2025");
            assertEquals(1, warnings.size());
            assertEquals("MEDIUM", warnings.get(0).getSeverity());
            assertTrue(warnings.get(0).getMessage().contains("after processed"));
        }

        @Test
        void handlesNullDatesGracefully() {
            List<DataQualityWarning> warnings =
                    validator.validatePaymentDates(null, null, null);
            assertTrue(warnings.isEmpty());
        }
    }

    // =========================================================================
    // ANM-001: Payment Validation (full entity)
    // =========================================================================

    @Nested
    class PaymentEntityValidationTests {

        @Test
        void validPaymentProducesNoWarnings() {
            LegacyPayment pmt = createValidPayment();
            List<DataQualityWarning> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void detectsInvalidPaymentStatus() {
            LegacyPayment pmt = createValidPayment();
            pmt.setStatusCode("BAD");
            List<DataQualityWarning> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w ->
                    w.getField().equals("paymentStatusCode")));
        }

        @Test
        void detectsInvalidPaymentType() {
            LegacyPayment pmt = createValidPayment();
            pmt.setTypeCode("UNKNOWN");
            List<DataQualityWarning> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w ->
                    w.getField().equals("paymentTypeCode")));
        }

        private LegacyPayment createValidPayment() {
            LegacyPayment p = new LegacyPayment();
            p.setPaymentSequenceNumber("PMT-001");
            p.setLoanAccountNumber("LN-2019-00142");
            p.setStatusCode("PST");
            p.setTypeCode("REG");
            return p;
        }
    }
}
