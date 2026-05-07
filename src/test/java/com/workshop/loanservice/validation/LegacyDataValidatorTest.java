package com.workshop.loanservice.validation;

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
    // ANO-001 / ANO-005: Numeric parsing — amounts, decimals, integers
    // =========================================================================

    @Nested
    class AmountParsing {

        @Test
        void parsesCommaFormattedAmount() {
            assertEquals(new BigDecimal("285000"), validator.parseAmount("285,000", "field", "rec1"));
        }

        @Test
        void parsesAmountWithDecimalAndComma() {
            assertEquals(new BigDecimal("271432.56"), validator.parseAmount("271,432.56", "field", "rec1"));
        }

        @Test
        void parsesPlainNumber() {
            assertEquals(new BigDecimal("0"), validator.parseAmount("0", "field", "rec1"));
        }

        @Test
        void stripsCurrencySymbol() {
            assertEquals(new BigDecimal("285000"), validator.parseAmount("$285,000", "field", "rec1"));
        }

        @Test
        void stripsWhitespace() {
            assertEquals(new BigDecimal("285000"), validator.parseAmount(" 285,000 ", "field", "rec1"));
        }

        @Test
        void returnsDefaultForNull() {
            assertEquals(BigDecimal.ZERO, validator.parseAmount(null, "field", "rec1"));
        }

        @Test
        void returnsDefaultForBlank() {
            assertEquals(BigDecimal.ZERO, validator.parseAmount("  ", "field", "rec1"));
        }

        @Test
        void returnsDefaultForNonNumeric() {
            assertEquals(BigDecimal.ZERO, validator.parseAmount("N/A", "field", "rec1"));
        }

        @Test
        void returnsDefaultForTBD() {
            assertEquals(BigDecimal.ZERO, validator.parseAmount("TBD", "field", "rec1"));
        }

        @Test
        void returnsCustomDefault() {
            BigDecimal defaultVal = new BigDecimal("999");
            assertEquals(defaultVal, validator.parseAmount("INVALID", "field", "rec1", defaultVal));
        }

        @Test
        void handlesNegativeAmount() {
            BigDecimal result = validator.parseAmount("-500", "field", "rec1");
            assertEquals(new BigDecimal("-500"), result);
        }
    }

    @Nested
    class DecimalParsing {

        @Test
        void parsesDecimal() {
            assertEquals(new BigDecimal("5.250"), validator.parseDecimal("5.250", "rate", "rec1"));
        }

        @Test
        void returnsDefaultForNull() {
            assertEquals(BigDecimal.ZERO, validator.parseDecimal(null, "rate", "rec1"));
        }

        @Test
        void returnsDefaultForInvalid() {
            assertEquals(BigDecimal.ZERO, validator.parseDecimal("abc", "rate", "rec1"));
        }
    }

    @Nested
    class IntegerParsing {

        @Test
        void parsesValidInteger() {
            assertEquals(15, validator.parseInteger("15", "days", "rec1"));
        }

        @Test
        void parsesWithWhitespace() {
            assertEquals(15, validator.parseInteger(" 15 ", "days", "rec1"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.parseInteger(null, "days", "rec1"));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.parseInteger("", "days", "rec1"));
        }

        @Test
        void returnsNullForNonNumeric() {
            assertNull(validator.parseInteger("N/A", "days", "rec1"));
        }
    }

    // =========================================================================
    // ANO-006: Credit score range validation
    // =========================================================================

    @Nested
    class CreditScoreValidation {

        @Test
        void acceptsValidScore() {
            assertEquals(745, validator.parseCreditScore("745", "B-10001"));
        }

        @Test
        void acceptsMinBoundary() {
            assertEquals(300, validator.parseCreditScore("300", "B-10001"));
        }

        @Test
        void acceptsMaxBoundary() {
            assertEquals(850, validator.parseCreditScore("850", "B-10001"));
        }

        @Test
        void rejectsBelowMin() {
            assertNull(validator.parseCreditScore("299", "B-10001"));
        }

        @Test
        void rejectsAboveMax() {
            assertNull(validator.parseCreditScore("999", "B-10001"));
        }

        @Test
        void rejectsZero() {
            assertNull(validator.parseCreditScore("0", "B-10001"));
        }

        @Test
        void returnsNullForNonNumeric() {
            assertNull(validator.parseCreditScore("N/A", "B-10001"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.parseCreditScore(null, "B-10001"));
        }
    }

    // =========================================================================
    // ANO-002 / ANO-012: Date parsing and format normalization
    // =========================================================================

    @Nested
    class DateParsing {

        @Test
        void parsesMMddyyyySlash() {
            assertEquals("2019-02-15", validator.parseAndFormatDate("02/15/2019", "date", "rec1"));
        }

        @Test
        void parsesSingleDigitMonth() {
            assertEquals("2019-02-15", validator.parseAndFormatDate("2/15/2019", "date", "rec1"));
        }

        @Test
        void parsesIso8601() {
            assertEquals("2025-03-15", validator.parseAndFormatDate("2025-03-15", "date", "rec1"));
        }

        @Test
        void parsesMMddyyyyDash() {
            assertEquals("2019-02-15", validator.parseAndFormatDate("02-15-2019", "date", "rec1"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.parseAndFormatDate(null, "date", "rec1"));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.parseAndFormatDate("  ", "date", "rec1"));
        }

        @Test
        void returnsOriginalForUnparseable() {
            assertEquals("not-a-date", validator.parseAndFormatDate("not-a-date", "date", "rec1"));
        }
    }

    // =========================================================================
    // ANO-009: Status code validation
    // =========================================================================

    @Nested
    class StatusCodeValidation {

        @Test
        void acceptsValidLoanStatus() {
            assertEquals("ACT", validator.validateLoanStatus("ACT", "LN-001"));
        }

        @Test
        void acceptsAllValidLoanStatuses() {
            for (String code : Set.of("ACT", "CLO", "DFT", "FRB")) {
                assertEquals(code, validator.validateLoanStatus(code, "LN-001"));
            }
        }

        @Test
        void returnsUnrecognizedCodeUnchanged() {
            assertEquals("XYZ", validator.validateLoanStatus("XYZ", "LN-001"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.validateLoanStatus(null, "LN-001"));
        }

        @Test
        void trimsWhitespace() {
            assertEquals("ACT", validator.validateLoanStatus(" ACT ", "LN-001"));
        }

        @Test
        void validatesPaymentType() {
            assertEquals("REG", validator.validatePaymentType("REG", "PMT-001"));
            assertEquals("UNKNOWN", validator.validatePaymentType("UNKNOWN", "PMT-001"));
        }

        @Test
        void validatesPaymentStatus() {
            assertEquals("PST", validator.validatePaymentStatus("PST", "PMT-001"));
        }

        @Test
        void validatesPropertyType() {
            assertEquals("SFR", validator.validatePropertyType("SFR", "LN-001"));
            assertEquals("CND", validator.validatePropertyType("CND", "LN-001"));
        }
    }

    // =========================================================================
    // ANO-007: Payment balance reconciliation
    // =========================================================================

    @Nested
    class PaymentBalanceValidation {

        @Test
        void passesWhenBalanced() {
            assertTrue(validator.validatePaymentBalance("PMT-001",
                    new BigDecimal("1000.00"),
                    new BigDecimal("400.00"),
                    new BigDecimal("350.00"),
                    new BigDecimal("200.00"),
                    new BigDecimal("50.00")));
        }

        @Test
        void failsWhenImbalanced() {
            assertFalse(validator.validatePaymentBalance("PMT-001",
                    new BigDecimal("1487.02"),
                    new BigDecimal("456.78"),
                    new BigDecimal("1074.69"),
                    new BigDecimal("355.55"),
                    new BigDecimal("0.00")));
        }

        @Test
        void passesWithAllZeros() {
            assertTrue(validator.validatePaymentBalance("PMT-001",
                    BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO,
                    BigDecimal.ZERO, BigDecimal.ZERO));
        }
    }

    // =========================================================================
    // ANO-010: Delinquency vs status consistency
    // =========================================================================

    @Nested
    class DelinquencyConsistency {

        @Test
        void noWarningForActiveWithZeroDays() {
            // Should not throw
            validator.validateDelinquencyConsistency("LN-001", "ACT", 0);
        }

        @Test
        void warnsForActiveWithDelinquency() {
            // Should log warning but not throw
            validator.validateDelinquencyConsistency("LN-001", "ACT", 15);
        }

        @Test
        void warnsForHighDelinquencyNotDefault() {
            // Should log warning but not throw
            validator.validateDelinquencyConsistency("LN-001", "ACT", 91);
        }

        @Test
        void noWarningForDefaultWithHighDelinquency() {
            validator.validateDelinquencyConsistency("LN-001", "DFT", 120);
        }

        @Test
        void handlesNullDelinquencyDays() {
            // Should not throw
            validator.validateDelinquencyConsistency("LN-001", "ACT", null);
        }
    }

    // =========================================================================
    // ANO-008: LTV cross-validation
    // =========================================================================

    @Nested
    class LtvValidation {

        @Test
        void noWarningWhenLtvMatches() {
            validator.validateLtv("LN-001",
                    new BigDecimal("82.6"),
                    new BigDecimal("285000"),
                    new BigDecimal("345000"));
        }

        @Test
        void warnsWhenLtvDiffersSignificantly() {
            validator.validateLtv("LN-001",
                    new BigDecimal("50.0"),
                    new BigDecimal("285000"),
                    new BigDecimal("345000"));
        }

        @Test
        void handlesNullInputs() {
            validator.validateLtv("LN-001", null, new BigDecimal("285000"), new BigDecimal("345000"));
            validator.validateLtv("LN-001", new BigDecimal("82.6"), null, new BigDecimal("345000"));
            validator.validateLtv("LN-001", new BigDecimal("82.6"), new BigDecimal("285000"), null);
        }

        @Test
        void handlesZeroAppraisedValue() {
            validator.validateLtv("LN-001",
                    new BigDecimal("82.6"),
                    new BigDecimal("285000"),
                    BigDecimal.ZERO);
        }
    }

    // =========================================================================
    // ANO-011: Null-safe address building
    // =========================================================================

    @Nested
    class AddressBuilding {

        @Test
        void buildsFullAddress() {
            assertEquals("123 Main St, Springfield, IL 62704",
                    validator.buildAddress("123 Main St", "Springfield", "IL", "62704"));
        }

        @Test
        void handlesNullCity() {
            assertEquals("123 Main St, IL 62704",
                    validator.buildAddress("123 Main St", null, "IL", "62704"));
        }

        @Test
        void handlesNullState() {
            assertEquals("123 Main St, Springfield 62704",
                    validator.buildAddress("123 Main St", "Springfield", null, "62704"));
        }

        @Test
        void handlesAllNull() {
            assertEquals("Unknown",
                    validator.buildAddress(null, null, null, null));
        }

        @Test
        void handlesBlankFields() {
            assertEquals("Unknown",
                    validator.buildAddress("", "  ", "", ""));
        }

        @Test
        void handlesOnlyAddress() {
            assertEquals("123 Main St",
                    validator.buildAddress("123 Main St", null, null, null));
        }
    }
}
