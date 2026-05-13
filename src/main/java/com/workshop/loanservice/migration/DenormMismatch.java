package com.workshop.loanservice.migration;

/**
 * Records a mismatch between denormalized borrower fields in CDW_LN_ACCT
 * and the authoritative values in CDW_BORR_MSTR for the same BORR_ID.
 * Used by {@link FkLookupResolver#reconcileDenormalizedFields} for audit logging.
 */
public class DenormMismatch {

    private final String loanAccountNumber;
    private final String borrowerId;
    private final String fieldName;
    private final String loanValue;      // Value in CDW_LN_ACCT (denormalized copy)
    private final String borrowerValue;  // Value in CDW_BORR_MSTR (authoritative)

    public DenormMismatch(String loanAccountNumber, String borrowerId,
                          String fieldName, String loanValue, String borrowerValue) {
        this.loanAccountNumber = loanAccountNumber;
        this.borrowerId = borrowerId;
        this.fieldName = fieldName;
        this.loanValue = loanValue;
        this.borrowerValue = borrowerValue;
    }

    public String getLoanAccountNumber() {
        return loanAccountNumber;
    }

    public String getBorrowerId() {
        return borrowerId;
    }

    public String getFieldName() {
        return fieldName;
    }

    public String getLoanValue() {
        return loanValue;
    }

    public String getBorrowerValue() {
        return borrowerValue;
    }

    @Override
    public String toString() {
        return "DenormMismatch{loan=" + loanAccountNumber + ", borrower=" + borrowerId
                + ", field=" + fieldName + ", loanVal='" + loanValue
                + "', borrVal='" + borrowerValue + "'}";
    }
}
