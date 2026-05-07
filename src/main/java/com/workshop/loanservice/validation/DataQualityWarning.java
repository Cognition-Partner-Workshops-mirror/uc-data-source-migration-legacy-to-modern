package com.workshop.loanservice.validation;

public class DataQualityWarning {

    public enum Severity {
        CRITICAL, HIGH, MEDIUM, LOW
    }

    private final Severity severity;
    private final String field;
    private final String message;
    private final String recordId;

    public DataQualityWarning(Severity severity, String field, String message, String recordId) {
        this.severity = severity;
        this.field = field;
        this.message = message;
        this.recordId = recordId;
    }

    public Severity getSeverity() { return severity; }
    public String getField() { return field; }
    public String getMessage() { return message; }
    public String getRecordId() { return recordId; }

    @Override
    public String toString() {
        return "[" + severity + "] " + recordId + "." + field + ": " + message;
    }
}
