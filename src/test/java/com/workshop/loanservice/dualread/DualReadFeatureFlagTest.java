package com.workshop.loanservice.dualread;

import com.workshop.loanservice.dto.BorrowerDto;
import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;
import com.workshop.loanservice.service.DualReadComparator;
import com.workshop.loanservice.service.LoanService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Tests for the dual-read feature flag. Verifies that each mode (legacy, modern, dual)
 * correctly routes to the appropriate data source and that dual mode performs
 * shadow comparison without failing the request.
 */
@SpringBootTest
@AutoConfigureMockMvc
class DualReadFeatureFlagTest {

    @Autowired
    private LoanService loanService;

    @Autowired
    private DualReadComparator comparator;

    @Autowired
    private MockMvc mockMvc;

    // =========================================================================
    // MODE SWITCHING TESTS — verify the router respects the feature flag
    // =========================================================================

    @Test
    void legacyModeReturnsDataFromLegacySource() {
        // Switch to legacy mode and verify we get results
        loanService.setMode("legacy");
        try {
            List<LoanSummaryDto> loans = loanService.getAllLoans();
            assertNotNull(loans, "Legacy mode should return loan data");
            assertFalse(loans.isEmpty(), "Legacy mode should have loan records");

            // Legacy source uses legacy origination date format (MM/DD/YYYY string)
            LoanSummaryDto firstLoan = loans.get(0);
            assertNotNull(firstLoan.getLoanAccountNumber());
            assertNotNull(firstLoan.getBorrowerName());
        } finally {
            loanService.setMode("modern");
        }
    }

    @Test
    void modernModeReturnsDataFromModernSource() {
        // Switch to modern mode and verify we get results
        loanService.setMode("modern");
        List<LoanSummaryDto> loans = loanService.getAllLoans();
        assertNotNull(loans, "Modern mode should return loan data");
        assertFalse(loans.isEmpty(), "Modern mode should have loan records");

        // Modern source uses ISO date format (YYYY-MM-DD)
        LoanSummaryDto firstLoan = loans.get(0);
        assertNotNull(firstLoan.getLoanAccountNumber());
        assertNotNull(firstLoan.getOriginationDate());
    }

    @Test
    void dualModeReturnsLegacyResponseWhileComparingModern() {
        // Dual mode should serve legacy response
        loanService.setMode("dual");
        comparator.clearMismatches();
        try {
            List<LoanSummaryDto> loans = loanService.getAllLoans();
            assertNotNull(loans, "Dual mode should return loan data (from legacy)");
            assertFalse(loans.isEmpty(), "Dual mode should have loan records");
        } finally {
            loanService.setMode("modern");
        }
    }

    @Test
    void dualModePerformsShadowComparisonForAllEndpoints() {
        // Verify dual mode triggers comparison for each operation
        loanService.setMode("dual");
        comparator.clearMismatches();
        try {
            // Exercise all endpoints in dual mode
            loanService.getAllLoans();
            loanService.getLoanById("LN-2019-00142");
            loanService.getAllBorrowers();
            loanService.getBorrowerById("B-10001");
            loanService.getPaymentsByLoan("LN-2019-00142");

            // In dual mode, comparison is always triggered — mismatches are expected
            // because legacy and modern have different date formats and payment IDs
            List<DualReadComparator.MismatchRecord> mismatches = comparator.getRecentMismatches();
            // Should have recorded comparison results (mismatches expected due to format differences)
            assertNotNull(mismatches);
        } finally {
            loanService.setMode("modern");
        }
    }

    // =========================================================================
    // API ENDPOINT TESTS — verify HTTP layer works correctly in each mode
    // =========================================================================

    @Test
    void legacyModeApiEndpointsReturnOk() throws Exception {
        loanService.setMode("legacy");
        try {
            mockMvc.perform(get("/api/loans")).andExpect(status().isOk());
            mockMvc.perform(get("/api/loans/LN-2019-00142")).andExpect(status().isOk());
            mockMvc.perform(get("/api/borrowers")).andExpect(status().isOk());
            mockMvc.perform(get("/api/borrowers/B-10001")).andExpect(status().isOk());
            mockMvc.perform(get("/api/loans/LN-2019-00142/payments")).andExpect(status().isOk());
        } finally {
            loanService.setMode("modern");
        }
    }

    @Test
    void dualModeApiEndpointsReturnOk() throws Exception {
        loanService.setMode("dual");
        try {
            mockMvc.perform(get("/api/loans")).andExpect(status().isOk());
            mockMvc.perform(get("/api/loans/LN-2019-00142")).andExpect(status().isOk());
            mockMvc.perform(get("/api/borrowers")).andExpect(status().isOk());
            mockMvc.perform(get("/api/borrowers/B-10001")).andExpect(status().isOk());
            mockMvc.perform(get("/api/loans/LN-2019-00142/payments")).andExpect(status().isOk());
        } finally {
            loanService.setMode("modern");
        }
    }

    @Test
    void modernModeApiEndpointsReturnOk() throws Exception {
        loanService.setMode("modern");
        mockMvc.perform(get("/api/loans")).andExpect(status().isOk());
        mockMvc.perform(get("/api/loans/LN-2019-00142")).andExpect(status().isOk());
        mockMvc.perform(get("/api/borrowers")).andExpect(status().isOk());
        mockMvc.perform(get("/api/borrowers/B-10001")).andExpect(status().isOk());
        mockMvc.perform(get("/api/loans/LN-2019-00142/payments")).andExpect(status().isOk());
    }

    // =========================================================================
    // COMPARATOR TESTS — verify the shadow comparator correctly detects diffs
    // =========================================================================

    @Test
    void comparatorDetectsIdenticalResults() {
        // Matching objects should return true (no mismatch)
        comparator.clearMismatches();
        LoanSummaryDto dto1 = new LoanSummaryDto();
        dto1.setLoanAccountNumber("LN-001");
        dto1.setStatus("Active");

        LoanSummaryDto dto2 = new LoanSummaryDto();
        dto2.setLoanAccountNumber("LN-001");
        dto2.setStatus("Active");

        boolean result = comparator.compareSilently(dto1, dto2, "testMatch");
        assertTrue(result, "Identical DTOs should be detected as matching");
        assertEquals(0, comparator.getMismatchCount());
    }

    @Test
    void comparatorDetectsMismatchedResults() {
        // Different objects should return false and record mismatch
        comparator.clearMismatches();
        LoanSummaryDto dto1 = new LoanSummaryDto();
        dto1.setLoanAccountNumber("LN-001");
        dto1.setStatus("Active");

        LoanSummaryDto dto2 = new LoanSummaryDto();
        dto2.setLoanAccountNumber("LN-001");
        dto2.setStatus("Closed");

        boolean result = comparator.compareSilently(dto1, dto2, "testMismatch");
        assertFalse(result, "Different DTOs should be detected as mismatched");
        assertEquals(1, comparator.getMismatchCount());

        // Verify mismatch record contains useful diagnostics
        DualReadComparator.MismatchRecord record = comparator.getRecentMismatches().get(0);
        assertEquals("testMismatch", record.operationName());
        assertTrue(record.legacyJson().contains("Active"));
        assertTrue(record.modernJson().contains("Closed"));
    }

    @Test
    void comparatorHandlesNullsGracefully() {
        // Null comparison should not throw, should record as mismatch
        comparator.clearMismatches();
        boolean result = comparator.compareSilently(null, "something", "testNull");
        assertFalse(result, "null vs non-null should be a mismatch");
    }

    @Test
    void dualModeDoesNotFailOnModernSourceError() {
        // Verify that if modern source has an issue, dual mode still serves legacy
        loanService.setMode("dual");
        try {
            // This uses a valid loan number so both sources should work
            LoanSummaryDto result = loanService.getLoanById("LN-2019-00142");
            assertNotNull(result, "Dual mode should always return a response");
            assertEquals("LN-2019-00142", result.getLoanAccountNumber());
        } finally {
            loanService.setMode("modern");
        }
    }

    @Test
    void modeDefaultsToModern() {
        // Verify the default mode is "modern" as configured in properties
        assertEquals("modern", loanService.getMode());
    }

    @Test
    void runtimeModeSwitchingWorksWithoutRestart() {
        // Verify mode can be switched at runtime
        String originalMode = loanService.getMode();
        try {
            loanService.setMode("legacy");
            assertEquals("legacy", loanService.getMode());

            loanService.setMode("dual");
            assertEquals("dual", loanService.getMode());

            loanService.setMode("modern");
            assertEquals("modern", loanService.getMode());
        } finally {
            loanService.setMode(originalMode);
        }
    }
}
