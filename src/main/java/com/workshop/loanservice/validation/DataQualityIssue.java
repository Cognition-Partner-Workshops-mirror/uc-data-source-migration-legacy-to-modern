package com.workshop.loanservice.validation;

/**
 * Represents a single data quality issue detected during legacy data ingestion.
 */
public class DataQualityIssue {

    public enum Severity {
        CRITICAL, HIGH, MEDIUM, LOW
    }

    private final Severity severity;
    private final String table;
    private final String column;
    private final String recordId;
    private final String description;
    private final String rawValue;

    public DataQualityIssue(Severity severity, String table, String column,
                            String recordId, String description, String rawValue) {
        this.severity = severity;
        this.table = table;
        this.column = column;
        this.recordId = recordId;
        this.description = description;
        this.rawValue = rawValue;
    }

    public Severity getSeverity() { return severity; }
    public String getTable() { return table; }
    public String getColumn() { return column; }
    public String getRecordId() { return recordId; }
    public String getDescription() { return description; }
    public String getRawValue() { return rawValue; }

    @Override
    public String toString() {
        return String.format("[%s] %s.%s (record=%s): %s [raw=%s]",
                severity, table, column, recordId, description, rawValue);
    }
}
