package com.workshop.loanservice.repository;

import com.workshop.loanservice.entity.LegacyPayment;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

/**
 * Spring Data JPA repository for the legacy {@code CDW_PMT_HIST} table.
 */
@Repository
public interface LegacyPaymentRepository extends JpaRepository<LegacyPayment, String> {

    /**
     * Finds all payments for a loan.
     *
     * @param loanAccountNumber the loan account number
     * @return list of payments for the loan
     */
    List<LegacyPayment> findByLoanAccountNumber(String loanAccountNumber);

    /**
     * Finds payments for a loan, ordered by most recent first.
     *
     * @param loanAccountNumber the loan account number
     * @return list of payments sorted by payment date descending
     */
    List<LegacyPayment> findByLoanAccountNumberOrderByPaymentDateDesc(String loanAccountNumber);
}
