package com.workshop.loanservice.repository;

import com.workshop.loanservice.entity.Payment;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

/**
 * Modern repository for the normalized payments table.
 * Queries by loan_account_id FK (resolved from account_number at service layer).
 */
@Repository
public interface PaymentRepository extends JpaRepository<Payment, Long> {

    List<Payment> findByLoanAccountIdOrderByPaymentDateDesc(Long loanAccountId);

    List<Payment> findByLoanAccountAccountNumberOrderByPaymentDateDesc(String accountNumber);
}
