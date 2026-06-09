package com.workshop.loanservice.service;

import com.workshop.loanservice.dto.BorrowerDto;
import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Integration tests that run the LoanService against the actual legacy seed data
 * to verify that data validation and safe parsing produce correct results despite
 * known data quality anomalies.
 */
@SpringBootTest
class LoanServiceValidationTest {

    @Autowired
    private LoanService loanService;

    @Test
    @DisplayName("getAllLoans returns results without crashing despite legacy data anomalies")
    void getAllLoansHandlesAnomalies() {
        List<LoanSummaryDto> loans = loanService.getAllLoans();

        assertThat(loans).hasSize(5);
        // All loans should have non-null required fields populated by safe parsing
        loans.forEach(loan -> {
            assertThat(loan.getLoanAccountNumber()).isNotBlank();
            assertThat(loan.getBorrowerName()).doesNotContain("null");
            assertThat(loan.getOriginalAmount()).isGreaterThan(BigDecimal.ZERO);
            assertThat(loan.getCurrentBalance()).isGreaterThan(BigDecimal.ZERO);
            assertThat(loan.getInterestRate()).isGreaterThan(BigDecimal.ZERO);
            assertThat(loan.getStatus()).isNotBlank();
        });
    }

    @Test
    @DisplayName("Delinquent loan exposes delinquencyDays field (ANO-003 fix)")
    void delinquentLoanExposesDelinquencyDays() {
        // LN-2018-00089 has 15 days delinquency — verify it's now visible
        LoanSummaryDto loan = loanService.getLoanById("LN-2018-00089");

        assertThat(loan.getDelinquencyDays()).isEqualTo(15);
        assertThat(loan.getStatus()).isEqualTo("Active"); // Raw status still shows Active
    }

    @Test
    @DisplayName("Non-delinquent loan has zero delinquency days")
    void nonDelinquentLoanHasZeroDays() {
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");

        assertThat(loan.getDelinquencyDays()).isEqualTo(0);
    }

    @Test
    @DisplayName("Safe amount parsing handles commas correctly")
    void safeAmountParsingHandlesCommas() {
        // LN-2021-00567 has originalAmount "525,000"
        LoanSummaryDto loan = loanService.getLoanById("LN-2021-00567");

        assertThat(loan.getOriginalAmount()).isEqualByComparingTo(new BigDecimal("525000"));
        assertThat(loan.getCurrentBalance()).isEqualByComparingTo(new BigDecimal("498123.78"));
    }

    @Test
    @DisplayName("Payment amounts parse correctly from legacy format")
    void paymentAmountsParsedCorrectly() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2020-00398");

        assertThat(payments).isNotEmpty();
        // Verify the December 2025 payment for LN-2020-00398
        PaymentDto dec = payments.stream()
                .filter(p -> "PMT-2025120002".equals(p.getPaymentId()))
                .findFirst()
                .orElseThrow();
        assertThat(dec.getTotalAmount()).isEqualByComparingTo(new BigDecimal("2924.18"));
        assertThat(dec.getPrincipalAmount()).isEqualByComparingTo(new BigDecimal("1842.56"));
        assertThat(dec.getInterestAmount()).isEqualByComparingTo(new BigDecimal("815.50"));
        assertThat(dec.getEscrowAmount()).isEqualByComparingTo(new BigDecimal("266.12"));
    }

    @Test
    @DisplayName("Borrower with null middle initial does not produce 'null' in name")
    void nullMiddleInitialHandledGracefully() {
        // B-10005 Robert Williams has NULL middle initial
        BorrowerDto borrower = loanService.getBorrowerById("B-10005");

        assertThat(borrower.getFullName()).isEqualTo("Robert Williams");
        assertThat(borrower.getFullName()).doesNotContain("null");
    }

    @Test
    @DisplayName("All borrowers have valid credit scores parsed from strings")
    void creditScoresParsedCorrectly() {
        List<BorrowerDto> borrowers = loanService.getAllBorrowers();

        borrowers.forEach(b -> {
            assertThat(b.getCreditScore()).isNotNull();
            assertThat(b.getCreditScore()).isBetween(300, 850);
        });
    }

    @Test
    @DisplayName("Dates are converted to ISO format from legacy MM/DD/YYYY")
    void datesConvertedToIsoFormat() {
        // LN-2019-00142 has origination date "02/15/2019"
        LoanSummaryDto loan = loanService.getLoanById("LN-2019-00142");

        // Should be converted to ISO format
        assertThat(loan.getOriginationDate()).isEqualTo("2019-02-15");
    }

    @Test
    @DisplayName("Payment dates are converted to ISO format")
    void paymentDatesConvertedToIso() {
        List<PaymentDto> payments = loanService.getPaymentsByLoan("LN-2019-00142");

        assertThat(payments).isNotEmpty();
        // Verify ISO date format for payment date
        payments.forEach(p ->
                assertThat(p.getPaymentDate()).matches("\\d{4}-\\d{2}-\\d{2}"));
    }

    @Test
    @DisplayName("Service does not crash on malformed amount - returns zero fallback")
    void malformedAmountReturnsFallback() {
        // Directly test the parseLegacyAmount with bad data
        BigDecimal result = loanService.parseLegacyAmount("$invalid");
        assertThat(result).isEqualByComparingTo(BigDecimal.ZERO);
    }

    @Test
    @DisplayName("Service does not crash on malformed integer - returns null fallback")
    void malformedIntegerReturnsFallback() {
        Integer result = loanService.parseLegacyInteger("N/A");
        assertThat(result).isNull();
    }

    @Test
    @DisplayName("Date parsing fallback returns raw string for invalid date")
    void invalidDateReturnsFallback() {
        String result = loanService.parseLegacyDateToIso("99/99/9999");
        // Should return the original string as fallback
        assertThat(result).isEqualTo("99/99/9999");
    }
}
