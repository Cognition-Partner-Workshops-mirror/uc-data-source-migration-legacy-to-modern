package com.workshop.loanservice.validation;

/**
 * Represents a single validation finding for a legacy CDW record.
 * Used by LegacyDataValidator to report anomalies found during ingestion-time checks.
 */
public record ValidationResult(
        Severity severity,
        String recordId,
        String table,
        String column,
        String message
) {

    public enum Severity {
        ERROR,
        WARNING
    }

    /** Factory for error-level findings (data issues that cause runtime failures or data corruption). */
    public static ValidationResult error(String recordId, String table, String column, String message) {
        return new ValidationResult(Severity.ERROR, recordId, table, column, message);
    }

    /** Factory for warning-level findings (data issues that may cause incorrect results but not crashes). */
    public static ValidationResult warning(String recordId, String table, String column, String message) {
        return new ValidationResult(Severity.WARNING, recordId, table, column, message);
    }
}
