package com.workshop.loanservice.validation;

import com.workshop.loanservice.validation.DataQualityValidator.Severity;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

class DataQualityValidatorTest {

    private DataQualityValidator validator;

    @BeforeEach
    void setUp() {
        validator = new DataQualityValidator();
    }

    // =========================================================================
    // ANM-001: Numeric Amounts as Comma-Formatted Strings
    // =========================================================================

    @Nested
    @DisplayName("ANM-001: Amount Parsing")
    class AmountParsing {

        @Test
        void parsesAmountWithCommas() {
            BigDecimal result = validator.parseAmount("285,000", "testField");
            assertEquals(new BigDecimal("285000"), result);
            assertFalse(validator.hasErrors());
        }

        @Test
        void parsesAmountWithCommasAndDecimals() {
            BigDecimal result = validator.parseAmount("1,487.02", "testField");
            assertEquals(new BigDecimal("1487.02"), result);
        }

        @Test
        void parsesAmountWithDollarSign() {
            BigDecimal result = validator.parseAmount("$92,500", "testField");
            assertEquals(new BigDecimal("92500"), result);
        }

        @Test
        void returnsNullForNullAmount() {
            BigDecimal result = validator.parseAmount(null, "testField");
            assertNull(result);
            assertTrue(validator.hasErrors());
        }

        @Test
        void returnsNullForBlankAmount() {
            BigDecimal result = validator.parseAmount("", "testField");
            assertNull(result);
            assertTrue(validator.hasErrors());
        }

        @Test
        void returnsNullForUnparseableAmount() {
            BigDecimal result = validator.parseAmount("N/A", "testField");
            assertNull(result);
            assertEquals(1, validator.countBySeverity(Severity.CRITICAL));
        }

        @Test
        void parseAmountWithDefaultReturnsDefaultForNull() {
            BigDecimal result = validator.parseAmountWithDefault(null, "testField", BigDecimal.ZERO);
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void parseAmountWithDefaultReturnsValueWhenValid() {
            BigDecimal result = validator.parseAmountWithDefault("100,000", "testField", BigDecimal.ZERO);
            assertEquals(new BigDecimal("100000"), result);
        }
    }

    // =========================================================================
    // ANM-001: Decimal Parsing (interest rate, LTV)
    // =========================================================================

    @Nested
    @DisplayName("ANM-001: Decimal Parsing")
    class DecimalParsing {

        @Test
        void parsesDecimalWithCommas() {
            BigDecimal result = validator.parseDecimal("1,234.56", "testField");
            assertEquals(new BigDecimal("1234.56"), result);
        }

        @Test
        void parsesCleanDecimal() {
            BigDecimal result = validator.parseDecimal("4.750", "testField");
            assertEquals(new BigDecimal("4.750"), result);
        }

        @Test
        void returnsNullForUnparseableDecimal() {
            BigDecimal result = validator.parseDecimal("TBD", "testField");
            assertNull(result);
            assertEquals(1, validator.countBySeverity(Severity.CRITICAL));
        }
    }

    // =========================================================================
    // ANM-001: Integer Parsing
    // =========================================================================

    @Nested
    @DisplayName("ANM-001: Integer Parsing")
    class IntegerParsing {

        @Test
        void parsesValidInteger() {
            Integer result = validator.parseInteger("360", "testField");
            assertEquals(360, result);
        }

        @Test
        void parsesIntegerWithCommas() {
            Integer result = validator.parseInteger("1,000", "testField");
            assertEquals(1000, result);
        }

        @Test
        void returnsNullForNonNumericInteger() {
            Integer result = validator.parseInteger("ABC", "testField");
            assertNull(result);
            assertTrue(validator.hasErrors());
        }

        @Test
        void returnsNullForNullInteger() {
            Integer result = validator.parseInteger(null, "testField");
            assertNull(result);
        }
    }

    // =========================================================================
    // ANM-002: Date Format Validation
    // =========================================================================

    @Nested
    @DisplayName("ANM-002: Date Parsing")
    class DateParsing {

        @Test
        void parsesValidLegacyDate() {
            LocalDate result = validator.parseDate("03/15/1978", "testField");
            assertEquals(LocalDate.of(1978, 3, 15), result);
            assertFalse(validator.hasErrors());
        }

        @Test
        void parsesEndOfMonthDate() {
            LocalDate result = validator.parseDate("02/28/1990", "testField");
            assertEquals(LocalDate.of(1990, 2, 28), result);
        }

        @Test
        void returnsNullForWrongFormat() {
            LocalDate result = validator.parseDate("1978-03-15", "testField");
            assertNull(result);
            assertEquals(1, validator.countBySeverity(Severity.CRITICAL));
        }

        @Test
        void returnsNullForGarbageDate() {
            LocalDate result = validator.parseDate("NOT_A_DATE", "testField");
            assertNull(result);
            assertEquals(1, validator.countBySeverity(Severity.CRITICAL));
        }

        @Test
        void returnsNullForNullDate() {
            LocalDate result = validator.parseDate(null, "testField");
            assertNull(result);
        }

        @Test
        void returnsNullForBlankDate() {
            LocalDate result = validator.parseDate("   ", "testField");
            assertNull(result);
        }
    }

    // =========================================================================
    // ANM-003: Foreign Key Validation
    // =========================================================================

    @Nested
    @DisplayName("ANM-003: Foreign Key Validation")
    class ForeignKeyValidation {

        @Test
        void validForeignKeyPasses() {
            Set<String> validIds = Set.of("B-10001", "B-10002", "B-10003");
            assertTrue(validator.validateForeignKey("B-10001", validIds, "BORR_ID", "CDW_BORR_MSTR"));
            assertFalse(validator.hasErrors());
        }

        @Test
        void orphanedForeignKeyFails() {
            Set<String> validIds = Set.of("B-10001", "B-10002");
            assertFalse(validator.validateForeignKey("B-99999", validIds, "BORR_ID", "CDW_BORR_MSTR"));
            assertEquals(1, validator.countBySeverity(Severity.CRITICAL));
        }

        @Test
        void nullForeignKeyFails() {
            Set<String> validIds = Set.of("B-10001");
            assertFalse(validator.validateForeignKey(null, validIds, "BORR_ID", "CDW_BORR_MSTR"));
            assertEquals(1, validator.countBySeverity(Severity.CRITICAL));
        }
    }

    // =========================================================================
    // ANM-004: Credit Score Validation
    // =========================================================================

    @Nested
    @DisplayName("ANM-004: Credit Score Validation")
    class CreditScoreValidation {

        @Test
        void validCreditScorePasses() {
            Integer score = validator.validateCreditScore("745");
            assertEquals(745, score);
            assertFalse(validator.hasErrors());
        }

        @Test
        void minimumCreditScorePasses() {
            Integer score = validator.validateCreditScore("300");
            assertEquals(300, score);
        }

        @Test
        void maximumCreditScorePasses() {
            Integer score = validator.validateCreditScore("850");
            assertEquals(850, score);
        }

        @Test
        void belowMinCreditScoreReturnsNull() {
            Integer score = validator.validateCreditScore("100");
            assertNull(score);
            assertTrue(validator.hasErrors());
        }

        @Test
        void aboveMaxCreditScoreReturnsNull() {
            Integer score = validator.validateCreditScore("9999");
            assertNull(score);
            assertTrue(validator.hasErrors());
        }

        @Test
        void nonNumericCreditScoreReturnsNull() {
            Integer score = validator.validateCreditScore("N/A");
            assertNull(score);
            assertTrue(validator.hasErrors());
        }

        @Test
        void nullCreditScoreReturnsNull() {
            Integer score = validator.validateCreditScore(null);
            assertNull(score);
        }
    }

    // =========================================================================
    // ANM-005: Required Field Validation
    // =========================================================================

    @Nested
    @DisplayName("ANM-005: Required Field Validation")
    class RequiredFieldValidation {

        @Test
        void nonNullRequiredFieldPasses() {
            String result = validator.validateRequired("James", "firstName");
            assertEquals("James", result);
            assertFalse(validator.hasErrors());
        }

        @Test
        void nullRequiredFieldReturnsNull() {
            String result = validator.validateRequired(null, "firstName");
            assertNull(result);
            assertTrue(validator.hasErrors());
        }

        @Test
        void blankRequiredFieldReturnsNull() {
            String result = validator.validateRequired("   ", "firstName");
            assertNull(result);
            assertTrue(validator.hasErrors());
        }

        @Test
        void requiredWithDefaultReturnsDefault() {
            String result = validator.validateRequiredWithDefault(null, "firstName", "UNKNOWN");
            assertEquals("UNKNOWN", result);
        }
    }

    // =========================================================================
    // ANM-005: Safe String Concatenation
    // =========================================================================

    @Nested
    @DisplayName("ANM-005: Safe Concatenation")
    class SafeConcatenation {

        @Test
        void concatenatesNonNullParts() {
            String result = validator.safeConcat(" ", "James", "R.", "Mitchell");
            assertEquals("James R. Mitchell", result);
        }

        @Test
        void skipsNullParts() {
            String result = validator.safeConcat(" ", "Robert", null, "Williams");
            assertEquals("Robert Williams", result);
        }

        @Test
        void skipsBlankParts() {
            String result = validator.safeConcat(", ", "742 Elm Street", "Springfield", "IL 62701");
            assertEquals("742 Elm Street, Springfield, IL 62701", result);
        }

        @Test
        void handlesAllNulls() {
            String result = validator.safeConcat(" ", null, null, null);
            assertEquals("", result);
        }
    }

    // =========================================================================
    // ANM-007: Interest Rate and LTV Bounds Validation
    // =========================================================================

    @Nested
    @DisplayName("ANM-007: Interest Rate Validation")
    class InterestRateValidation {

        @Test
        void validInterestRatePasses() {
            BigDecimal rate = validator.validateInterestRate("4.750");
            assertEquals(new BigDecimal("4.750"), rate);
            assertFalse(validator.hasErrors());
        }

        @Test
        void zeroInterestRatePasses() {
            BigDecimal rate = validator.validateInterestRate("0");
            assertEquals(BigDecimal.ZERO, rate);
        }

        @Test
        void negativeInterestRateReturnsNull() {
            BigDecimal rate = validator.validateInterestRate("-5.0");
            assertNull(rate);
            assertTrue(validator.hasErrors());
        }

        @Test
        void absurdInterestRateReturnsNull() {
            BigDecimal rate = validator.validateInterestRate("999.99");
            assertNull(rate);
            assertTrue(validator.hasErrors());
        }
    }

    @Nested
    @DisplayName("ANM-007: LTV Validation")
    class LtvValidation {

        @Test
        void validLtvPasses() {
            BigDecimal ltv = validator.validateLtvPercent("82.5");
            assertEquals(new BigDecimal("82.5"), ltv);
        }

        @Test
        void negativeLtvReturnsNull() {
            BigDecimal ltv = validator.validateLtvPercent("-10.0");
            assertNull(ltv);
        }

        @Test
        void extremeLtvReturnsNull() {
            BigDecimal ltv = validator.validateLtvPercent("250.0");
            assertNull(ltv);
        }
    }

    // =========================================================================
    // ANM-008: Status Code Validation
    // =========================================================================

    @Nested
    @DisplayName("ANM-008: Status Code Validation")
    class StatusCodeValidation {

        @Test
        void validLoanStatusPasses() {
            String status = validator.validateLoanStatusCode("ACT");
            assertEquals("ACT", status);
            assertFalse(validator.hasErrors());
        }

        @Test
        void caseInsensitiveStatusPasses() {
            String status = validator.validateLoanStatusCode("act");
            assertEquals("ACT", status);
        }

        @Test
        void invalidStatusReturnsUnknown() {
            String status = validator.validateLoanStatusCode("XYZ");
            assertEquals("UNKNOWN", status);
        }

        @Test
        void nullStatusReturnsUnknown() {
            String status = validator.validateLoanStatusCode(null);
            assertEquals("UNKNOWN", status);
        }

        @Test
        void validPaymentStatusPasses() {
            assertEquals("PST", validator.validatePaymentStatusCode("PST"));
            assertEquals("REV", validator.validatePaymentStatusCode("REV"));
            assertEquals("NSF", validator.validatePaymentStatusCode("NSF"));
            assertEquals("PND", validator.validatePaymentStatusCode("PND"));
        }

        @Test
        void validPaymentTypePasses() {
            assertEquals("REG", validator.validatePaymentTypeCode("REG"));
            assertEquals("EXT", validator.validatePaymentTypeCode("EXT"));
            assertEquals("PRT", validator.validatePaymentTypeCode("PRT"));
            assertEquals("PRE", validator.validatePaymentTypeCode("PRE"));
        }

        @Test
        void validPropertyTypePasses() {
            assertEquals("SFR", validator.validatePropertyTypeCode("SFR"));
            assertEquals("CND", validator.validatePropertyTypeCode("CND"));
            assertEquals("MFR", validator.validatePropertyTypeCode("MFR"));
            assertEquals("TWN", validator.validatePropertyTypeCode("TWN"));
        }
    }

    // =========================================================================
    // ANM-009: Payment Component Validation
    // =========================================================================

    @Nested
    @DisplayName("ANM-009: Payment Component Validation")
    class PaymentComponentValidation {

        @Test
        void matchingComponentsPass() {
            boolean result = validator.validatePaymentComponents(
                    new BigDecimal("2924.18"),
                    new BigDecimal("1842.56"),
                    new BigDecimal("815.50"),
                    new BigDecimal("266.12"),
                    new BigDecimal("0.00"),
                    "PMT-TEST");
            assertTrue(result);
            assertFalse(validator.hasErrors());
        }

        @Test
        void mismatchedComponentsFail() {
            boolean result = validator.validatePaymentComponents(
                    new BigDecimal("1487.02"),
                    new BigDecimal("456.78"),
                    new BigDecimal("1074.69"),
                    new BigDecimal("355.55"),
                    new BigDecimal("0.00"),
                    "PMT-MISMATCH");
            assertFalse(result);
            assertEquals(1, validator.countBySeverity(Severity.MEDIUM));
        }

        @Test
        void nullComponentsSkipValidation() {
            boolean result = validator.validatePaymentComponents(
                    null, null, null, null, null, "PMT-NULL");
            assertTrue(result);
        }
    }

    // =========================================================================
    // ANM-010: Payment Date Order Validation
    // =========================================================================

    @Nested
    @DisplayName("ANM-010: Payment Date Order")
    class PaymentDateOrderValidation {

        @Test
        void onTimePaymentPasses() {
            boolean result = validator.validatePaymentDateOrder(
                    LocalDate.of(2025, 12, 1),
                    LocalDate.of(2025, 11, 30),
                    "PMT-ONTIME");
            assertTrue(result);
        }

        @Test
        void significantlyLatePaymentFails() {
            boolean result = validator.validatePaymentDateOrder(
                    LocalDate.of(2025, 11, 1),
                    LocalDate.of(2025, 11, 18),
                    "PMT-LATE");
            assertFalse(result);
            assertEquals(1, validator.countBySeverity(Severity.MEDIUM));
        }

        @Test
        void nullDatesSkipValidation() {
            boolean result = validator.validatePaymentDateOrder(null, null, "PMT-NULL");
            assertTrue(result);
        }
    }

    // =========================================================================
    // Validator State Management
    // =========================================================================

    @Nested
    @DisplayName("Validator State")
    class ValidatorState {

        @Test
        void clearResultsResetsState() {
            validator.parseAmount("GARBAGE", "testField");
            assertTrue(validator.hasErrors());
            validator.clearResults();
            assertFalse(validator.hasErrors());
            assertEquals(0, validator.getValidationResults().size());
        }

        @Test
        void countBySeverityIsAccurate() {
            validator.parseAmount(null, "f1");        // HIGH
            validator.parseAmount("BAD", "f2");       // CRITICAL
            validator.validateLoanStatusCode("XYZ");  // MEDIUM
            assertEquals(1, validator.countBySeverity(Severity.CRITICAL));
            assertEquals(1, validator.countBySeverity(Severity.HIGH));
            assertEquals(1, validator.countBySeverity(Severity.MEDIUM));
        }
    }
}
