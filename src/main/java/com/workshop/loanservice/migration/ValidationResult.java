package com.workshop.loanservice.migration;

/**
 * Generic result wrapper for a single field validation during migration.
 * Captures the parsed value (if valid), the raw source value, the column name,
 * and any error/warning message with its severity level.
 *
 * @param <T> the target Java type after transformation (e.g. LocalDate, BigDecimal)
 */
public class ValidationResult<T> {

    /** Severity levels for validation findings */
    public enum Severity {
        ERROR,   // Data cannot be migrated — will violate NOT NULL or FK constraint
        WARNING, // Data can be migrated but looks suspicious (ambiguous date, sum mismatch)
        INFO     // Informational note (e.g. time component loss on DATE→TIMESTAMP)
    }

    private final boolean valid;
    private final T value;
    private final String columnName;
    private final String rawValue;
    private final String errorMessage;
    private final Severity severity;

    private ValidationResult(boolean valid, T value, String columnName,
                             String rawValue, String errorMessage, Severity severity) {
        this.valid = valid;
        this.value = value;
        this.columnName = columnName;
        this.rawValue = rawValue;
        this.errorMessage = errorMessage;
        this.severity = severity;
    }

    /** Factory: successful parse — no issues */
    public static <T> ValidationResult<T> ok(T value) {
        return new ValidationResult<>(true, value, null, null, null, null);
    }

    /** Factory: parse failed or constraint violated — ERROR severity */
    public static <T> ValidationResult<T> error(String columnName, String rawValue, String message) {
        return new ValidationResult<>(false, null, columnName, rawValue, message, Severity.ERROR);
    }

    /** Factory: parse succeeded but value is suspicious — WARNING severity */
    public static <T> ValidationResult<T> warning(String columnName, String rawValue, String message) {
        return new ValidationResult<>(true, null, columnName, rawValue, message, Severity.WARNING);
    }

    /** Factory: warning that also carries the parsed value */
    public static <T> ValidationResult<T> warningWithValue(T value, String columnName,
                                                           String rawValue, String message) {
        return new ValidationResult<>(true, value, columnName, rawValue, message, Severity.WARNING);
    }

    /** Factory: informational note (e.g. time component loss) */
    public static <T> ValidationResult<T> info(T value, String columnName,
                                               String rawValue, String message) {
        return new ValidationResult<>(true, value, columnName, rawValue, message, Severity.INFO);
    }

    // ---- Accessors ----

    public boolean isValid() {
        return valid;
    }

    public T getValue() {
        return value;
    }

    public String getColumnName() {
        return columnName;
    }

    public String getRawValue() {
        return rawValue;
    }

    public String getErrorMessage() {
        return errorMessage;
    }

    public Severity getSeverity() {
        return severity;
    }

    @Override
    public String toString() {
        if (severity == null) {
            return "OK: " + value;
        }
        return severity + " [" + columnName + "] raw='" + rawValue + "' — " + errorMessage;
    }
}
