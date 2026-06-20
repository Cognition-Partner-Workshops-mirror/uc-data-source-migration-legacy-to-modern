package com.workshop.loanservice.service;

import com.workshop.loanservice.dto.BorrowerDto;
import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;

import java.util.List;

/**
 * Common interface for loan data access — implemented by both the legacy
 * (all-VARCHAR CDW) and modern (normalized, typed) data sources.
 * The LoanService router delegates to the appropriate implementation
 * based on the datasource.mode feature flag.
 */
public interface LoanDataSource {

    /** Returns all loan summaries */
    List<LoanSummaryDto> getAllLoans();

    /** Returns a single loan by account number */
    LoanSummaryDto getLoanById(String loanAccountNumber);

    /** Returns all borrowers */
    List<BorrowerDto> getAllBorrowers();

    /** Returns a single borrower with attached loans */
    BorrowerDto getBorrowerById(String borrowerId);

    /** Returns payments for a loan account, ordered by date descending */
    List<PaymentDto> getPaymentsByLoan(String loanAccountNumber);
}
