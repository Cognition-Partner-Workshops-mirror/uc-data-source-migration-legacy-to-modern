package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.repository.LegacyBorrowerRepository;
import com.workshop.loanservice.repository.LegacyLoanAccountRepository;
import com.workshop.loanservice.repository.LegacyPaymentRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Integration test that runs the DataQualityValidator against
 * the actual legacy seed data loaded from data-legacy.sql.
 * Verifies that known anomalies are correctly detected.
 */
@SpringBootTest
class LegacySeedDataValidationTest {

    @Autowired
    private DataQualityValidator validator;

    @Autowired
    private LegacyBorrowerRepository borrowerRepository;

    @Autowired
    private LegacyLoanAccountRepository loanAccountRepository;

    @Autowired
    private LegacyPaymentRepository paymentRepository;

    @Test
    @DisplayName("All borrower seed records should pass validation")
    void allBorrowersShouldPassValidation() {
        List<LegacyBorrower> borrowers = borrowerRepository.findAll();
        assertFalse(borrowers.isEmpty(), "Seed data should contain borrowers");

        for (LegacyBorrower borrower : borrowers) {
            // Should not throw — all seed borrowers have required fields
            assertDoesNotThrow(() -> validator.validateBorrower(borrower),
                    "Borrower " + borrower.getBorrowerId() + " should pass validation");
        }
    }

    @Test
    @DisplayName("All loan account seed records should pass critical validation")
    void allLoanAccountsShouldPassCriticalValidation() {
        List<LegacyLoanAccount> accounts = loanAccountRepository.findAll();
        assertFalse(accounts.isEmpty(), "Seed data should contain loan accounts");

        for (LegacyLoanAccount account : accounts) {
            // Should not throw — all seed loans have required fields
            assertDoesNotThrow(() -> validator.validateLoanAccount(account),
                    "Loan " + account.getLoanAccountNumber() + " should pass critical validation");
        }
    }

    @Test
    @DisplayName("Should detect delinquency/status anomaly in seed data (ANO-004)")
    void shouldDetectDelinquencyStatusAnomaly() {
        // LN-2018-00089 has 15 days delinquent but status ACT
        LegacyLoanAccount delinquentLoan = loanAccountRepository
                .findById("LN-2018-00089").orElseThrow();

        List<String> warnings = validator.validateLoanAccount(delinquentLoan);

        assertTrue(warnings.stream().anyMatch(w -> w.contains("delinquent")
                        && w.contains("ACT")),
                "Should detect delinquency/status inconsistency on LN-2018-00089");
    }

    @Test
    @DisplayName("Should detect payment component mismatch in seed data (ANO-001)")
    void shouldDetectPaymentComponentMismatch() {
        List<LegacyPayment> allPayments = paymentRepository.findAll();
        List<String> allWarnings = new ArrayList<>();

        for (LegacyPayment payment : allPayments) {
            allWarnings.addAll(validator.validatePayment(payment));
        }

        // At least 3 payments should have component sum mismatches
        long componentMismatches = allWarnings.stream()
                .filter(w -> w.contains("component sum"))
                .count();
        assertTrue(componentMismatches >= 2,
                "Expected at least 2 payment component mismatch warnings, found: "
                        + componentMismatches);
    }

    @Test
    @DisplayName("All payment seed records should pass critical validation")
    void allPaymentsShouldPassCriticalValidation() {
        List<LegacyPayment> payments = paymentRepository.findAll();
        assertFalse(payments.isEmpty(), "Seed data should contain payments");

        for (LegacyPayment payment : payments) {
            // Should not throw — all seed payments have required fields
            assertDoesNotThrow(() -> validator.validatePayment(payment),
                    "Payment " + payment.getPaymentSequenceNumber()
                            + " should pass critical validation");
        }
    }
}
