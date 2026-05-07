package com.workshop.loanservice.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest
class LoanServiceTest {

    @Autowired
    private LoanService loanService;

    @Test
    @DisplayName("parseLegacyAmount handles null gracefully")
    void parseLegacyAmountNull() {
        assertEquals(BigDecimal.ZERO, loanService.parseLegacyAmount(null));
    }

    @Test
    @DisplayName("parseLegacyAmount handles blank gracefully")
    void parseLegacyAmountBlank() {
        assertEquals(BigDecimal.ZERO, loanService.parseLegacyAmount(""));
    }

    @Test
    @DisplayName("parseLegacyAmount handles comma-formatted amounts")
    void parseLegacyAmountCommas() {
        assertEquals(new BigDecimal("285000"), loanService.parseLegacyAmount("285,000"));
        assertEquals(new BigDecimal("1487.02"), loanService.parseLegacyAmount("1,487.02"));
    }

    @Test
    @DisplayName("parseLegacyAmount returns ZERO for invalid input instead of throwing")
    void parseLegacyAmountInvalid() {
        assertEquals(BigDecimal.ZERO, loanService.parseLegacyAmount("$285,000"));
        assertEquals(BigDecimal.ZERO, loanService.parseLegacyAmount("DECLINED"));
        assertEquals(BigDecimal.ZERO, loanService.parseLegacyAmount("12.34.56"));
    }

    @Test
    @DisplayName("parseLegacyDecimal handles percentage signs gracefully")
    void parseLegacyDecimalInvalid() {
        assertEquals(BigDecimal.ZERO, loanService.parseLegacyDecimal("4.75%"));
        assertEquals(BigDecimal.ZERO, loanService.parseLegacyDecimal("N/A"));
    }

    @Test
    @DisplayName("parseLegacyDecimal handles valid decimals")
    void parseLegacyDecimalValid() {
        assertEquals(new BigDecimal("4.750"), loanService.parseLegacyDecimal("4.750"));
        assertEquals(new BigDecimal("82.5"), loanService.parseLegacyDecimal("82.5"));
    }

    @Test
    @DisplayName("parseLegacyInteger returns null for invalid input instead of throwing")
    void parseLegacyIntegerInvalid() {
        assertNull(loanService.parseLegacyInteger("N/A"));
        assertNull(loanService.parseLegacyInteger("7A5"));
        assertNull(loanService.parseLegacyInteger(null));
        assertNull(loanService.parseLegacyInteger(""));
    }

    @Test
    @DisplayName("parseLegacyInteger handles valid integers")
    void parseLegacyIntegerValid() {
        assertEquals(745, loanService.parseLegacyInteger("745"));
        assertEquals(360, loanService.parseLegacyInteger("360"));
        assertEquals(0, loanService.parseLegacyInteger("0"));
    }

    @Test
    @DisplayName("getAllLoans returns loans with data quality warnings for known anomalies")
    void getAllLoansIncludesDataQualityWarnings() {
        var loans = loanService.getAllLoans();
        assertFalse(loans.isEmpty());

        // Loan LN-2018-00089 should have delinquency warning
        var delinquentLoan = loans.stream()
                .filter(l -> "LN-2018-00089".equals(l.getLoanAccountNumber()))
                .findFirst()
                .orElseThrow();
        assertTrue(delinquentLoan.getStatus().contains("Delinquent"));
        assertNotNull(delinquentLoan.getDataQualityWarnings());
        assertTrue(delinquentLoan.getDataQualityWarnings().stream()
                .anyMatch(w -> w.contains("delinquency days")));
    }

    @Test
    @DisplayName("getAllLoans detects SSN-phone corruption in all records")
    void getAllLoansDetectsSsnCorruption() {
        var loans = loanService.getAllLoans();
        // All 5 loan records have SSN_LST4 matching phone number last-4
        long corruptedCount = loans.stream()
                .filter(l -> l.getDataQualityWarnings() != null)
                .filter(l -> l.getDataQualityWarnings().stream()
                        .anyMatch(w -> w.contains("SSN last-4")))
                .count();
        assertEquals(5, corruptedCount);
    }

    @Test
    @DisplayName("getPaymentsByLoan detects payment sum mismatches")
    void getPaymentsDetectsSumMismatch() {
        var payments = loanService.getPaymentsByLoan("LN-2019-00142");
        assertFalse(payments.isEmpty());

        // Both payments for this loan have component sum mismatch
        long mismatchCount = payments.stream()
                .filter(p -> p.getRecalculatedTotal() != null)
                .count();
        assertEquals(2, mismatchCount);

        // Verify recalculated total is set for mismatched payments
        var payment = payments.stream()
                .filter(p -> "PMT-2025120001".equals(p.getPaymentId()))
                .findFirst()
                .orElseThrow();
        assertNotNull(payment.getRecalculatedTotal());
        assertEquals(new BigDecimal("1887.02"), payment.getRecalculatedTotal());
    }

    @Test
    @DisplayName("getPaymentsByLoan passes validation for consistent payments")
    void getPaymentsPassesForConsistentData() {
        var payments = loanService.getPaymentsByLoan("LN-2020-00398");
        assertFalse(payments.isEmpty());

        // Both payments for this loan have matching component sums
        long mismatchCount = payments.stream()
                .filter(p -> p.getRecalculatedTotal() != null)
                .count();
        assertEquals(0, mismatchCount);
    }

    @Test
    @DisplayName("getAllBorrowers processes all records without exceptions")
    void getAllBorrowersNoExceptions() {
        var borrowers = loanService.getAllBorrowers();
        assertEquals(5, borrowers.size());
        borrowers.forEach(b -> {
            assertNotNull(b.getFullName());
            assertFalse(b.getFullName().contains("null"));
        });
    }
}
