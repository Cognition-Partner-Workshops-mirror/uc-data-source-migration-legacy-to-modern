package com.workshop.loanservice.service;

import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyLoanProduct;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.repository.LegacyBorrowerRepository;
import com.workshop.loanservice.repository.LegacyLoanAccountRepository;
import com.workshop.loanservice.repository.LegacyLoanProductRepository;
import com.workshop.loanservice.repository.LegacyPaymentRepository;
import com.workshop.loanservice.validation.DataQualityValidator;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest
class ValidatingLoanServiceTest {

    @Autowired
    private ValidatingLoanService validatingLoanService;

    @Test
    @DisplayName("Safe amount parsing handles dollar signs gracefully")
    void safeParseAmountWithDollarSign() {
        BigDecimal result = validatingLoanService.safeParseAmount("$285,000", "TEST", "rec-1");
        assertEquals(BigDecimal.ZERO, result);
    }

    @Test
    @DisplayName("Safe amount parsing handles 'N/A' gracefully")
    void safeParseAmountWithNA() {
        BigDecimal result = validatingLoanService.safeParseAmount("N/A", "TEST", "rec-1");
        assertEquals(BigDecimal.ZERO, result);
    }

    @Test
    @DisplayName("Safe amount parsing handles valid comma-formatted amounts")
    void safeParseAmountValid() {
        BigDecimal result = validatingLoanService.safeParseAmount("285,000", "TEST", "rec-1");
        assertEquals(new BigDecimal("285000"), result);
    }

    @Test
    @DisplayName("Safe amount parsing handles decimal values with commas")
    void safeParseAmountDecimal() {
        BigDecimal result = validatingLoanService.safeParseAmount("1,487.02", "TEST", "rec-1");
        assertEquals(new BigDecimal("1487.02"), result);
    }

    @Test
    @DisplayName("Safe amount parsing handles null")
    void safeParseAmountNull() {
        BigDecimal result = validatingLoanService.safeParseAmount(null, "TEST", "rec-1");
        assertEquals(BigDecimal.ZERO, result);
    }

    @Test
    @DisplayName("Safe amount parsing handles blank string")
    void safeParseAmountBlank() {
        BigDecimal result = validatingLoanService.safeParseAmount("   ", "TEST", "rec-1");
        assertEquals(BigDecimal.ZERO, result);
    }

    @Test
    @DisplayName("Safe integer parsing handles non-numeric values")
    void safeParseIntegerNonNumeric() {
        Integer result = validatingLoanService.safeParseInteger("N/A", "TEST", "rec-1");
        assertNull(result);
    }

    @Test
    @DisplayName("Safe integer parsing handles valid values")
    void safeParseIntegerValid() {
        Integer result = validatingLoanService.safeParseInteger("745", "TEST", "rec-1");
        assertEquals(745, result);
    }

    @Test
    @DisplayName("Safe decimal parsing handles percent suffix")
    void safeParseDecimalPercent() {
        BigDecimal result = validatingLoanService.safeParseDecimal("4.75%", "TEST", "rec-1");
        assertEquals(BigDecimal.ZERO, result);
    }

    @Test
    @DisplayName("Safe decimal parsing handles valid values")
    void safeParseDecimalValid() {
        BigDecimal result = validatingLoanService.safeParseDecimal("4.750", "TEST", "rec-1");
        assertEquals(new BigDecimal("4.750"), result);
    }

    @Test
    @DisplayName("getAllLoansValidated returns results from seed data without crashing")
    void getAllLoansValidated() {
        List<LoanSummaryDto> loans = validatingLoanService.getAllLoansValidated();
        assertNotNull(loans);
        assertFalse(loans.isEmpty());
        assertEquals(5, loans.size());
    }

    @Test
    @DisplayName("getLoanByIdValidated returns loan details")
    void getLoanByIdValidated() {
        LoanSummaryDto loan = validatingLoanService.getLoanByIdValidated("LN-2019-00142");
        assertNotNull(loan);
        assertEquals("LN-2019-00142", loan.getLoanAccountNumber());
        assertEquals("James Mitchell", loan.getBorrowerName());
        assertEquals("Active", loan.getStatus());
    }

    @Test
    @DisplayName("getPaymentsByLoanValidated filters out non-reconciling payments")
    void getPaymentsByLoanValidatedFiltersNonReconciling() {
        // LN-2019-00142 has payments with $400 reconciliation discrepancy (CRITICAL)
        List<PaymentDto> payments = validatingLoanService.getPaymentsByLoanValidated("LN-2019-00142");
        assertNotNull(payments);
        // Both payments have component sums that don't match total — filtered as CRITICAL
        assertTrue(payments.isEmpty(), "Non-reconciling payments should be filtered out");
    }

    @Test
    @DisplayName("getPaymentsByLoanValidated returns reconciling payments")
    void getPaymentsByLoanValidatedReturnsValid() {
        // LN-2020-00398 has payments where components sum correctly
        List<PaymentDto> payments = validatingLoanService.getPaymentsByLoanValidated("LN-2020-00398");
        assertNotNull(payments);
        assertFalse(payments.isEmpty());
        assertEquals(2, payments.size());
    }

    @Test
    @DisplayName("getAllBorrowersValidated returns all valid borrowers")
    void getAllBorrowersValidated() {
        var borrowers = validatingLoanService.getAllBorrowersValidated();
        assertNotNull(borrowers);
        assertEquals(5, borrowers.size());
    }

    @Test
    @DisplayName("getLoanByIdValidated throws for non-existent loan")
    void getLoanByIdNotFound() {
        assertThrows(RuntimeException.class, () ->
                validatingLoanService.getLoanByIdValidated("NONEXISTENT"));
    }
}
