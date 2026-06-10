package com.workshop.loanservice.repository;

import com.workshop.loanservice.entity.Borrower;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

/**
 * Modern repository for the normalized borrowers table.
 * Provides lookups by external_id (legacy BORR_ID) to preserve API contract.
 */
@Repository
public interface BorrowerRepository extends JpaRepository<Borrower, Long> {

    Optional<Borrower> findByExternalId(String externalId);
}
