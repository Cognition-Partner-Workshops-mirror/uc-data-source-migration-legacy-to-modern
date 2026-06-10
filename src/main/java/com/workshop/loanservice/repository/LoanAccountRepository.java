package com.workshop.loanservice.repository;

import com.workshop.loanservice.entity.LoanAccount;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

/**
 * Modern repository for the normalized loan_accounts table.
 * Provides lookups by account_number (used as the REST path parameter).
 */
@Repository
public interface LoanAccountRepository extends JpaRepository<LoanAccount, Long> {

    Optional<LoanAccount> findByAccountNumber(String accountNumber);

    List<LoanAccount> findByBorrowerId(Long borrowerId);
}
