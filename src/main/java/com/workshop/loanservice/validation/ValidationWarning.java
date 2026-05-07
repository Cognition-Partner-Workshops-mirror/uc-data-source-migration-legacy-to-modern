package com.workshop.loanservice.validation;

public class ValidationWarning {

    private final String recordId;
    private final String field;
    private final String anomalyType;
    private final String message;
    private final String severity;

    public ValidationWarning(String recordId, String field, String anomalyType,
                             String message, String severity) {
        this.recordId = recordId;
        this.field = field;
        this.anomalyType = anomalyType;
        this.message = message;
        this.severity = severity;
    }

    public String getRecordId() { return recordId; }
    public String getField() { return field; }
    public String getAnomalyType() { return anomalyType; }
    public String getMessage() { return message; }
    public String getSeverity() { return severity; }

    @Override
    public String toString() {
        return "[" + severity + "] " + anomalyType + " on " + recordId + "." + field + ": " + message;
    }
}
