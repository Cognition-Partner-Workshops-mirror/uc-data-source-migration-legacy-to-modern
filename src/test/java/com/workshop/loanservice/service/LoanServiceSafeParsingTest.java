package com.workshop.loanservice.service;

import com.workshop.loanservice.repository.LegacyBorrowerRepository;
import com.workshop.loanservice.repository.LegacyLoanAccountRepository;
import com.workshop.loanservice.repository.LegacyLoanProductRepository;
import com.workshop.loanservice.repository.LegacyPaymentRepository;
import com.workshop.loanservice.validation.LegacyDataValidator;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for the safe parsing methods in LoanService (RCA-003 fix).
 * Verifies that malformed legacy data returns fallback defaults
 * instead of throwing unhandled NumberFormatException.
 */
@ExtendWith(MockitoExtension.class)
class LoanServiceSafeParsingTest {

    @Mock
    private LegacyBorrowerRepository borrowerRepository;
    @Mock
    private LegacyLoanAccountRepository loanAccountRepository;
    @Mock
    private LegacyLoanProductRepository loanProductRepository;
    @Mock
    private LegacyPaymentRepository paymentRepository;

    private LoanService loanService;

    @BeforeEach
    void setUp() {
        // Use real validator — no mocking needed for parse method tests
        LegacyDataValidator validator = new LegacyDataValidator();
        loanService = new LoanService(borrowerRepository, loanAccountRepository,
                loanProductRepository, paymentRepository, validator);
    }

    // =========================================================================
    // parseLegacyAmountSafe — handles comma-separated amounts with error recovery
    // =========================================================================

    @Nested
    @DisplayName("parseLegacyAmountSafe")
    class ParseAmountSafe {

        @Test
        @DisplayName("Parses valid comma-separated amount")
        void parsesValidAmount() {
            assertEquals(new BigDecimal("285000"), loanService.parseLegacyAmountSafe("285,000", "TEST", "R1"));
        }

        @Test
        @DisplayName("Parses valid decimal amount with commas")
        void parsesDecimalWithCommas() {
            assertEquals(new BigDecimal("1487.02"), loanService.parseLegacyAmountSafe("1,487.02", "TEST", "R1"));
        }

        @Test
        @DisplayName("Returns ZERO for null input")
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, loanService.parseLegacyAmountSafe(null, "TEST", "R1"));
        }

        @Test
        @DisplayName("Returns ZERO for blank input")
        void returnsZeroForBlank() {
            assertEquals(BigDecimal.ZERO, loanService.parseLegacyAmountSafe("  ", "TEST", "R1"));
        }

        @Test
        @DisplayName("Returns ZERO for non-numeric input (does not throw)")
        void returnsZeroForNonNumeric() {
            // RCA-003: Previously would throw NumberFormatException
            assertDoesNotThrow(() -> {
                BigDecimal result = loanService.parseLegacyAmountSafe("$285,000", "TEST", "R1");
                assertEquals(BigDecimal.ZERO, result);
            });
        }

        @Test
        @DisplayName("Returns ZERO for text input like 'N/A'")
        void returnsZeroForTextInput() {
            assertDoesNotThrow(() -> {
                BigDecimal result = loanService.parseLegacyAmountSafe("N/A", "TEST", "R1");
                assertEquals(BigDecimal.ZERO, result);
            });
        }

        @Test
        @DisplayName("Returns ZERO for 'PENDING' text")
        void returnsZeroForPending() {
            assertDoesNotThrow(() -> {
                BigDecimal result = loanService.parseLegacyAmountSafe("PENDING", "TEST", "R1");
                assertEquals(BigDecimal.ZERO, result);
            });
        }
    }

    // =========================================================================
    // parseLegacyDecimalSafe — handles plain decimals with error recovery
    // =========================================================================

    @Nested
    @DisplayName("parseLegacyDecimalSafe")
    class ParseDecimalSafe {

        @Test
        @DisplayName("Parses valid decimal")
        void parsesValidDecimal() {
            assertEquals(new BigDecimal("4.750"), loanService.parseLegacyDecimalSafe("4.750", "TEST", "R1"));
        }

        @Test
        @DisplayName("Handles commas in decimal (improvement over original)")
        void handlesCommasInDecimal() {
            // Original parseLegacyDecimal did not strip commas; this now does
            assertEquals(new BigDecimal("1234.56"), loanService.parseLegacyDecimalSafe("1,234.56", "TEST", "R1"));
        }

        @Test
        @DisplayName("Returns ZERO for non-numeric input (does not throw)")
        void returnsZeroForNonNumeric() {
            assertDoesNotThrow(() -> {
                BigDecimal result = loanService.parseLegacyDecimalSafe("VARIABLE", "TEST", "R1");
                assertEquals(BigDecimal.ZERO, result);
            });
        }
    }

    // =========================================================================
    // parseLegacyIntegerSafe — handles integer strings with error recovery
    // =========================================================================

    @Nested
    @DisplayName("parseLegacyIntegerSafe")
    class ParseIntegerSafe {

        @Test
        @DisplayName("Parses valid integer string")
        void parsesValidInteger() {
            assertEquals(745, loanService.parseLegacyIntegerSafe("745", "TEST", "R1"));
        }

        @Test
        @DisplayName("Handles leading/trailing whitespace")
        void handlesWhitespace() {
            assertEquals(745, loanService.parseLegacyIntegerSafe(" 745 ", "TEST", "R1"));
        }

        @Test
        @DisplayName("Returns null for null input")
        void returnsNullForNull() {
            assertNull(loanService.parseLegacyIntegerSafe(null, "TEST", "R1"));
        }

        @Test
        @DisplayName("Returns null for blank input")
        void returnsNullForBlank() {
            assertNull(loanService.parseLegacyIntegerSafe("  ", "TEST", "R1"));
        }

        @Test
        @DisplayName("Returns null for non-numeric input (does not throw)")
        void returnsNullForNonNumeric() {
            // RCA-003: Previously would throw NumberFormatException
            assertDoesNotThrow(() -> {
                Integer result = loanService.parseLegacyIntegerSafe("N/A", "TEST", "R1");
                assertNull(result);
            });
        }

        @Test
        @DisplayName("Returns null for decimal string (does not throw)")
        void returnsNullForDecimal() {
            // Integer.parseInt("745.5") throws — safe version catches this
            assertDoesNotThrow(() -> {
                Integer result = loanService.parseLegacyIntegerSafe("745.5", "TEST", "R1");
                assertNull(result);
            });
        }
    }
}
