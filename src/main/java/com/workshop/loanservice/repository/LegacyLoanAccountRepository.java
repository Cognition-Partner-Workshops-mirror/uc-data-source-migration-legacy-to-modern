package com.workshop.loanservice.repository;

import com.workshop.loanservice.entity.LegacyLoanAccount;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

/**
 * Spring Data JPA repository for the legacy {@code CDW_LN_ACCT} table.
 */
@Repository
public interface LegacyLoanAccountRepository extends JpaRepository<LegacyLoanAccount, String> {

    /**
     * Finds all loan accounts for a given borrower.
     *
     * @param borrowerId the borrower identifier
     * @return list of loan accounts belonging to the borrower
     */
    List<LegacyLoanAccount> findByBorrowerId(String borrowerId);

    /**
     * Finds loan accounts by status code.
     *
     * @param statusCode the legacy status code
     * @return list of matching loan accounts
     */
    List<LegacyLoanAccount> findByStatusCode(String statusCode);

    /**
     * Finds loan accounts by product code.
     *
     * @param productCode the legacy product code
     * @return list of matching loan accounts
     */
    List<LegacyLoanAccount> findByProductCode(String productCode);
}
