package com.workshop.loanservice.controller;

import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;
import com.workshop.loanservice.service.LoanService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * REST controller exposing loan endpoints under {@code /api/loans}.
 */
@RestController
@RequestMapping("/api/loans")
public class LoanController {

    private final LoanService loanService;

    public LoanController(LoanService loanService) {
        this.loanService = loanService;
    }

    /**
     * Retrieves all loan summaries.
     *
     * @return list of all loan summaries
     */
    @GetMapping
    public List<LoanSummaryDto> getAllLoans() {
        return loanService.getAllLoans();
    }

    /**
     * Retrieves a single loan summary by account number.
     *
     * @param id the loan account number
     * @return the loan summary
     */
    @GetMapping("/{id}")
    public LoanSummaryDto getLoan(@PathVariable String id) {
        return loanService.getLoanById(id);
    }

    /**
     * Retrieves payment history for a specific loan.
     *
     * @param loanId the loan account number
     * @return list of payments for the loan
     */
    @GetMapping("/{loanId}/payments")
    public List<PaymentDto> getPayments(@PathVariable String loanId) {
        return loanService.getPaymentsByLoan(loanId);
    }
}
