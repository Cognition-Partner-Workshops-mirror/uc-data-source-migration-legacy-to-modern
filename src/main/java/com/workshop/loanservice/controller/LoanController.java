package com.workshop.loanservice.controller;

import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;
import com.workshop.loanservice.service.DualReadService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * Loan API controller — now uses DualReadService to support
 * legacy, modern, or dual-read mode based on the datasource.mode property.
 */
@RestController
@RequestMapping("/api/loans")
public class LoanController {

    private final DualReadService dualReadService;

    public LoanController(DualReadService dualReadService) {
        this.dualReadService = dualReadService;
    }

    @GetMapping
    public List<LoanSummaryDto> getAllLoans() {
        return dualReadService.getAllLoans();
    }

    @GetMapping("/{id}")
    public LoanSummaryDto getLoan(@PathVariable String id) {
        return dualReadService.getLoanById(id);
    }

    @GetMapping("/{loanId}/payments")
    public List<PaymentDto> getPayments(@PathVariable String loanId) {
        return dualReadService.getPaymentsByLoan(loanId);
    }
}
