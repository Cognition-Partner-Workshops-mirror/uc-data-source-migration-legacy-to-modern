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
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Integration tests that verify the validation layer correctly handles
 * the known anomalies in the legacy seed data.
 */
@SpringBootTest
class LoanServiceValidationTest {

    @Autowired
    private LoanService loanService;

    @Autowired
    private LegacyBorrowerRepository borrowerRepository;

    @Autowired
    private LegacyLoanAccountRepository loanAccountRepository;

    @Autowired
    private LegacyLoanProductRepository productRepository;

    @Autowired
    private LegacyPaymentRepository paymentRepository;

    // =====================================================================
    // ANO-001: Numeric parsing on real seed data
    // =====================================================================
    @Test
    void loanAmountsAreParsedCorrectly() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertEquals(new BigDecimal("285000"), loan.getOriginalAmount());
        assertEquals(new BigDecimal("271432.56"), loan.getCurrentBalance());
        assertEquals(new BigDecimal("4.750"), loan.getInterestRate());
        assertEquals(new BigDecimal("1487.02"), loan.getMonthlyPayment());
    }

    // =====================================================================
    // ANO-002: Date fields are normalized to ISO-8601
    // =====================================================================
    @Test
    void datesAreNormalizedToIso8601() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");
        assertEquals("2019-02-15", loan.getOriginationDate());
    }

    @Test
    void paymentDatesAreNormalizedToIso8601() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertFalse(payments.isEmpty());
        for (PaymentDto pmt : payments) {
            assertNotNull(pmt.getPaymentDate());
            assertTrue(pmt.getPaymentDate().matches("\\d{4}-\\d{2}-\\d{2}"),
                    "Payment date should be ISO-8601: " + pmt.getPaymentDate());
        }
    }

    // =====================================================================
    // ANO-003: Orphaned record handling — service doesn't crash
    // =====================================================================
    @Test
    void loanWithMissingProductDoesNotCrash() {
        LegacyLoanAccount orphan = new LegacyLoanAccount();
        orphan.setLoanAccountNumber("LN-ORPHAN-001");
        orphan.setBorrowerId("B-99999");
        orphan.setBorrowerFirstName("Orphan");
        orphan.setBorrowerLastName("Record");
        orphan.setBorrowerSsnLast4("0000");
        orphan.setProductCode("BADPROD");
        orphan.setOriginalAmount("100,000");
        orphan.setCurrentBalance("95,000");
        orphan.setInterestRate("5.000");
        orphan.setTermMonths("360");
        orphan.setMonthlyPayment("536.82");
        orphan.setOriginationDate("01/01/2020");
        orphan.setMaturityDate("01/01/2050");
        orphan.setFirstPaymentDate("02/01/2020");
        orphan.setNextPaymentDate("01/01/2026");
        orphan.setStatusCode("ACT");
        orphan.setDelinquencyDays("0");
        orphan.setEscrowBalance("500.00");
        orphan.setLtvPercent("80.0");
        orphan.setPropertyAddress("123 Test St");
        orphan.setPropertyCity("TestCity");
        orphan.setPropertyState("TX");
        orphan.setPropertyZip("75001");
        orphan.setPropertyType("SFR");
        orphan.setAppraisedValue("125,000");
        orphan.setCreatedDate("01/01/2020");
        orphan.setUpdatedDate("12/01/2025");
        loanAccountRepository.save(orphan);

        LoanSummaryDto dto = loanService.getLoanById("LN-ORPHAN-001");
        assertNotNull(dto);
        assertEquals("BADPROD", dto.getProductDescription());

        loanAccountRepository.delete(orphan);
    }

    // =====================================================================
    // ANO-005: Null name fields produce safe output
    // =====================================================================
    @Test
    void borrowerWithNullNamesGetsFallback() {
        LegacyBorrower bad = new LegacyBorrower();
        bad.setBorrowerId("B-NULL-TEST");
        bad.setFirstName(null);
        bad.setLastName(null);
        bad.setMiddleInitial(null);
        bad.setCreditScore("750");
        bad.setStatusCode("ACT");
        bad.setRecordType("PRI");
        borrowerRepository.save(bad);

        BorrowerDto dto = loanService.getBorrowerById("B-NULL-TEST");
        assertEquals("Unknown Unknown", dto.getFullName());
        assertFalse(dto.getFullName().contains("null"));

        borrowerRepository.delete(bad);
    }

    // =====================================================================
    // ANO-010: Credit score range validation
    // =====================================================================
    @Test
    void validCreditScoresAreParsed() {
        BorrowerDto borrower = loanService.getBorrowerById("B-10001");
        assertEquals(745, borrower.getCreditScore());
    }

    @Test
    void outOfRangeCreditScoreReturnsNull() {
        LegacyBorrower bad = new LegacyBorrower();
        bad.setBorrowerId("B-BADSCORE");
        bad.setFirstName("Bad");
        bad.setLastName("Score");
        bad.setCreditScore("999");
        bad.setStatusCode("ACT");
        bad.setRecordType("PRI");
        borrowerRepository.save(bad);

        BorrowerDto dto = loanService.getBorrowerById("B-BADSCORE");
        assertNull(dto.getCreditScore());

        borrowerRepository.delete(bad);
    }

    @Test
    void nonNumericCreditScoreReturnsNull() {
        LegacyBorrower bad = new LegacyBorrower();
        bad.setBorrowerId("B-TEXTSCORE");
        bad.setFirstName("Text");
        bad.setLastName("Score");
        bad.setCreditScore("N/A");
        bad.setStatusCode("ACT");
        bad.setRecordType("PRI");
        borrowerRepository.save(bad);

        BorrowerDto dto = loanService.getBorrowerById("B-TEXTSCORE");
        assertNull(dto.getCreditScore());

        borrowerRepository.delete(bad);
    }

    // =====================================================================
    // ANO-007: Payment sum validation runs without crashing
    // =====================================================================
    @Test
    void paymentComponentsAreAllParsed() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2020-00398");
        assertFalse(payments.isEmpty());
        for (PaymentDto pmt : payments) {
            assertNotNull(pmt.getTotalAmount());
            assertNotNull(pmt.getPrincipalAmount());
            assertNotNull(pmt.getInterestAmount());
            assertNotNull(pmt.getEscrowAmount());
            assertNotNull(pmt.getLateFee());
        }
    }

    // =====================================================================
    // Full seed data: getAllLoans doesn't crash
    // =====================================================================
    @Test
    void getAllLoansReturnsAllSeedRecords() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        assertFalse(loans.isEmpty());
        assertTrue(loans.size() >= 5);
        for (LoanSummaryDto loan : loans) {
            assertNotNull(loan.getLoanAccountNumber());
            assertNotNull(loan.getOriginalAmount());
            assertNotNull(loan.getCurrentBalance());
            assertNotNull(loan.getInterestRate());
            assertNotNull(loan.getOriginationDate());
        }
    }

    @Test
    void getAllBorrowersReturnsAllSeedRecords() {
        List<BorrowerDto> borrowers = loanService.getAllBorrowers();
        assertFalse(borrowers.isEmpty());
        assertTrue(borrowers.size() >= 5);
        for (BorrowerDto b : borrowers) {
            assertNotNull(b.getId());
            assertNotNull(b.getFullName());
            assertFalse(b.getFullName().contains("null"));
        }
    }
}
