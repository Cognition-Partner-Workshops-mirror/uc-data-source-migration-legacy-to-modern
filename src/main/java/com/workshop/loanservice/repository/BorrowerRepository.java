package com.workshop.loanservice.repository;

import com.workshop.loanservice.entity.Borrower;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

/**
 * Repository for modern borrower entity with proper typed queries.
 */
@Repository
public interface BorrowerRepository extends JpaRepository<Borrower, Long> {

    Optional<Borrower> findByExternalId(String externalId);

    List<Borrower> findByStatus(String status);

    List<Borrower> findByLastNameIgnoreCase(String lastName);
}
