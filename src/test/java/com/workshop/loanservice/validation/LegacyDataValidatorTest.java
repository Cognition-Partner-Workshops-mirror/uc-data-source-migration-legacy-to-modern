package com.workshop.loanservice.validation;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    @Nested
    @DisplayName("parseAmount - Numeric string parsing with error handling")
    class ParseAmountTests {

        @Test
        @DisplayName("parses amount with commas")
        void parsesAmountWithCommas() {
            BigDecimal result = validator.parseAmount("285,000", "LN_ORIG_AMT", "LN-001");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        @DisplayName("parses amount with commas and decimals")
        void parsesAmountWithCommasAndDecimals() {
            BigDecimal result = validator.parseAmount("271,432.56", "LN_CURR_BAL", "LN-001");
            assertEquals(new BigDecimal("271432.56"), result);
        }

        @Test
        @DisplayName("returns ZERO for null input")
        void returnsZeroForNull() {
            BigDecimal result = validator.parseAmount(null, "LN_ORIG_AMT", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("returns ZERO for blank input")
        void returnsZeroForBlank() {
            BigDecimal result = validator.parseAmount("   ", "LN_ORIG_AMT", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("returns ZERO for non-numeric string like 'N/A'")
        void returnsZeroForNonNumeric() {
            BigDecimal result = validator.parseAmount("N/A", "LN_ORIG_AMT", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("returns ZERO for text value 'PENDING'")
        void returnsZeroForTextValue() {
            BigDecimal result = validator.parseAmount("PENDING", "LN_CURR_BAL", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("strips dollar sign and parses correctly")
        void stripsDollarSign() {
            BigDecimal result = validator.parseAmount("$285,000", "LN_ORIG_AMT", "LN-001");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        @DisplayName("handles value '0'")
        void handlesZeroString() {
            BigDecimal result = validator.parseAmount("0", "PMT_LATE_FEE", "PMT-001");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("handles value '0.00'")
        void handlesZeroDecimalString() {
            BigDecimal result = validator.parseAmount("0.00", "PMT_LATE_FEE", "PMT-001");
            assertEquals(new BigDecimal("0.00"), result);
        }
    }

    @Nested
    @DisplayName("parseDecimal - Decimal string parsing")
    class ParseDecimalTests {

        @Test
        @DisplayName("parses clean decimal")
        void parsesCleanDecimal() {
            BigDecimal result = validator.parseDecimal("4.750", "LN_INT_RT", "LN-001");
            assertEquals(new BigDecimal("4.750"), result);
        }

        @Test
        @DisplayName("parses decimal with whitespace")
        void parsesWithWhitespace() {
            BigDecimal result = validator.parseDecimal("  3.125  ", "LN_INT_RT", "LN-001");
            assertEquals(new BigDecimal("3.125"), result);
        }

        @Test
        @DisplayName("returns ZERO for invalid decimal")
        void returnsZeroForInvalid() {
            BigDecimal result = validator.parseDecimal("abc", "LN_INT_RT", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("returns ZERO for null")
        void returnsZeroForNull() {
            BigDecimal result = validator.parseDecimal(null, "LN_INT_RT", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }
    }

    @Nested
    @DisplayName("parseInteger - Integer string parsing")
    class ParseIntegerTests {

        @Test
        @DisplayName("parses clean integer")
        void parsesCleanInteger() {
            Integer result = validator.parseInteger("745", "BORR_CRDT_SCR", "B-001");
            assertEquals(745, result);
        }

        @Test
        @DisplayName("returns null for null input")
        void returnsNullForNull() {
            Integer result = validator.parseInteger(null, "BORR_CRDT_SCR", "B-001");
            assertNull(result);
        }

        @Test
        @DisplayName("returns null for blank input")
        void returnsNullForBlank() {
            Integer result = validator.parseInteger("", "BORR_CRDT_SCR", "B-001");
            assertNull(result);
        }

        @Test
        @DisplayName("returns null for non-numeric text")
        void returnsNullForNonNumeric() {
            Integer result = validator.parseInteger("HIGH", "BORR_CRDT_SCR", "B-001");
            assertNull(result);
        }

        @Test
        @DisplayName("handles decimal string by truncating")
        void handlesDecimalString() {
            Integer result = validator.parseInteger("745.0", "BORR_CRDT_SCR", "B-001");
            assertEquals(745, result);
        }

        @Test
        @DisplayName("handles comma-separated integer")
        void handlesCommaSeparated() {
            Integer result = validator.parseInteger("1,000", "LN_DLQ_DAYS", "LN-001");
            assertEquals(1000, result);
        }
    }

    @Nested
    @DisplayName("parseDate - Date format validation")
    class ParseDateTests {

        @Test
        @DisplayName("parses valid MM/DD/YYYY date")
        void parsesValidDate() {
            String result = validator.parseDate("03/15/1978", "BORR_DOB_DT", "B-001");
            assertEquals("1978-03-15", result);
        }

        @Test
        @DisplayName("returns null for invalid date like 13/15/2025")
        void returnsNullForInvalidMonth() {
            String result = validator.parseDate("13/15/2025", "BORR_DOB_DT", "B-001");
            assertNull(result);
        }

        @Test
        @DisplayName("returns null for invalid date like 02/30/2020")
        void returnsNullForInvalidDay() {
            String result = validator.parseDate("02/30/2020", "BORR_DOB_DT", "B-001");
            assertNull(result);
        }

        @Test
        @DisplayName("returns null for wrong format (ISO)")
        void returnsNullForIsoFormat() {
            String result = validator.parseDate("2020-03-15", "BORR_DOB_DT", "B-001");
            assertNull(result);
        }

        @Test
        @DisplayName("returns null for null input")
        void returnsNullForNull() {
            String result = validator.parseDate(null, "BORR_DOB_DT", "B-001");
            assertNull(result);
        }

        @Test
        @DisplayName("returns null for blank input")
        void returnsNullForBlank() {
            String result = validator.parseDate("", "BORR_DOB_DT", "B-001");
            assertNull(result);
        }

        @Test
        @DisplayName("returns null for partial date")
        void returnsNullForPartialDate() {
            String result = validator.parseDate("03/2020", "BORR_DOB_DT", "B-001");
            assertNull(result);
        }
    }

    @Nested
    @DisplayName("requireNonBlank - Null/blank field detection")
    class RequireNonBlankTests {

        @Test
        @DisplayName("returns value when non-blank")
        void returnsValueWhenValid() {
            String result = validator.requireNonBlank("James", "BORR_FST_NM", "B-001", "Unknown");
            assertEquals("James", result);
        }

        @Test
        @DisplayName("returns fallback for null")
        void returnsFallbackForNull() {
            String result = validator.requireNonBlank(null, "BORR_FST_NM", "B-001", "Unknown");
            assertEquals("Unknown", result);
        }

        @Test
        @DisplayName("returns fallback for blank string")
        void returnsFallbackForBlank() {
            String result = validator.requireNonBlank("   ", "BORR_FST_NM", "B-001", "Unknown");
            assertEquals("Unknown", result);
        }
    }

    @Nested
    @DisplayName("validateStatusCode - Status code validation")
    class ValidateStatusCodeTests {

        @Test
        @DisplayName("accepts valid loan status code")
        void acceptsValidLoanStatus() {
            String result = validator.validateLoanStatus("ACT", "LN-001");
            assertEquals("ACT", result);
        }

        @Test
        @DisplayName("logs warning for unknown loan status but returns it")
        void returnsUnknownLoanStatus() {
            String result = validator.validateLoanStatus("XXX", "LN-001");
            assertEquals("XXX", result);
        }

        @Test
        @DisplayName("returns null for null status code")
        void returnsNullForNullStatus() {
            String result = validator.validateLoanStatus(null, "LN-001");
            assertNull(result);
        }

        @Test
        @DisplayName("accepts valid payment status code")
        void acceptsValidPaymentStatus() {
            String result = validator.validatePaymentStatus("PST", "PMT-001");
            assertEquals("PST", result);
        }

        @Test
        @DisplayName("accepts valid payment type code")
        void acceptsValidPaymentType() {
            String result = validator.validatePaymentType("REG", "PMT-001");
            assertEquals("REG", result);
        }

        @Test
        @DisplayName("accepts valid property type code")
        void acceptsValidPropertyType() {
            String result = validator.validatePropertyType("SFR", "LN-001");
            assertEquals("SFR", result);
        }

        @Test
        @DisplayName("returns unknown property type with warning")
        void returnsUnknownPropertyType() {
            String result = validator.validatePropertyType("HOUSE", "LN-001");
            assertEquals("HOUSE", result);
        }
    }

    @Nested
    @DisplayName("validatePaymentConsistency - Payment component sum validation")
    class PaymentConsistencyTests {

        @Test
        @DisplayName("returns true when components sum to total")
        void returnsTrueWhenConsistent() {
            boolean result = validator.validatePaymentConsistency(
                    new BigDecimal("2924.18"),
                    new BigDecimal("1842.56"),
                    new BigDecimal("815.50"),
                    new BigDecimal("266.12"),
                    new BigDecimal("0.00"),
                    "PMT-002"
            );
            assertTrue(result);
        }

        @Test
        @DisplayName("returns false when components exceed total (anomaly #1)")
        void returnsFalseWhenComponentsExceedTotal() {
            boolean result = validator.validatePaymentConsistency(
                    new BigDecimal("1487.02"),
                    new BigDecimal("456.78"),
                    new BigDecimal("1074.69"),
                    new BigDecimal("355.55"),
                    new BigDecimal("0.00"),
                    "PMT-2025120001"
            );
            assertFalse(result);
        }

        @Test
        @DisplayName("tolerates rounding difference of $0.01")
        void toleratesSmallRoundingDifference() {
            boolean result = validator.validatePaymentConsistency(
                    new BigDecimal("100.00"),
                    new BigDecimal("50.005"),
                    new BigDecimal("49.995"),
                    new BigDecimal("0.00"),
                    new BigDecimal("0.00"),
                    "PMT-TEST"
            );
            assertTrue(result);
        }

        @Test
        @DisplayName("detects $400 discrepancy from seed data")
        void detectsFourHundredDollarDiscrepancy() {
            // PMT-2025110001: total=1,487.02, components sum=1,887.02
            boolean result = validator.validatePaymentConsistency(
                    new BigDecimal("1487.02"),
                    new BigDecimal("454.97"),
                    new BigDecimal("1076.50"),
                    new BigDecimal("355.55"),
                    new BigDecimal("0.00"),
                    "PMT-2025110001"
            );
            assertFalse(result);
        }
    }

    @Nested
    @DisplayName("validateForeignKeyReference - Orphaned record detection")
    class ForeignKeyTests {

        @Test
        @DisplayName("returns true for non-null reference")
        void returnsTrueForValidRef() {
            boolean result = validator.validateForeignKeyReference("B-10001", "BORR_ID", "LN-001");
            assertTrue(result);
        }

        @Test
        @DisplayName("returns false for null reference")
        void returnsFalseForNullRef() {
            boolean result = validator.validateForeignKeyReference(null, "BORR_ID", "LN-001");
            assertFalse(result);
        }

        @Test
        @DisplayName("returns false for blank reference")
        void returnsFalseForBlankRef() {
            boolean result = validator.validateForeignKeyReference("  ", "BORR_ID", "LN-001");
            assertFalse(result);
        }
    }
}
