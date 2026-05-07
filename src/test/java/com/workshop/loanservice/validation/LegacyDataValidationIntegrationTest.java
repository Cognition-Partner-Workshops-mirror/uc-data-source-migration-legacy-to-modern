package com.workshop.loanservice.validation;

import com.workshop.loanservice.service.LoanService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Integration test that validates the actual legacy seed data
 * and verifies that known anomalies are detected.
 */
@SpringBootTest
class LegacyDataValidationIntegrationTest {

    @Autowired
    private LoanService loanService;

    @Test
    void validateAllData_detectsKnownAnomalies() {
        List<ValidationWarning> warnings = loanService.validateAllData();

        assertFalse(warnings.isEmpty(), "Expected data anomalies in legacy seed data");

        // ANO-001: Payment component sum mismatch
        assertTrue(warnings.stream().anyMatch(w ->
                        "COMPONENT_SUM_MISMATCH".equals(w.getAnomalyType())),
                "Should detect payment component sum mismatches");

        long mismatchCount = warnings.stream()
                .filter(w -> "COMPONENT_SUM_MISMATCH".equals(w.getAnomalyType()))
                .count();
        assertEquals(3, mismatchCount, "Should find exactly 3 payment component mismatches");

        // ANO-002: SSN last-4 contains phone digits
        assertTrue(warnings.stream().anyMatch(w ->
                        "DATA_CROSS_CONTAMINATION".equals(w.getAnomalyType())),
                "Should detect SSN/phone cross-contamination");

        long crossContaminationCount = warnings.stream()
                .filter(w -> "DATA_CROSS_CONTAMINATION".equals(w.getAnomalyType()))
                .count();
        assertEquals(5, crossContaminationCount,
                "All 5 loan records should have SSN/phone cross-contamination");

        // ANO-006: Delinquency/status inconsistency
        assertTrue(warnings.stream().anyMatch(w ->
                        "STATUS_INCONSISTENCY".equals(w.getAnomalyType())),
                "Should detect delinquency/status inconsistency for LN-2018-00089");
    }

    @Test
    void validateAllData_apiEndpointsStillWork() {
        // Verify that the validation does not break normal API operations
        assertDoesNotThrow(() -> loanService.getAllLoans());
        assertDoesNotThrow(() -> loanService.getAllBorrowers());
        assertDoesNotThrow(() -> loanService.getLoanById("LN-2019-00142"));
        assertDoesNotThrow(() -> loanService.getBorrowerById("B-10001"));
        assertDoesNotThrow(() -> loanService.getPaymentsByLoan("LN-2019-00142"));
    }

    @Test
    void validateAllData_safeParsingDoesNotCrashOnBadData() {
        // The validator should handle all the legacy data without throwing exceptions
        assertDoesNotThrow(() -> loanService.validateAllData());
    }
}
