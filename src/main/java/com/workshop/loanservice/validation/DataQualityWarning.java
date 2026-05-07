package com.workshop.loanservice.validation;

public class DataQualityWarning {

    private final String field;
    private final String severity;
    private final String message;

    public DataQualityWarning(String field, String severity, String message) {
        this.field = field;
        this.severity = severity;
        this.message = message;
    }

    public String getField() { return field; }
    public String getSeverity() { return severity; }
    public String getMessage() { return message; }

    public static DataQualityWarning critical(String field, String message) {
        return new DataQualityWarning(field, "CRITICAL", message);
    }

    public static DataQualityWarning high(String field, String message) {
        return new DataQualityWarning(field, "HIGH", message);
    }

    public static DataQualityWarning medium(String field, String message) {
        return new DataQualityWarning(field, "MEDIUM", message);
    }
}
