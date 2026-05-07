package com.workshop.loanservice.repository;

import com.workshop.loanservice.entity.LegacyBorrower;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

/**
 * Spring Data JPA repository for the legacy {@code CDW_BORR_MSTR} table.
 * This is a migration target — to be replaced by a modern repository
 * backed by the normalized schema.
 */
@Repository
public interface LegacyBorrowerRepository extends JpaRepository<LegacyBorrower, String> {

    /**
     * Finds borrowers by their status code (e.g., "ACT" for active).
     *
     * @param statusCode the legacy status code
     * @return list of matching borrowers
     */
    List<LegacyBorrower> findByStatusCode(String statusCode);

    /**
     * Case-insensitive search for borrowers by last name.
     *
     * @param lastName the last name to search for
     * @return list of matching borrowers
     */
    List<LegacyBorrower> findByLastNameIgnoreCase(String lastName);
}
