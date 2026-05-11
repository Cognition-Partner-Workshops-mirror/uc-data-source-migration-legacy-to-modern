package com.workshop.loanservice.validation;

/**
 * Thrown when legacy data fails quality validation.
 * Contains the anomaly type and affected record identifier for traceability.
 */
public class DataQualityException extends RuntimeException {

    private final String anomalyType;
    private final String recordId;

    public DataQualityException(String anomalyType, String recordId, String message) {
        super(message);
        this.anomalyType = anomalyType;
        this.recordId = recordId;
    }

    public String getAnomalyType() {
        return anomalyType;
    }

    public String getRecordId() {
        return recordId;
    }
}
