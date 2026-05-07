package com.workshop.loanservice.validation;

public class DataQualityIssue {

    public enum Severity { CRITICAL, HIGH, MEDIUM, LOW }

    private final Severity severity;
    private final String context;
    private final String column;
    private final String message;

    public DataQualityIssue(Severity severity, String context, String column, String message) {
        this.severity = severity;
        this.context = context;
        this.column = column;
        this.message = message;
    }

    public static DataQualityIssue critical(String context, String column, String message) {
        return new DataQualityIssue(Severity.CRITICAL, context, column, message);
    }

    public static DataQualityIssue high(String context, String column, String message) {
        return new DataQualityIssue(Severity.HIGH, context, column, message);
    }

    public static DataQualityIssue medium(String context, String column, String message) {
        return new DataQualityIssue(Severity.MEDIUM, context, column, message);
    }

    public static DataQualityIssue low(String context, String column, String message) {
        return new DataQualityIssue(Severity.LOW, context, column, message);
    }

    public Severity getSeverity() { return severity; }
    public String getContext() { return context; }
    public String getColumn() { return column; }
    public String getMessage() { return message; }

    @Override
    public String toString() {
        return "[" + severity + "] " + context + "." + column + ": " + message;
    }
}
