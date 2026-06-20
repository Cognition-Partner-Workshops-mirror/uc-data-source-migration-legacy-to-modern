-- =============================================================================
-- LEGACY DATA WAREHOUSE SCHEMA (CDW-style)
-- =============================================================================
-- These tables simulate a legacy data warehouse with:
--   - Cryptic column names (abbreviated, inconsistent)
--   - Denormalized structures (borrower data embedded in loan accounts)
--   - VARCHAR for everything (loose typing)
--   - No foreign key constraints
--   - Inconsistent date formats stored as strings
-- =============================================================================

-- Borrower Master
CREATE TABLE IF NOT EXISTS CDW_BORR_MSTR (
    BORR_ID         VARCHAR(20) PRIMARY KEY,
    BORR_FST_NM     VARCHAR(50),
    BORR_LST_NM     VARCHAR(50),
    BORR_MID_INIT   VARCHAR(1),
    BORR_SSN_ENCR   VARCHAR(100),
    BORR_DOB_DT     VARCHAR(10),        -- stored as MM/DD/YYYY
    BORR_ADDR_LN1   VARCHAR(100),
    BORR_ADDR_LN2   VARCHAR(100),
    BORR_CTY_NM     VARCHAR(50),
    BORR_ST_CD      VARCHAR(2),
    BORR_ZIP_CD     VARCHAR(10),
    BORR_PH_NBR     VARCHAR(15),
    BORR_EMAIL_ADDR VARCHAR(100),
    BORR_CRDT_SCR   VARCHAR(5),         -- credit score as string
    BORR_EMP_STAT   VARCHAR(20),
    BORR_ANN_INCM   VARCHAR(15),        -- annual income as string with commas
    BORR_CRET_DT    VARCHAR(10),        -- created date as MM/DD/YYYY
    BORR_UPDT_DT    VARCHAR(10),        -- updated date as MM/DD/YYYY
    BORR_STAT_CD    VARCHAR(5),
    BORR_REC_TYP    VARCHAR(10)
);

-- Loan Products
CREATE TABLE IF NOT EXISTS CDW_LN_PROD (
    PROD_CD         VARCHAR(10) PRIMARY KEY,
    PROD_DESC_TXT   VARCHAR(200),
    PROD_TYP_CD     VARCHAR(5),         -- FXD, ARM, FHA, VA, etc.
    PROD_TERM_MOS   VARCHAR(5),         -- term in months as string
    PROD_RT_TYP     VARCHAR(10),        -- FIXED, VARIABLE
    PROD_MIN_AMT    VARCHAR(15),
    PROD_MAX_AMT    VARCHAR(15),
    PROD_STAT_CD    VARCHAR(5),
    PROD_EFF_DT     VARCHAR(10),
    PROD_EXP_DT     VARCHAR(10)
);

-- Loan Accounts (denormalized — has borrower data embedded)
CREATE TABLE IF NOT EXISTS CDW_LN_ACCT (
    LN_ACCT_NBR     VARCHAR(20) PRIMARY KEY,
    BORR_ID         VARCHAR(20),
    -- Denormalized borrower fields (redundant with CDW_BORR_MSTR)
    BORR_FST_NM     VARCHAR(50),
    BORR_LST_NM     VARCHAR(50),
    BORR_SSN_LST4   VARCHAR(4),
    -- Loan fields
    PROD_CD         VARCHAR(10),
    LN_ORIG_AMT     VARCHAR(15),        -- original amount as string
    LN_CURR_BAL     VARCHAR(15),        -- current balance as string
    LN_INT_RT       VARCHAR(8),         -- interest rate as string "5.250"
    LN_TERM_MOS     VARCHAR(5),
    LN_PMT_AMT      VARCHAR(15),        -- monthly payment as string
    LN_ORIG_DT      VARCHAR(10),        -- origination date MM/DD/YYYY
    LN_MAT_DT       VARCHAR(10),        -- maturity date MM/DD/YYYY
    LN_1ST_PMT_DT   VARCHAR(10),
    LN_NXT_PMT_DT   VARCHAR(10),
    LN_STAT_CD      VARCHAR(5),         -- ACT, CLO, DFT, FRB
    LN_DLQ_DAYS     VARCHAR(5),
    LN_ESCROW_BAL   VARCHAR(15),
    LN_LTV_PCT      VARCHAR(8),         -- loan-to-value as string
    PROP_ADDR_LN1   VARCHAR(100),
    PROP_CTY_NM     VARCHAR(50),
    PROP_ST_CD      VARCHAR(2),
    PROP_ZIP_CD     VARCHAR(10),
    PROP_TYP_CD     VARCHAR(10),        -- SFR, CND, MFR, TWN
    PROP_APRS_VAL   VARCHAR(15),        -- appraised value as string
    LN_CRET_DT      VARCHAR(10),
    LN_UPDT_DT      VARCHAR(10)
);

-- Payment History
CREATE TABLE IF NOT EXISTS CDW_PMT_HIST (
    PMT_SEQ_NBR     VARCHAR(20) PRIMARY KEY,
    LN_ACCT_NBR     VARCHAR(20),
    PMT_DT          VARCHAR(10),        -- payment date MM/DD/YYYY
    PMT_AMT         VARCHAR(15),        -- total payment as string
    PMT_PRIN_AMT    VARCHAR(15),        -- principal portion
    PMT_INT_AMT     VARCHAR(15),        -- interest portion
    PMT_ESCROW_AMT  VARCHAR(15),        -- escrow portion
    PMT_LATE_FEE    VARCHAR(15),
    PMT_TYP_CD      VARCHAR(5),         -- REG, EXT, PRT, PRE
    PMT_STAT_CD     VARCHAR(5),         -- PST, REV, NSF, PND
    PMT_RECV_DT     VARCHAR(10),
    PMT_PROC_DT     VARCHAR(10),
    PMT_CRET_DT     VARCHAR(10),
    PMT_UPDT_DT     VARCHAR(10)
);
