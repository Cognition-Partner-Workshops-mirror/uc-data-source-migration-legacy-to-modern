package com.workshop.loanservice.validation;

/**
 * Represents a data quality issue detected during legacy data ingestion.
 */
public class DataQualityWarning {

    private final String anomalyId;
    private final String severity;
    private final String field;
    private final String rawValue;
    private final String message;

    public DataQualityWarning(String anomalyId, String severity, String field, String rawValue, String message) {
        this.anomalyId = anomalyId;
        this.severity = severity;
        this.field = field;
        this.rawValue = rawValue;
        this.message = message;
    }

    public String getAnomalyId() { return anomalyId; }
    public String getSeverity() { return severity; }
    public String getField() { return field; }
    public String getRawValue() { return rawValue; }
    public String getMessage() { return message; }

    @Override
    public String toString() {
        return "[" + anomalyId + "/" + severity + "] " + field + "=" + rawValue + ": " + message;
    }
}
