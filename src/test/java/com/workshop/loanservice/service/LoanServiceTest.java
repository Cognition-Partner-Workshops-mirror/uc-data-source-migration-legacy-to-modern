package com.workshop.loanservice.service;

import com.workshop.loanservice.dto.BorrowerDto;
import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;
import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyLoanProduct;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.repository.LegacyBorrowerRepository;
import com.workshop.loanservice.repository.LegacyLoanAccountRepository;
import com.workshop.loanservice.repository.LegacyLoanProductRepository;
import com.workshop.loanservice.repository.LegacyPaymentRepository;
import com.workshop.loanservice.validation.DataQualityValidator;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

/**
 * Tests for LoanService — verifies that the service layer handles legacy
 * data anomalies gracefully instead of crashing (ANOM-002, ANOM-003 fixes).
 */
@ExtendWith(MockitoExtension.class)
class LoanServiceTest {

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
        // Use a real DataQualityValidator (not mocked) so validation warnings are exercised
        DataQualityValidator validator = new DataQualityValidator();
        loanService = new LoanService(
                borrowerRepository, loanAccountRepository,
                loanProductRepository, paymentRepository, validator);
    }

    // =========================================================================
    // ANOM-003 fix: Safe parsing — malformed values don't crash endpoints
    // =========================================================================

    @Nested
    @DisplayName("ANOM-003: Safe Parsing in Service Layer")
    class SafeParsingTests {

        @Test
        @DisplayName("parseLegacyAmount returns ZERO for malformed amounts instead of throwing")
        void parseLegacyAmountHandlesMalformed() {
            // These would throw NumberFormatException without the fix
            assertEquals(BigDecimal.ZERO, loanService.parseLegacyAmount("$285,000"));
            assertEquals(BigDecimal.ZERO, loanService.parseLegacyAmount("N/A"));
            assertEquals(BigDecimal.ZERO, loanService.parseLegacyAmount("TBD"));
            assertEquals(BigDecimal.ZERO, loanService.parseLegacyAmount("285 000"));
        }

        @Test
        @DisplayName("parseLegacyAmount correctly parses valid comma-formatted amounts")
        void parseLegacyAmountHandlesValid() {
            assertEquals(new BigDecimal("285000"), loanService.parseLegacyAmount("285,000"));
            assertEquals(new BigDecimal("271432.56"), loanService.parseLegacyAmount("271,432.56"));
            assertEquals(new BigDecimal("0.00"), loanService.parseLegacyAmount("0.00"));
        }

        @Test
        @DisplayName("parseLegacyAmount returns ZERO for null/blank")
        void parseLegacyAmountHandlesNullBlank() {
            assertEquals(BigDecimal.ZERO, loanService.parseLegacyAmount(null));
            assertEquals(BigDecimal.ZERO, loanService.parseLegacyAmount(""));
            assertEquals(BigDecimal.ZERO, loanService.parseLegacyAmount("   "));
        }

        @Test
        @DisplayName("parseLegacyDecimal returns ZERO for malformed decimals")
        void parseLegacyDecimalHandlesMalformed() {
            assertEquals(BigDecimal.ZERO, loanService.parseLegacyDecimal("4.750%"));
            assertEquals(BigDecimal.ZERO, loanService.parseLegacyDecimal("abc"));
        }

        @Test
        @DisplayName("parseLegacyInteger returns null for malformed integers")
        void parseLegacyIntegerHandlesMalformed() {
            assertNull(loanService.parseLegacyInteger("N/A"));
            assertNull(loanService.parseLegacyInteger("PENDING"));
            assertNull(loanService.parseLegacyInteger("15 days"));
        }
    }

    // =========================================================================
    // ANOM-002 fix: Null-safe name/address concatenation
    // =========================================================================

    @Nested
    @DisplayName("ANOM-002: Null-Safe Translation")
    class NullSafeTranslationTests {

        @Test
        @DisplayName("getAllLoans handles null borrower names without NPE")
        void getAllLoansHandlesNullNames() {
            LegacyLoanAccount acct = createLoanAccountWithNullNames();
            LegacyLoanProduct product = createProduct();

            when(loanAccountRepository.findAll()).thenReturn(List.of(acct));
            when(loanProductRepository.findAll()).thenReturn(List.of(product));

            // Should not throw NPE
            List<LoanSummaryDto> loans = loanService.getAllLoans();

            assertEquals(1, loans.size());
            // Null names should be replaced with "Unknown" instead of literal "null"
            assertFalse(loans.get(0).getBorrowerName().contains("null"),
                    "Borrower name should not contain literal 'null': " + loans.get(0).getBorrowerName());
            assertTrue(loans.get(0).getBorrowerName().contains("Unknown"),
                    "Null name should be replaced with 'Unknown': " + loans.get(0).getBorrowerName());
        }

        @Test
        @DisplayName("getAllLoans handles null property address fields without NPE")
        void getAllLoansHandlesNullAddressFields() {
            LegacyLoanAccount acct = createLoanAccountWithNullAddress();
            LegacyLoanProduct product = createProduct();

            when(loanAccountRepository.findAll()).thenReturn(List.of(acct));
            when(loanProductRepository.findAll()).thenReturn(List.of(product));

            List<LoanSummaryDto> loans = loanService.getAllLoans();

            assertEquals(1, loans.size());
            // Null address components should be replaced with "N/A"
            assertFalse(loans.get(0).getPropertyAddress().contains("null"),
                    "Property address should not contain literal 'null': " + loans.get(0).getPropertyAddress());
            assertTrue(loans.get(0).getPropertyAddress().contains("N/A"),
                    "Null address parts should show 'N/A': " + loans.get(0).getPropertyAddress());
        }

        @Test
        @DisplayName("getAllBorrowers handles null names without NPE")
        void getAllBorrowersHandlesNullNames() {
            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-99999");
            borrower.setFirstName(null);
            borrower.setLastName(null);
            borrower.setCreditScore("700");
            borrower.setStatusCode("ACT");

            when(borrowerRepository.findAll()).thenReturn(List.of(borrower));

            List<BorrowerDto> borrowers = loanService.getAllBorrowers();

            assertEquals(1, borrowers.size());
            assertFalse(borrowers.get(0).getFullName().contains("null"),
                    "Full name should not contain literal 'null': " + borrowers.get(0).getFullName());
        }

        @Test
        @DisplayName("getPaymentsByLoan handles malformed amount strings without crashing")
        void getPaymentsByLoanHandlesMalformedAmounts() {
            LegacyPayment pmt = new LegacyPayment();
            pmt.setPaymentSequenceNumber("PMT-BAD");
            pmt.setLoanAccountNumber("LN-TEST");
            pmt.setPaymentDate("12/01/2025");
            pmt.setTotalAmount("INVALID");
            pmt.setPrincipalAmount("$500");
            pmt.setInterestAmount("N/A");
            pmt.setEscrowAmount("abc");
            pmt.setLateFee("0.00");
            pmt.setTypeCode("REG");
            pmt.setStatusCode("PST");

            when(paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc("LN-TEST"))
                    .thenReturn(List.of(pmt));

            // Should not throw NumberFormatException
            List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-TEST");

            assertEquals(1, payments.size());
            // Malformed amounts should default to ZERO
            assertEquals(BigDecimal.ZERO, payments.get(0).getTotalAmount());
            assertEquals(BigDecimal.ZERO, payments.get(0).getPrincipalAmount());
            assertEquals(BigDecimal.ZERO, payments.get(0).getInterestAmount());
            assertEquals(BigDecimal.ZERO, payments.get(0).getEscrowAmount());
        }
    }

    // =========================================================================
    // ANOM-009 fix: Status code expansion
    // =========================================================================

    @Nested
    @DisplayName("ANOM-009: Status Code Handling")
    class StatusCodeTests {

        @Test
        @DisplayName("Unrecognized status code is passed through (not crash)")
        void unrecognizedStatusCodePassesThrough() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setStatusCode("XYZ");
            LegacyLoanProduct product = createProduct();

            when(loanAccountRepository.findAll()).thenReturn(List.of(acct));
            when(loanProductRepository.findAll()).thenReturn(List.of(product));

            List<LoanSummaryDto> loans = loanService.getAllLoans();

            assertEquals(1, loans.size());
            assertEquals("XYZ", loans.get(0).getStatus());
        }

        @Test
        @DisplayName("Null status code returns 'Unknown'")
        void nullStatusCodeReturnsUnknown() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setStatusCode(null);
            LegacyLoanProduct product = createProduct();

            when(loanAccountRepository.findAll()).thenReturn(List.of(acct));
            when(loanProductRepository.findAll()).thenReturn(List.of(product));

            List<LoanSummaryDto> loans = loanService.getAllLoans();

            assertEquals(1, loans.size());
            assertEquals("Unknown", loans.get(0).getStatus());
        }
    }

    // =========================================================================
    // Helper methods
    // =========================================================================

    private LegacyLoanAccount createValidLoanAccount() {
        LegacyLoanAccount a = new LegacyLoanAccount();
        a.setLoanAccountNumber("LN-TEST-001");
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

    private LegacyLoanAccount createLoanAccountWithNullNames() {
        LegacyLoanAccount a = createValidLoanAccount();
        a.setBorrowerFirstName(null);
        a.setBorrowerLastName(null);
        return a;
    }

    private LegacyLoanAccount createLoanAccountWithNullAddress() {
        LegacyLoanAccount a = createValidLoanAccount();
        a.setPropertyAddress(null);
        a.setPropertyCity(null);
        a.setPropertyState(null);
        a.setPropertyZip(null);
        return a;
    }

    private LegacyLoanProduct createProduct() {
        LegacyLoanProduct p = new LegacyLoanProduct();
        p.setProductCode("FXD30");
        p.setDescription("30-Year Fixed Rate Mortgage");
        p.setTypeCode("FXD");
        p.setTermMonths("360");
        p.setRateType("FIXED");
        p.setMinAmount("50,000");
        p.setMaxAmount("1,500,000");
        p.setStatusCode("ACT");
        p.setEffectiveDate("01/01/2020");
        p.setExpirationDate("12/31/2099");
        return p;
    }
}
