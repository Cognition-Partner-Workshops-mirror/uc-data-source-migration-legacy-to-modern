package com.workshop.loanservice.migration;

import com.workshop.loanservice.entity.modern.Borrower;
import com.workshop.loanservice.entity.modern.LoanAccount;
import com.workshop.loanservice.entity.modern.LoanProduct;
import com.workshop.loanservice.entity.modern.Payment;
import com.workshop.loanservice.repository.LegacyBorrowerRepository;
import com.workshop.loanservice.repository.LegacyLoanAccountRepository;
import com.workshop.loanservice.repository.LegacyLoanProductRepository;
import com.workshop.loanservice.repository.LegacyPaymentRepository;
import com.workshop.loanservice.repository.modern.BorrowerRepository;
import com.workshop.loanservice.repository.modern.LoanAccountRepository;
import com.workshop.loanservice.repository.modern.LoanProductRepository;
import com.workshop.loanservice.repository.modern.PaymentRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Data reconciliation tests that verify the migration from legacy CDW tables
 * to the modern schema preserved all records correctly.
 *
 * Validates:
 * - Record counts match between legacy and modern tables
 * - Field values are correctly transformed (dates, amounts, statuses)
 * - FK relationships are properly resolved
 * - Denormalized fields are correctly dropped/normalized
 */
@SpringBootTest
@Transactional
class DataReconciliationTest {

    @Autowired
    private LegacyBorrowerRepository legacyBorrowerRepo;
    @Autowired
    private LegacyLoanProductRepository legacyProductRepo;
    @Autowired
    private LegacyLoanAccountRepository legacyAccountRepo;
    @Autowired
    private LegacyPaymentRepository legacyPaymentRepo;

    @Autowired
    private BorrowerRepository modernBorrowerRepo;
    @Autowired
    private LoanProductRepository modernProductRepo;
    @Autowired
    private LoanAccountRepository modernAccountRepo;
    @Autowired
    private PaymentRepository modernPaymentRepo;

    // =========================================================================
    // RECORD COUNT TESTS — verify no data loss during migration
    // =========================================================================

    @Test
    void borrowerRecordCountMatches() {
        long legacyCount = legacyBorrowerRepo.count();
        long modernCount = modernBorrowerRepo.count();
        assertEquals(legacyCount, modernCount,
                "Borrower count mismatch: legacy=" + legacyCount + " modern=" + modernCount);
    }

    @Test
    void loanProductRecordCountMatches() {
        long legacyCount = legacyProductRepo.count();
        long modernCount = modernProductRepo.count();
        assertEquals(legacyCount, modernCount,
                "Loan product count mismatch: legacy=" + legacyCount + " modern=" + modernCount);
    }

    @Test
    void loanAccountRecordCountMatches() {
        long legacyCount = legacyAccountRepo.count();
        long modernCount = modernAccountRepo.count();
        assertEquals(legacyCount, modernCount,
                "Loan account count mismatch: legacy=" + legacyCount + " modern=" + modernCount);
    }

    @Test
    void paymentRecordCountMatches() {
        long legacyCount = legacyPaymentRepo.count();
        long modernCount = modernPaymentRepo.count();
        assertEquals(legacyCount, modernCount,
                "Payment count mismatch: legacy=" + legacyCount + " modern=" + modernCount);
    }

    // =========================================================================
    // FIELD VALUE TESTS — verify transformations are correct
    // =========================================================================

    @Test
    void borrowerFieldsTransformedCorrectly() {
        // Verify James Mitchell (B-10001) migration
        Optional<Borrower> opt = modernBorrowerRepo.findByExternalId("B-10001");
        assertTrue(opt.isPresent(), "Borrower B-10001 should exist in modern schema");

        Borrower borrower = opt.get();
        assertEquals("James", borrower.getFirstName());
        assertEquals("Mitchell", borrower.getLastName());
        assertEquals("R", borrower.getMiddleInitial());
        assertEquals("j.mitchell@email.com", borrower.getEmail());
        assertEquals("Springfield", borrower.getCity());
        assertEquals("IL", borrower.getState());
        assertEquals("62701", borrower.getZipCode());

        // Date transformation: "03/15/1978" → LocalDate(1978, 3, 15)
        assertEquals(LocalDate.of(1978, 3, 15), borrower.getDateOfBirth());

        // Integer parsing: "745" → 745
        assertEquals(745, borrower.getCreditScore());

        // Amount parsing: "92,500" → 92500.00
        assertEquals(0, new BigDecimal("92500").compareTo(borrower.getAnnualIncome()));

        // Status expansion: "ACT" → ACTIVE
        assertEquals(Borrower.Status.ACTIVE, borrower.getStatus());
    }

    @Test
    void borrowerWithNullMiddleInitialHandled() {
        // Robert Williams (B-10005) has NULL middle initial
        Optional<Borrower> opt = modernBorrowerRepo.findByExternalId("B-10005");
        assertTrue(opt.isPresent());
        assertNull(opt.get().getMiddleInitial());
        assertEquals("RETIRED", opt.get().getEmploymentStatus());
    }

    @Test
    void loanProductFieldsTransformedCorrectly() {
        // Verify FXD30 product migration
        Optional<LoanProduct> opt = modernProductRepo.findByCode("FXD30");
        assertTrue(opt.isPresent(), "Product FXD30 should exist in modern schema");

        LoanProduct product = opt.get();
        assertEquals("30-Year Fixed Rate Mortgage", product.getName());
        assertEquals("FXD", product.getType());
        assertEquals(360, product.getTermMonths());
        assertEquals("FIXED", product.getRateType());

        // Amount parsing: "50,000" → 50000.00
        assertEquals(0, new BigDecimal("50000").compareTo(product.getMinAmount()));
        assertEquals(0, new BigDecimal("1500000").compareTo(product.getMaxAmount()));

        // Status to boolean: "ACT" → true
        assertTrue(product.getIsActive());

        // Date parsing: "01/01/2020" → LocalDate(2020, 1, 1)
        assertEquals(LocalDate.of(2020, 1, 1), product.getEffectiveDate());
    }

    @Test
    void loanAccountFieldsTransformedCorrectly() {
        // Verify LN-2019-00142 migration
        Optional<LoanAccount> opt = modernAccountRepo.findByAccountNumber("LN-2019-00142");
        assertTrue(opt.isPresent(), "Loan LN-2019-00142 should exist in modern schema");

        LoanAccount account = opt.get();

        // FK resolution: borrower resolved by external_id
        assertNotNull(account.getBorrower());
        assertEquals("B-10001", account.getBorrower().getExternalId());

        // FK resolution: product resolved by code
        assertNotNull(account.getProduct());
        assertEquals("FXD30", account.getProduct().getCode());

        // Amount transformations
        assertEquals(0, new BigDecimal("285000").compareTo(account.getOriginalAmount()));
        assertEquals(0, new BigDecimal("271432.56").compareTo(account.getCurrentBalance()));
        assertEquals(0, new BigDecimal("4.750").compareTo(account.getInterestRate()));
        assertEquals(0, new BigDecimal("1487.02").compareTo(account.getMonthlyPayment()));
        assertEquals(0, new BigDecimal("3245.80").compareTo(account.getEscrowBalance()));
        assertEquals(0, new BigDecimal("82.5").compareTo(account.getLtvPercent()));

        // Integer parsing
        assertEquals(360, account.getTermMonths());
        assertEquals(0, account.getDelinquencyDays());

        // Date parsing
        assertEquals(LocalDate.of(2019, 2, 15), account.getOriginationDate());
        assertEquals(LocalDate.of(2049, 2, 15), account.getMaturityDate());

        // Status expansion: "ACT" → ACTIVE
        assertEquals(LoanAccount.Status.ACTIVE, account.getStatus());

        // Property type expansion: "SFR" → "Single Family"
        assertEquals("Single Family", account.getPropertyType());
        assertEquals("742 Elm Street", account.getPropertyAddress());
    }

    @Test
    void loanAccountDelinquencyDaysPreserved() {
        // LN-2018-00089 has 15 delinquency days
        Optional<LoanAccount> opt = modernAccountRepo.findByAccountNumber("LN-2018-00089");
        assertTrue(opt.isPresent());
        assertEquals(15, opt.get().getDelinquencyDays());
    }

    @Test
    void paymentFieldsTransformedCorrectly() {
        // Verify a payment for LN-2019-00142
        Optional<LoanAccount> acctOpt = modernAccountRepo.findByAccountNumber("LN-2019-00142");
        assertTrue(acctOpt.isPresent());

        var payments = modernPaymentRepo.findByLoanAccountIdOrderByPaymentDateDesc(acctOpt.get().getId());
        assertFalse(payments.isEmpty(), "Payments should exist for LN-2019-00142");

        // First payment (most recent) should be Dec 2025
        Payment latestPayment = payments.get(0);
        assertEquals(LocalDate.of(2025, 12, 15), latestPayment.getPaymentDate());
        assertEquals(0, new BigDecimal("1487.02").compareTo(latestPayment.getTotalAmount()));
        assertEquals(0, new BigDecimal("456.78").compareTo(latestPayment.getPrincipalAmount()));
        assertEquals(0, new BigDecimal("1074.69").compareTo(latestPayment.getInterestAmount()));
        assertEquals(0, new BigDecimal("355.55").compareTo(latestPayment.getEscrowAmount()));
        assertEquals(0, new BigDecimal("0.00").compareTo(latestPayment.getLateFee()));

        // Type expansion: "REG" → REGULAR
        assertEquals(Payment.PaymentType.REGULAR, latestPayment.getType());

        // Status expansion: "PST" → POSTED
        assertEquals(Payment.PaymentStatus.POSTED, latestPayment.getStatus());

        // Date fields
        assertEquals(LocalDate.of(2025, 12, 14), latestPayment.getReceivedDate());
        assertEquals(LocalDate.of(2025, 12, 15), latestPayment.getProcessedDate());
    }

    @Test
    void paymentWithLateFeePreserved() {
        // LN-2018-00089 Nov payment has a $47.50 late fee
        Optional<LoanAccount> acctOpt = modernAccountRepo.findByAccountNumber("LN-2018-00089");
        assertTrue(acctOpt.isPresent());

        var payments = modernPaymentRepo.findByLoanAccountIdOrderByPaymentDateDesc(acctOpt.get().getId());
        // Find the November payment (second in desc order)
        Payment novPayment = payments.stream()
                .filter(p -> p.getPaymentDate().equals(LocalDate.of(2025, 11, 1)))
                .findFirst()
                .orElseThrow(() -> new AssertionError("Nov 2025 payment not found"));

        assertEquals(0, new BigDecimal("47.50").compareTo(novPayment.getLateFee()));
    }

    @Test
    void allBorrowersFkRelationshipsResolved() {
        // Every loan account should have a valid borrower FK
        var accounts = modernAccountRepo.findAll();
        for (LoanAccount acct : accounts) {
            assertNotNull(acct.getBorrower(),
                    "Borrower FK should be resolved for account " + acct.getAccountNumber());
            assertNotNull(acct.getBorrower().getExternalId());
        }
    }

    @Test
    void allProductFkRelationshipsResolved() {
        // Every loan account should have a valid product FK
        var accounts = modernAccountRepo.findAll();
        for (LoanAccount acct : accounts) {
            assertNotNull(acct.getProduct(),
                    "Product FK should be resolved for account " + acct.getAccountNumber());
            assertNotNull(acct.getProduct().getCode());
        }
    }

    @Test
    void allPaymentLoanAccountFkResolved() {
        // Every payment should have a valid loan_account FK
        var payments = modernPaymentRepo.findAll();
        for (Payment pmt : payments) {
            assertNotNull(pmt.getLoanAccount(),
                    "Loan account FK should be resolved for payment " + pmt.getId());
            assertNotNull(pmt.getLoanAccount().getAccountNumber());
        }
    }

    @Test
    void condominiumPropertyTypeExpanded() {
        // LN-2020-00398 has property type CND → "Condominium"
        Optional<LoanAccount> opt = modernAccountRepo.findByAccountNumber("LN-2020-00398");
        assertTrue(opt.isPresent());
        assertEquals("Condominium", opt.get().getPropertyType());
    }

    @Test
    void townhousePropertyTypeExpanded() {
        // LN-2021-00567 has property type TWN → "Townhouse"
        Optional<LoanAccount> opt = modernAccountRepo.findByAccountNumber("LN-2021-00567");
        assertTrue(opt.isPresent());
        assertEquals("Townhouse", opt.get().getPropertyType());
    }
}
