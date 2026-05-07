package com.workshop.loanservice.validation;

public class DataQualityWarning {

    private final String recordId;
    private final String field;
    private final String message;
    private final Severity severity;

    public enum Severity {
        CRITICAL, HIGH, MEDIUM, LOW
    }

    public DataQualityWarning(String recordId, String field, String message, Severity severity) {
        this.recordId = recordId;
        this.field = field;
        this.message = message;
        this.severity = severity;
    }

    public String getRecordId() { return recordId; }
    public String getField() { return field; }
    public String getMessage() { return message; }
    public Severity getSeverity() { return severity; }

    @Override
    public String toString() {
        return "[" + severity + "] " + recordId + "." + field + ": " + message;
    }
}
