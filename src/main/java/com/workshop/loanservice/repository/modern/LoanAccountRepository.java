package com.workshop.loanservice.repository.modern;

import com.workshop.loanservice.entity.modern.LoanAccount;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

/**
 * Repository for the modern loan_accounts table.
 * Uses FK relationship to borrower instead of denormalized borrower fields.
 */
@Repository
public interface LoanAccountRepository extends JpaRepository<LoanAccount, Long> {

    Optional<LoanAccount> findByAccountNumber(String accountNumber);

    List<LoanAccount> findByBorrowerId(Long borrowerId);

    List<LoanAccount> findByBorrowerExternalId(String externalId);

    List<LoanAccount> findByStatus(LoanAccount.Status status);
}
