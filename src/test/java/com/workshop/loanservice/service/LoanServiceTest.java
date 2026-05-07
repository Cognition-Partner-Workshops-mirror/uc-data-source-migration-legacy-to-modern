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
import com.workshop.loanservice.validation.LegacyDataValidator;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.when;

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
        LegacyDataValidator validator = new LegacyDataValidator();
        loanService = new LoanService(borrowerRepository, loanAccountRepository,
                loanProductRepository, paymentRepository, validator);
    }

    // =========================================================================
    // ANO-001: Malformed numeric fields don't crash the service
    // =========================================================================

    @Nested
    class NumericParsingResilience {

        @Test
        void handlesNonNumericAmountWithoutCrashing() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-001");
            acct.setOriginalAmount("N/A");
            acct.setCurrentBalance("TBD");
            acct.setInterestRate("abc");
            acct.setMonthlyPayment("$invalid");

            LegacyLoanProduct product = buildProduct("FXD30", "30-Year Fixed");
            when(loanProductRepository.findAll()).thenReturn(List.of(product));
            when(loanAccountRepository.findAll()).thenReturn(List.of(acct));

            List<LoanSummaryDto> loans = loanService.getAllLoans();

            assertEquals(1, loans.size());
            assertEquals(BigDecimal.ZERO, loans.get(0).getOriginalAmount());
            assertEquals(BigDecimal.ZERO, loans.get(0).getCurrentBalance());
            assertEquals(BigDecimal.ZERO, loans.get(0).getInterestRate());
            assertEquals(BigDecimal.ZERO, loans.get(0).getMonthlyPayment());
        }

        @Test
        void parsesCommaFormattedAmountsCorrectly() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-001");
            acct.setOriginalAmount("285,000");
            acct.setCurrentBalance("271,432.56");
            acct.setInterestRate("5.250");
            acct.setMonthlyPayment("1,487.02");

            LegacyLoanProduct product = buildProduct("FXD30", "30-Year Fixed");
            when(loanProductRepository.findAll()).thenReturn(List.of(product));
            when(loanAccountRepository.findAll()).thenReturn(List.of(acct));

            List<LoanSummaryDto> loans = loanService.getAllLoans();

            assertEquals(new BigDecimal("285000"), loans.get(0).getOriginalAmount());
            assertEquals(new BigDecimal("271432.56"), loans.get(0).getCurrentBalance());
            assertEquals(new BigDecimal("5.250"), loans.get(0).getInterestRate());
            assertEquals(new BigDecimal("1487.02"), loans.get(0).getMonthlyPayment());
        }
    }

    // =========================================================================
    // ANO-002 / ANO-012: Date format normalization and sorting
    // =========================================================================

    @Nested
    class DateHandling {

        @Test
        void normalizesLegacyDateFormat() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-001");
            acct.setOriginationDate("02/15/2019");

            LegacyLoanProduct product = buildProduct("FXD30", "30-Year Fixed");
            when(loanProductRepository.findAll()).thenReturn(List.of(product));
            when(loanAccountRepository.findAll()).thenReturn(List.of(acct));

            List<LoanSummaryDto> loans = loanService.getAllLoans();
            assertEquals("2019-02-15", loans.get(0).getOriginationDate());
        }

        @Test
        void sortsPaymentsByDateChronologically() {
            LegacyPayment pmt1 = buildPayment("PMT-001", "LN-001", "09/01/2025");
            LegacyPayment pmt2 = buildPayment("PMT-002", "LN-001", "12/01/2025");
            LegacyPayment pmt3 = buildPayment("PMT-003", "LN-001", "01/15/2026");

            when(paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc("LN-001"))
                    .thenReturn(List.of(pmt2, pmt1, pmt3));

            List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-001");

            assertEquals("2026-01-15", payments.get(0).getPaymentDate());
            assertEquals("2025-12-01", payments.get(1).getPaymentDate());
            assertEquals("2025-09-01", payments.get(2).getPaymentDate());
        }

        @Test
        void handlesNullPaymentDate() {
            LegacyPayment pmt1 = buildPayment("PMT-001", "LN-001", "12/01/2025");
            LegacyPayment pmt2 = buildPayment("PMT-002", "LN-001", null);

            when(paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc("LN-001"))
                    .thenReturn(List.of(pmt1, pmt2));

            List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-001");
            assertEquals(2, payments.size());
            assertEquals("2025-12-01", payments.get(0).getPaymentDate());
            assertNull(payments.get(1).getPaymentDate());
        }
    }

    // =========================================================================
    // ANO-003: Missing product reference handled gracefully
    // =========================================================================

    @Nested
    class OrphanedRecordHandling {

        @Test
        void handlesUnknownProductCodeGracefully() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-001");
            acct.setProductCode("INVALID");

            when(loanProductRepository.findAll()).thenReturn(List.of());
            when(loanAccountRepository.findAll()).thenReturn(List.of(acct));

            List<LoanSummaryDto> loans = loanService.getAllLoans();

            assertEquals(1, loans.size());
            assertEquals("INVALID", loans.get(0).getProductDescription());
        }
    }

    // =========================================================================
    // ANO-006: Credit score validation
    // =========================================================================

    @Nested
    class CreditScoreHandling {

        @Test
        void validCreditScorePassesThrough() {
            LegacyBorrower borrower = buildBorrower("B-001", "745");
            when(borrowerRepository.findAll()).thenReturn(List.of(borrower));

            List<BorrowerDto> borrowers = loanService.getAllBorrowers();
            assertEquals(745, borrowers.get(0).getCreditScore());
        }

        @Test
        void outOfRangeCreditScoreBecomesNull() {
            LegacyBorrower borrower = buildBorrower("B-001", "999");
            when(borrowerRepository.findAll()).thenReturn(List.of(borrower));

            List<BorrowerDto> borrowers = loanService.getAllBorrowers();
            assertNull(borrowers.get(0).getCreditScore());
        }

        @Test
        void nonNumericCreditScoreBecomesNull() {
            LegacyBorrower borrower = buildBorrower("B-001", "N/A");
            when(borrowerRepository.findAll()).thenReturn(List.of(borrower));

            List<BorrowerDto> borrowers = loanService.getAllBorrowers();
            assertNull(borrowers.get(0).getCreditScore());
        }
    }

    // =========================================================================
    // ANO-011: Null-safe property address
    // =========================================================================

    @Nested
    class NullSafeAddress {

        @Test
        void buildsAddressWithAllFields() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-001");
            acct.setPropertyAddress("123 Main St");
            acct.setPropertyCity("Springfield");
            acct.setPropertyState("IL");
            acct.setPropertyZip("62704");

            LegacyLoanProduct product = buildProduct("FXD30", "30-Year Fixed");
            when(loanProductRepository.findAll()).thenReturn(List.of(product));
            when(loanAccountRepository.findAll()).thenReturn(List.of(acct));

            List<LoanSummaryDto> loans = loanService.getAllLoans();
            assertEquals("123 Main St, Springfield, IL 62704", loans.get(0).getPropertyAddress());
        }

        @Test
        void buildsAddressWithNullFields() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-001");
            acct.setPropertyAddress(null);
            acct.setPropertyCity(null);
            acct.setPropertyState(null);
            acct.setPropertyZip(null);

            LegacyLoanProduct product = buildProduct("FXD30", "30-Year Fixed");
            when(loanProductRepository.findAll()).thenReturn(List.of(product));
            when(loanAccountRepository.findAll()).thenReturn(List.of(acct));

            List<LoanSummaryDto> loans = loanService.getAllLoans();
            assertEquals("Unknown", loans.get(0).getPropertyAddress());
        }
    }

    // =========================================================================
    // ANO-007: Payment balance reconciliation (logged, not blocking)
    // =========================================================================

    @Nested
    class PaymentBalanceReconciliation {

        @Test
        void processesImbalancedPaymentWithoutCrashing() {
            LegacyPayment pmt = buildPayment("PMT-001", "LN-001", "12/01/2025");
            pmt.setTotalAmount("1,487.02");
            pmt.setPrincipalAmount("456.78");
            pmt.setInterestAmount("1,074.69");
            pmt.setEscrowAmount("355.55");
            pmt.setLateFee("0.00");

            when(paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc("LN-001"))
                    .thenReturn(List.of(pmt));

            List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-001");

            assertEquals(1, payments.size());
            assertEquals(new BigDecimal("1487.02"), payments.get(0).getTotalAmount());
            assertEquals(new BigDecimal("456.78"), payments.get(0).getPrincipalAmount());
        }
    }

    // =========================================================================
    // Helpers
    // =========================================================================

    private LegacyLoanAccount buildLoanAccount(String loanId, String borrowerId) {
        LegacyLoanAccount acct = new LegacyLoanAccount();
        acct.setLoanAccountNumber(loanId);
        acct.setBorrowerId(borrowerId);
        acct.setBorrowerFirstName("John");
        acct.setBorrowerLastName("Doe");
        acct.setProductCode("FXD30");
        acct.setOriginalAmount("285,000");
        acct.setCurrentBalance("271,432.56");
        acct.setInterestRate("5.250");
        acct.setMonthlyPayment("1,487.02");
        acct.setStatusCode("ACT");
        acct.setOriginationDate("02/15/2019");
        acct.setPropertyAddress("123 Main St");
        acct.setPropertyCity("Springfield");
        acct.setPropertyState("IL");
        acct.setPropertyZip("62704");
        acct.setPropertyType("SFR");
        acct.setDelinquencyDays("0");
        acct.setLtvPercent("82.5");
        acct.setAppraisedValue("345,000");
        return acct;
    }

    private LegacyLoanProduct buildProduct(String code, String description) {
        LegacyLoanProduct product = new LegacyLoanProduct();
        product.setProductCode(code);
        product.setDescription(description);
        return product;
    }

    private LegacyBorrower buildBorrower(String id, String creditScore) {
        LegacyBorrower borrower = new LegacyBorrower();
        borrower.setBorrowerId(id);
        borrower.setFirstName("John");
        borrower.setLastName("Doe");
        borrower.setCreditScore(creditScore);
        borrower.setEmploymentStatus("Employed");
        return borrower;
    }

    private LegacyPayment buildPayment(String pmtId, String loanId, String date) {
        LegacyPayment pmt = new LegacyPayment();
        pmt.setPaymentSequenceNumber(pmtId);
        pmt.setLoanAccountNumber(loanId);
        pmt.setPaymentDate(date);
        pmt.setTotalAmount("1,487.02");
        pmt.setPrincipalAmount("456.78");
        pmt.setInterestAmount("674.69");
        pmt.setEscrowAmount("355.55");
        pmt.setLateFee("0.00");
        pmt.setTypeCode("REG");
        pmt.setStatusCode("PST");
        return pmt;
    }
}
