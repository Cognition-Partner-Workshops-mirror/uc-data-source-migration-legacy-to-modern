package com.workshop.loanservice.validation;

/**
 * Represents a single data quality issue found during validation.
 */
public class ValidationIssue {

    public enum Severity {
        CRITICAL, HIGH, MEDIUM, LOW
    }

    private final Severity severity;
    private final String column;
    private final String recordId;
    private final String message;

    public ValidationIssue(Severity severity, String column, String recordId, String message) {
        this.severity = severity;
        this.column = column;
        this.recordId = recordId;
        this.message = message;
    }

    public static ValidationIssue critical(String column, String recordId, String message) {
        return new ValidationIssue(Severity.CRITICAL, column, recordId, message);
    }

    public static ValidationIssue high(String column, String recordId, String message) {
        return new ValidationIssue(Severity.HIGH, column, recordId, message);
    }

    public static ValidationIssue medium(String column, String recordId, String message) {
        return new ValidationIssue(Severity.MEDIUM, column, recordId, message);
    }

    public static ValidationIssue low(String column, String recordId, String message) {
        return new ValidationIssue(Severity.LOW, column, recordId, message);
    }

    public Severity getSeverity() {
        return severity;
    }

    public String getColumn() {
        return column;
    }

    public String getRecordId() {
        return recordId;
    }

    public String getMessage() {
        return message;
    }

    @Override
    public String toString() {
        return String.format("[%s] %s (record=%s, column=%s)", severity, message, recordId, column);
    }
}
