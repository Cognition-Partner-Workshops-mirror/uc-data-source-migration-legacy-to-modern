package com.workshop.loanservice.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * Shadow comparator for dual-read mode. Compares legacy and modern data source
 * responses by serializing both to JSON and performing field-level diff.
 * Logs mismatches at WARN level for reconciliation monitoring without failing
 * the request — the primary source's response is always returned to the caller.
 *
 * In production, mismatch logs should feed into a dashboard for tracking
 * migration correctness before cutting over to the modern source.
 */
@Component
public class DualReadComparator {

    private static final Logger log = LoggerFactory.getLogger(DualReadComparator.class);

    private final ObjectMapper objectMapper;

    // Tracks mismatch count for monitoring/testing purposes
    private final List<MismatchRecord> recentMismatches = new ArrayList<>();

    public DualReadComparator() {
        this.objectMapper = new ObjectMapper();
        this.objectMapper.configure(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS, true);
    }

    /**
     * Compare legacy and modern responses, logging any differences.
     * Returns true if they match, false if mismatches were found.
     *
     * @param legacyResult  the result from legacy data source
     * @param modernResult  the result from modern data source
     * @param operationName name of the operation for logging context (e.g., "getAllLoans")
     * @param <T>           response type
     * @return true if results match, false otherwise
     */
    public <T> boolean compareSilently(T legacyResult, T modernResult, String operationName) {
        try {
            String legacyJson = objectMapper.writeValueAsString(legacyResult);
            String modernJson = objectMapper.writeValueAsString(modernResult);

            if (legacyJson.equals(modernJson)) {
                log.debug("DUAL-READ [{}]: Legacy and modern results match", operationName);
                return true;
            }

            // Log the mismatch with truncated payloads to avoid flooding logs
            String legacyTruncated = truncate(legacyJson, 500);
            String modernTruncated = truncate(modernJson, 500);

            log.warn("DUAL-READ MISMATCH [{}]: Legacy and modern results differ. "
                            + "Legacy: {} | Modern: {}",
                    operationName, legacyTruncated, modernTruncated);

            // Record mismatch for monitoring/testing
            synchronized (recentMismatches) {
                recentMismatches.add(new MismatchRecord(
                        operationName, legacyJson, modernJson, System.currentTimeMillis()));
                // Keep only last 100 mismatches to bound memory
                if (recentMismatches.size() > 100) {
                    recentMismatches.remove(0);
                }
            }

            return false;
        } catch (Exception e) {
            // Comparison failure should never break the request — log and move on
            log.error("DUAL-READ [{}]: Failed to compare results: {}", operationName, e.getMessage());
            return false;
        }
    }

    /**
     * Returns the count of recent mismatches (useful for health checks and tests).
     */
    public int getMismatchCount() {
        synchronized (recentMismatches) {
            return recentMismatches.size();
        }
    }

    /**
     * Returns recent mismatch records (useful for diagnostics and tests).
     */
    public List<MismatchRecord> getRecentMismatches() {
        synchronized (recentMismatches) {
            return new ArrayList<>(recentMismatches);
        }
    }

    /**
     * Clears mismatch records (useful for test isolation).
     */
    public void clearMismatches() {
        synchronized (recentMismatches) {
            recentMismatches.clear();
        }
    }

    /** Truncate a string to maxLen chars, appending "..." if truncated */
    private String truncate(String s, int maxLen) {
        if (s == null) return "null";
        if (s.length() <= maxLen) return s;
        return s.substring(0, maxLen) + "...";
    }

    /**
     * Record of a single mismatch event for diagnostics.
     */
    public record MismatchRecord(
            String operationName,
            String legacyJson,
            String modernJson,
            long timestampMillis
    ) {}
}
