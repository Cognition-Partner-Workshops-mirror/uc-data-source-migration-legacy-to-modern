package com.workshop.loanservice.service;

import com.workshop.loanservice.validation.LegacyDataValidator;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.*;

class LoanServiceTest {

    private LoanService loanService;

    @BeforeEach
    void setUp() {
        LegacyDataValidator validator = new LegacyDataValidator();
        loanService = new LoanService(null, null, null, null, validator);
    }

    @Nested
    class ParseLegacyAmountTests {

        @Test
        void parsesValidAmount() {
            assertEquals(new BigDecimal("285000"), loanService.parseLegacyAmount("285,000"));
        }

        @Test
        void parsesDecimalAmount() {
            assertEquals(new BigDecimal("1487.02"), loanService.parseLegacyAmount("1,487.02"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, loanService.parseLegacyAmount(null));
        }

        @Test
        void returnsZeroForBlank() {
            assertEquals(BigDecimal.ZERO, loanService.parseLegacyAmount(""));
        }

        @Test
        void returnsZeroForInvalidInsteadOfThrowing() {
            assertEquals(BigDecimal.ZERO, loanService.parseLegacyAmount("N/A"));
        }

        @Test
        void returnsZeroForCurrencyPrefix() {
            assertEquals(BigDecimal.ZERO, loanService.parseLegacyAmount("$285,000"));
        }
    }

    @Nested
    class ParseLegacyDecimalTests {

        @Test
        void parsesValidDecimal() {
            assertEquals(new BigDecimal("4.750"), loanService.parseLegacyDecimal("4.750"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, loanService.parseLegacyDecimal(null));
        }

        @Test
        void returnsZeroForInvalid() {
            assertEquals(BigDecimal.ZERO, loanService.parseLegacyDecimal("TBD"));
        }
    }

    @Nested
    class ParseLegacyIntegerTests {

        @Test
        void parsesValidInteger() {
            assertEquals(745, loanService.parseLegacyInteger("745"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(loanService.parseLegacyInteger(null));
        }

        @Test
        void returnsNullForInvalid() {
            assertNull(loanService.parseLegacyInteger("PENDING"));
        }
    }

    @Nested
    class FormatLegacyDateTests {

        @Test
        void convertsToIsoFormat() {
            assertEquals("2019-02-15", loanService.formatLegacyDate("02/15/2019"));
        }

        @Test
        void convertsMonthDayCorrectly() {
            assertEquals("2025-12-01", loanService.formatLegacyDate("12/01/2025"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(loanService.formatLegacyDate(null));
        }

        @Test
        void returnsRawValueForInvalidDate() {
            assertEquals("13/01/2025", loanService.formatLegacyDate("13/01/2025"));
        }

        @Test
        void returnsRawValueForIsoFormat() {
            assertEquals("2025-01-15", loanService.formatLegacyDate("2025-01-15"));
        }
    }
}
