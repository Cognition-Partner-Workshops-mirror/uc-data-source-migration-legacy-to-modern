package com.workshop.loanservice.repository.modern;

import com.workshop.loanservice.entity.modern.Borrower;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

/**
 * Repository for the modern borrowers table.
 * Uses Long (auto-increment) primary key instead of legacy string ID.
 */
@Repository
public interface BorrowerRepository extends JpaRepository<Borrower, Long> {

    Optional<Borrower> findByExternalId(String externalId);
}
