package com.workshop.loanservice.validation;

/**
 * Represents a single data quality issue detected during legacy data ingestion.
 * Each issue captures the table, record, field, and a human-readable description
 * of what went wrong plus the severity level.
 */
public class DataQualityIssue {

    /**
     * Severity levels aligned with DATA_ANOMALY_REPORT.md categories.
     */
    public enum Severity {
        CRITICAL, HIGH, MEDIUM, LOW
    }

    private final Severity severity;
    private final String table;
    private final String recordId;
    private final String field;
    private final String description;
    private final String rawValue;

    public DataQualityIssue(Severity severity, String table, String recordId,
                            String field, String description, String rawValue) {
        this.severity = severity;
        this.table = table;
        this.recordId = recordId;
        this.field = field;
        this.description = description;
        this.rawValue = rawValue;
    }

    public Severity getSeverity() { return severity; }
    public String getTable() { return table; }
    public String getRecordId() { return recordId; }
    public String getField() { return field; }
    public String getDescription() { return description; }
    public String getRawValue() { return rawValue; }

    @Override
    public String toString() {
        return String.format("[%s] %s.%s (record=%s): %s (raw='%s')",
                severity, table, field, recordId, description, rawValue);
    }
}
