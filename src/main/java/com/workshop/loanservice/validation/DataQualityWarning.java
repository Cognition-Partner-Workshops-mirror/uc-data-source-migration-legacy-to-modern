package com.workshop.loanservice.validation;

public class DataQualityWarning {

    public enum Severity {
        CRITICAL, HIGH, MEDIUM, LOW
    }

    private final String anomalyCode;
    private final Severity severity;
    private final String table;
    private final String column;
    private final String recordId;
    private final String message;

    public DataQualityWarning(String anomalyCode, Severity severity, String table,
                              String column, String recordId, String message) {
        this.anomalyCode = anomalyCode;
        this.severity = severity;
        this.table = table;
        this.column = column;
        this.recordId = recordId;
        this.message = message;
    }

    public String getAnomalyCode() { return anomalyCode; }
    public Severity getSeverity() { return severity; }
    public String getTable() { return table; }
    public String getColumn() { return column; }
    public String getRecordId() { return recordId; }
    public String getMessage() { return message; }

    @Override
    public String toString() {
        return "[" + anomalyCode + "/" + severity + "] " + table + "." + column
                + " (record=" + recordId + "): " + message;
    }
}
