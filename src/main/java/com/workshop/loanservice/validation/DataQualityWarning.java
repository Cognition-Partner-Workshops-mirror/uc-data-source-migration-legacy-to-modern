package com.workshop.loanservice.validation;

/**
 * Represents a single data quality warning detected during legacy data ingestion.
 */
public class DataQualityWarning {

    public enum Severity {
        CRITICAL, HIGH, MEDIUM, LOW
    }

    private final Severity severity;
    private final String recordId;
    private final String field;
    private final String message;
    private final String originalValue;

    public DataQualityWarning(Severity severity, String recordId, String field,
                              String message, String originalValue) {
        this.severity = severity;
        this.recordId = recordId;
        this.field = field;
        this.message = message;
        this.originalValue = originalValue;
    }

    public Severity getSeverity() { return severity; }
    public String getRecordId() { return recordId; }
    public String getField() { return field; }
    public String getMessage() { return message; }
    public String getOriginalValue() { return originalValue; }

    @Override
    public String toString() {
        return "[" + severity + "] " + recordId + "." + field + ": " + message
                + " (value: " + originalValue + ")";
    }
}
