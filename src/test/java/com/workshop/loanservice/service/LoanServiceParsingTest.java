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

@ExtendWith(MockitoExtension.class)
class LoanServiceParsingTest {

    @Mock private LegacyBorrowerRepository borrowerRepo;
    @Mock private LegacyLoanAccountRepository loanRepo;
    @Mock private LegacyLoanProductRepository productRepo;
    @Mock private LegacyPaymentRepository paymentRepo;

    private LoanService service;

    @BeforeEach
    void setUp() {
        service = new LoanService(borrowerRepo, loanRepo, productRepo, paymentRepo,
                new LegacyDataValidator());
    }

    @Nested
    @DisplayName("parseLegacyAmount — robust amount parsing")
    class ParseAmount {

        @Test
        @DisplayName("Parses standard comma-formatted amount")
        void parsesCommaAmount() {
            assertEquals(new BigDecimal("285000"), service.parseLegacyAmount("285,000"));
        }

        @Test
        @DisplayName("Parses amount with decimal")
        void parsesDecimalAmount() {
            assertEquals(new BigDecimal("1487.02"), service.parseLegacyAmount("1,487.02"));
        }

        @Test
        @DisplayName("Strips dollar sign")
        void stripsDollarSign() {
            assertEquals(new BigDecimal("285000"), service.parseLegacyAmount("$285,000"));
        }

        @Test
        @DisplayName("Handles accounting-style negative (parentheses)")
        void handlesAccountingNegative() {
            assertEquals(new BigDecimal("-500.00"), service.parseLegacyAmount("(500.00)"));
        }

        @Test
        @DisplayName("Returns ZERO for null input")
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, service.parseLegacyAmount(null));
        }

        @Test
        @DisplayName("Returns ZERO for blank input")
        void returnsZeroForBlank() {
            assertEquals(BigDecimal.ZERO, service.parseLegacyAmount("  "));
        }

        @Test
        @DisplayName("Returns ZERO for non-numeric input instead of throwing")
        void returnsZeroForNonNumeric() {
            assertEquals(BigDecimal.ZERO, service.parseLegacyAmount("N/A"));
        }

        @Test
        @DisplayName("Returns ZERO for text like TBD")
        void returnsZeroForTbd() {
            assertEquals(BigDecimal.ZERO, service.parseLegacyAmount("TBD"));
        }
    }

    @Nested
    @DisplayName("parseLegacyDecimal — decimal parsing")
    class ParseDecimal {

        @Test
        @DisplayName("Parses interest rate string")
        void parsesInterestRate() {
            assertEquals(new BigDecimal("4.750"), service.parseLegacyDecimal("4.750"));
        }

        @Test
        @DisplayName("Returns ZERO for non-numeric")
        void returnsZeroForNonNumeric() {
            assertEquals(BigDecimal.ZERO, service.parseLegacyDecimal("VARIABLE"));
        }

        @Test
        @DisplayName("Returns ZERO for null")
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, service.parseLegacyDecimal(null));
        }
    }

    @Nested
    @DisplayName("parseLegacyInteger — integer parsing")
    class ParseInteger {

        @Test
        @DisplayName("Parses credit score")
        void parsesCreditScore() {
            assertEquals(745, service.parseLegacyInteger("745"));
        }

        @Test
        @DisplayName("Returns null for blank")
        void returnsNullForBlank() {
            assertNull(service.parseLegacyInteger(""));
        }

        @Test
        @DisplayName("Returns null for non-numeric instead of throwing")
        void returnsNullForNonNumeric() {
            assertNull(service.parseLegacyInteger("HIGH"));
        }

        @Test
        @DisplayName("Returns null for null input")
        void returnsNullForNull() {
            assertNull(service.parseLegacyInteger(null));
        }
    }

    @Nested
    @DisplayName("Status code expansion with fallback logging")
    class StatusExpansion {

        @Test
        @DisplayName("Expands known loan status codes")
        void expandsKnownLoanStatuses() {
            assertEquals("Active", service.expandStatusCode("ACT"));
            assertEquals("Closed", service.expandStatusCode("CLO"));
            assertEquals("Default", service.expandStatusCode("DFT"));
            assertEquals("Forbearance", service.expandStatusCode("FRB"));
        }

        @Test
        @DisplayName("Passes through unknown loan status code")
        void passesThroughUnknownLoanStatus() {
            assertEquals("XYZ", service.expandStatusCode("XYZ"));
        }

        @Test
        @DisplayName("Returns Unknown for null")
        void returnsUnknownForNull() {
            assertEquals("Unknown", service.expandStatusCode(null));
        }

        @Test
        @DisplayName("Expands known property type codes")
        void expandsPropertyTypes() {
            assertEquals("Single Family Residence", service.expandPropertyType("SFR"));
            assertEquals("Condominium", service.expandPropertyType("CND"));
            assertEquals("Multi-Family Residence", service.expandPropertyType("MFR"));
            assertEquals("Townhouse", service.expandPropertyType("TWN"));
        }

        @Test
        @DisplayName("Expands known payment type codes")
        void expandsPaymentTypes() {
            assertEquals("Regular", service.expandPaymentType("REG"));
            assertEquals("Extra", service.expandPaymentType("EXT"));
            assertEquals("Partial", service.expandPaymentType("PRT"));
            assertEquals("Prepayment", service.expandPaymentType("PRE"));
        }

        @Test
        @DisplayName("Expands known payment status codes")
        void expandsPaymentStatuses() {
            assertEquals("Posted", service.expandPaymentStatus("PST"));
            assertEquals("Reversed", service.expandPaymentStatus("REV"));
            assertEquals("Non-Sufficient Funds", service.expandPaymentStatus("NSF"));
            assertEquals("Pending", service.expandPaymentStatus("PND"));
        }
    }
}
