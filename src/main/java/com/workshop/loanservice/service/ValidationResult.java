package com.workshop.loanservice.service;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Holds validation warnings and errors collected during legacy data ingestion.
 * Each entry records the anomaly type and a human-readable message.
 */
public class ValidationResult {

    /** Severity levels aligned with the Data Anomaly Report (docs/DATA_ANOMALY_REPORT.md). */
    public enum Severity { CRITICAL, HIGH, MEDIUM, LOW }

    /** A single validation finding. */
    public record Finding(Severity severity, String anomalyId, String message) {}

    private final List<Finding> findings = new ArrayList<>();

    /** Record a validation finding. */
    public void addFinding(Severity severity, String anomalyId, String message) {
        findings.add(new Finding(severity, anomalyId, message));
    }

    /** True if any CRITICAL or HIGH findings were recorded. */
    public boolean hasErrors() {
        return findings.stream()
                .anyMatch(f -> f.severity() == Severity.CRITICAL || f.severity() == Severity.HIGH);
    }

    /** True if any findings at all were recorded. */
    public boolean hasWarnings() {
        return !findings.isEmpty();
    }

    /** Unmodifiable view of all findings. */
    public List<Finding> getFindings() {
        return Collections.unmodifiableList(findings);
    }
}
