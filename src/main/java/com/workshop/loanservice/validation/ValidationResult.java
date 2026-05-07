package com.workshop.loanservice.validation;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Captures validation warnings and errors detected during legacy data ingestion.
 * Each entry includes the anomaly ID (matching DATA_ANOMALY_REPORT.md), the affected
 * record identifier, and a human-readable description.
 */
public class ValidationResult {

    /**
     * Severity levels aligned with DATA_ANOMALY_REPORT.md classifications.
     */
    public enum Severity {
        CRITICAL, HIGH, MEDIUM, LOW
    }

    /**
     * Single validation issue found during data ingestion.
     */
    public static class Issue {
        private final Severity severity;
        private final String anomalyId;
        private final String recordId;
        private final String description;

        public Issue(Severity severity, String anomalyId, String recordId, String description) {
            this.severity = severity;
            this.anomalyId = anomalyId;
            this.recordId = recordId;
            this.description = description;
        }

        public Severity getSeverity() { return severity; }
        public String getAnomalyId() { return anomalyId; }
        public String getRecordId() { return recordId; }
        public String getDescription() { return description; }

        @Override
        public String toString() {
            return "[" + severity + "] " + anomalyId + " (" + recordId + "): " + description;
        }
    }

    private final List<Issue> issues = new ArrayList<>();

    public void addIssue(Severity severity, String anomalyId, String recordId, String description) {
        issues.add(new Issue(severity, anomalyId, recordId, description));
    }

    public List<Issue> getIssues() {
        return Collections.unmodifiableList(issues);
    }

    public boolean hasIssues() {
        return !issues.isEmpty();
    }

    /**
     * Returns true if any issue has CRITICAL severity.
     */
    public boolean hasCriticalIssues() {
        return issues.stream().anyMatch(i -> i.getSeverity() == Severity.CRITICAL);
    }

    /**
     * Returns issues filtered by severity.
     */
    public List<Issue> getIssuesBySeverity(Severity severity) {
        return issues.stream()
                .filter(i -> i.getSeverity() == severity)
                .toList();
    }

    public int size() {
        return issues.size();
    }
}
