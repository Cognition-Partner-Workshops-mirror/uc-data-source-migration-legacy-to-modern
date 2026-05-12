-- =============================================================================
-- SYNTHETIC HIVE SCHEMA FOR EXECUTION AND VALIDATION
-- =============================================================================
-- Generated from: data/mappings/column_mappings.md
-- Purpose: Provides Hive-compatible DDL for the data migration pipeline.
--
-- Databases:
--   default       - Source layer (raw ingested data from legacy Teradata)
--   work_schema   - Staging layer (intermediate transformations)
--   audit         - Audit layer (final validated dimensional / fact tables)
--
-- Conventions:
--   - All tables are partitioned by as_of_dt (STRING, format YYYY-MM-DD).
--   - data_src_ind column distinguishes load frequency:
--       'D' = DAILY  (business-day snapshots)
--       'M' = MOEND  (month-end snapshots)
--   - Stored as ORC with Snappy compression for efficient columnar reads.
--   - Column comments reference the legacy CDW source columns from
--     data/mappings/column_mappings.md.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- Create databases if they do not already exist
-- -----------------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS work_schema
    COMMENT 'Staging layer for intermediate transformations during migration';

CREATE DATABASE IF NOT EXISTS audit
    COMMENT 'Audit layer for validated dimensional and fact tables';


-- =============================================================================
-- 1. SOURCE LAYER: default.td_contracts
-- =============================================================================
-- Raw contract/loan data ingested from the legacy Teradata CDW.
-- Maps to CDW_LN_ACCT joined with CDW_BORR_MSTR (denormalized source).
-- Contains both DAILY and MOEND snapshots distinguished by data_src_ind.
-- =============================================================================
DROP TABLE IF EXISTS default.td_contracts;

CREATE TABLE default.td_contracts (
    -- Data source indicator: 'D' = DAILY snapshot, 'M' = MOEND snapshot
    data_src_ind        STRING      COMMENT 'Load frequency: D=DAILY, M=MOEND',

    -- Contract / Loan Account fields (from CDW_LN_ACCT)
    ln_acct_nbr         STRING      COMMENT 'Loan account number (CDW_LN_ACCT.LN_ACCT_NBR)',
    prod_cd             STRING      COMMENT 'Product code (CDW_LN_ACCT.PROD_CD)',
    ln_orig_amt         STRING      COMMENT 'Original loan amount as string (CDW_LN_ACCT.LN_ORIG_AMT)',
    ln_curr_bal         STRING      COMMENT 'Current balance as string (CDW_LN_ACCT.LN_CURR_BAL)',
    ln_int_rt           STRING      COMMENT 'Interest rate as string e.g. 5.250 (CDW_LN_ACCT.LN_INT_RT)',
    ln_term_mos         STRING      COMMENT 'Term in months as string (CDW_LN_ACCT.LN_TERM_MOS)',
    ln_pmt_amt          STRING      COMMENT 'Monthly payment as string (CDW_LN_ACCT.LN_PMT_AMT)',
    ln_orig_dt          STRING      COMMENT 'Origination date MM/DD/YYYY (CDW_LN_ACCT.LN_ORIG_DT)',
    ln_mat_dt           STRING      COMMENT 'Maturity date MM/DD/YYYY (CDW_LN_ACCT.LN_MAT_DT)',
    ln_1st_pmt_dt       STRING      COMMENT 'First payment date MM/DD/YYYY (CDW_LN_ACCT.LN_1ST_PMT_DT)',
    ln_nxt_pmt_dt       STRING      COMMENT 'Next payment date MM/DD/YYYY (CDW_LN_ACCT.LN_NXT_PMT_DT)',
    ln_stat_cd          STRING      COMMENT 'Status code: ACT, CLO, DFT, FRB (CDW_LN_ACCT.LN_STAT_CD)',
    ln_dlq_days         STRING      COMMENT 'Delinquency days as string (CDW_LN_ACCT.LN_DLQ_DAYS)',
    ln_escrow_bal       STRING      COMMENT 'Escrow balance as string (CDW_LN_ACCT.LN_ESCROW_BAL)',
    ln_ltv_pct          STRING      COMMENT 'Loan-to-value percent as string (CDW_LN_ACCT.LN_LTV_PCT)',
    ln_cret_dt          STRING      COMMENT 'Record created date MM/DD/YYYY (CDW_LN_ACCT.LN_CRET_DT)',
    ln_updt_dt          STRING      COMMENT 'Record updated date MM/DD/YYYY (CDW_LN_ACCT.LN_UPDT_DT)',

    -- Property fields (from CDW_LN_ACCT)
    prop_addr_ln1       STRING      COMMENT 'Property address line 1 (CDW_LN_ACCT.PROP_ADDR_LN1)',
    prop_cty_nm         STRING      COMMENT 'Property city (CDW_LN_ACCT.PROP_CTY_NM)',
    prop_st_cd          STRING      COMMENT 'Property state code (CDW_LN_ACCT.PROP_ST_CD)',
    prop_zip_cd         STRING      COMMENT 'Property zip code (CDW_LN_ACCT.PROP_ZIP_CD)',
    prop_typ_cd         STRING      COMMENT 'Property type: SFR, CND, MFR, TWN (CDW_LN_ACCT.PROP_TYP_CD)',
    prop_aprs_val       STRING      COMMENT 'Appraised value as string (CDW_LN_ACCT.PROP_APRS_VAL)',

    -- Denormalized Borrower fields (from CDW_LN_ACCT / CDW_BORR_MSTR)
    borr_id             STRING      COMMENT 'Borrower identifier (CDW_BORR_MSTR.BORR_ID)',
    borr_fst_nm         STRING      COMMENT 'Borrower first name (CDW_BORR_MSTR.BORR_FST_NM)',
    borr_lst_nm         STRING      COMMENT 'Borrower last name (CDW_BORR_MSTR.BORR_LST_NM)',
    borr_mid_init       STRING      COMMENT 'Borrower middle initial (CDW_BORR_MSTR.BORR_MID_INIT)',
    borr_ssn_encr       STRING      COMMENT 'Encrypted SSN (CDW_BORR_MSTR.BORR_SSN_ENCR)',
    borr_ssn_lst4       STRING      COMMENT 'Last 4 of SSN (CDW_LN_ACCT.BORR_SSN_LST4)',
    borr_dob_dt         STRING      COMMENT 'Date of birth MM/DD/YYYY (CDW_BORR_MSTR.BORR_DOB_DT)',
    borr_addr_ln1       STRING      COMMENT 'Borrower address line 1 (CDW_BORR_MSTR.BORR_ADDR_LN1)',
    borr_addr_ln2       STRING      COMMENT 'Borrower address line 2 (CDW_BORR_MSTR.BORR_ADDR_LN2)',
    borr_cty_nm         STRING      COMMENT 'Borrower city (CDW_BORR_MSTR.BORR_CTY_NM)',
    borr_st_cd          STRING      COMMENT 'Borrower state code (CDW_BORR_MSTR.BORR_ST_CD)',
    borr_zip_cd         STRING      COMMENT 'Borrower zip code (CDW_BORR_MSTR.BORR_ZIP_CD)',
    borr_ph_nbr         STRING      COMMENT 'Borrower phone number (CDW_BORR_MSTR.BORR_PH_NBR)',
    borr_email_addr     STRING      COMMENT 'Borrower email (CDW_BORR_MSTR.BORR_EMAIL_ADDR)',
    borr_crdt_scr       STRING      COMMENT 'Credit score as string (CDW_BORR_MSTR.BORR_CRDT_SCR)',
    borr_emp_stat       STRING      COMMENT 'Employment status (CDW_BORR_MSTR.BORR_EMP_STAT)',
    borr_ann_incm       STRING      COMMENT 'Annual income as string with commas (CDW_BORR_MSTR.BORR_ANN_INCM)',
    borr_stat_cd        STRING      COMMENT 'Borrower status code: ACT, INA (CDW_BORR_MSTR.BORR_STAT_CD)',

    -- Payment summary fields (from CDW_PMT_HIST aggregate)
    last_pmt_dt         STRING      COMMENT 'Last payment date MM/DD/YYYY (derived from CDW_PMT_HIST.PMT_DT)',
    last_pmt_amt        STRING      COMMENT 'Last payment amount as string (derived from CDW_PMT_HIST.PMT_AMT)',

    -- Audit / ETL metadata
    src_sys_cd          STRING      COMMENT 'Source system code, e.g. CDW',
    etl_load_ts         TIMESTAMP   COMMENT 'Timestamp when the record was loaded by ETL'
)
COMMENT 'Source layer: raw contract data from legacy Teradata CDW. Contains DAILY (D) and MOEND (M) snapshots.'
PARTITIONED BY (
    as_of_dt            STRING      COMMENT 'Snapshot date partition (YYYY-MM-DD)'
)
STORED AS ORC
TBLPROPERTIES (
    'orc.compress' = 'SNAPPY',
    'transactional' = 'false'
);


-- =============================================================================
-- 2. STAGING LAYER: work_schema.cad_id
-- =============================================================================
-- Contract Account Detail - Identification.
-- Extracts and normalizes borrower identification / demographic fields
-- from td_contracts. Supports both DAILY and MOEND snapshots.
-- Maps to CDW_BORR_MSTR columns via column_mappings.md.
-- =============================================================================
DROP TABLE IF EXISTS work_schema.cad_id;

CREATE TABLE work_schema.cad_id (
    -- Data source indicator: 'D' = DAILY snapshot, 'M' = MOEND snapshot
    -- DAILY: loaded every business day for current-state tracking
    -- MOEND: loaded at month-end for period-close reporting
    data_src_ind        STRING      COMMENT 'Load frequency: D=DAILY, M=MOEND',

    -- Contract key
    ln_acct_nbr         STRING      COMMENT 'Loan account number linking to td_contracts',

    -- Borrower identification (normalized from CDW_BORR_MSTR via mapping doc)
    borr_id             STRING      COMMENT 'Borrower external ID -> modern external_id (direct copy)',
    borr_fst_nm         STRING      COMMENT 'First name -> modern first_name (direct copy)',
    borr_lst_nm         STRING      COMMENT 'Last name -> modern last_name (direct copy)',
    borr_mid_init       STRING      COMMENT 'Middle initial -> modern middle_initial (direct copy)',
    borr_ssn_hash       STRING      COMMENT 'Encrypted SSN -> modern ssn_hash (re-encrypt recommended)',
    borr_dob_dt         DATE        COMMENT 'Date of birth parsed from MM/DD/YYYY -> DATE',

    -- Borrower demographics (normalized types per mapping doc)
    borr_addr_ln1       STRING      COMMENT 'Address line 1 -> modern address_line1 (direct copy)',
    borr_addr_ln2       STRING      COMMENT 'Address line 2 -> modern address_line2 (direct copy)',
    borr_cty_nm         STRING      COMMENT 'City -> modern city (direct copy)',
    borr_st_cd          STRING      COMMENT 'State code -> modern state (direct copy)',
    borr_zip_cd         STRING      COMMENT 'Zip code -> modern zip_code (direct copy)',
    borr_ph_nbr         STRING      COMMENT 'Phone -> modern phone (direct copy)',
    borr_email_addr     STRING      COMMENT 'Email -> modern email (direct copy)',
    borr_crdt_scr       INT         COMMENT 'Credit score parsed from string -> INT (modern credit_score)',
    borr_emp_stat       STRING      COMMENT 'Employment status -> modern employment_status (direct copy)',
    borr_ann_incm       DECIMAL(12,2) COMMENT 'Annual income parsed, commas removed -> DECIMAL (modern annual_income)',

    -- Status (expanded per mapping: ACT->ACTIVE, INA->INACTIVE)
    borr_stat_cd        STRING      COMMENT 'Borrower status expanded: ACT->ACTIVE, INA->INACTIVE',

    -- Audit / ETL metadata
    src_sys_cd          STRING      COMMENT 'Source system code',
    etl_load_ts         TIMESTAMP   COMMENT 'ETL load timestamp',
    rec_eff_dt          DATE        COMMENT 'Record effective date for SCD tracking'
)
COMMENT 'Staging: borrower identification and demographics. Normalized from td_contracts per column_mappings.md.'
PARTITIONED BY (
    as_of_dt            STRING      COMMENT 'Snapshot date partition (YYYY-MM-DD)'
)
STORED AS ORC
TBLPROPERTIES (
    'orc.compress' = 'SNAPPY',
    'transactional' = 'false'
);


-- =============================================================================
-- 3. STAGING LAYER: work_schema.cad_cb
-- =============================================================================
-- Contract Account Detail - Current Balance.
-- Contains current (active) loan account balance and payment data.
-- Applies to contracts where ln_stat_cd IN ('ACT','FRB') — active or
-- forbearance status. Supports DAILY and MOEND snapshots.
-- Maps to CDW_LN_ACCT balance columns via column_mappings.md.
-- =============================================================================
DROP TABLE IF EXISTS work_schema.cad_cb;

CREATE TABLE work_schema.cad_cb (
    -- Data source indicator: determines snapshot cadence
    -- DAILY ('D'): captures intra-month balance movements
    -- MOEND ('M'): captures official month-end position for reporting
    data_src_ind        STRING      COMMENT 'Load frequency: D=DAILY, M=MOEND',

    -- Contract keys
    ln_acct_nbr         STRING      COMMENT 'Loan account number (CDW_LN_ACCT.LN_ACCT_NBR)',
    borr_id             STRING      COMMENT 'Borrower ID for FK resolution to cad_id',
    prod_cd             STRING      COMMENT 'Product code for FK resolution to loan_products',

    -- Balance fields (typed per mapping: string -> DECIMAL)
    ln_orig_amt         DECIMAL(12,2)   COMMENT 'Original amount, commas removed -> DECIMAL (modern original_amount)',
    ln_curr_bal         DECIMAL(12,2)   COMMENT 'Current balance, commas removed -> DECIMAL (modern current_balance)',
    ln_int_rt           DECIMAL(5,3)    COMMENT 'Interest rate parsed -> DECIMAL (modern interest_rate)',
    ln_pmt_amt          DECIMAL(10,2)   COMMENT 'Monthly payment, commas removed -> DECIMAL (modern monthly_payment)',
    ln_escrow_bal       DECIMAL(10,2)   COMMENT 'Escrow balance, commas removed -> DECIMAL (modern escrow_balance)',
    ln_ltv_pct          DECIMAL(5,2)    COMMENT 'Loan-to-value percent parsed -> DECIMAL (modern ltv_percent)',

    -- Term and dates (typed per mapping: string -> INT / DATE)
    ln_term_mos         INT             COMMENT 'Term months parsed -> INT (modern term_months)',
    ln_orig_dt          DATE            COMMENT 'Origination date parsed MM/DD/YYYY -> DATE (modern origination_date)',
    ln_mat_dt           DATE            COMMENT 'Maturity date parsed MM/DD/YYYY -> DATE (modern maturity_date)',
    ln_1st_pmt_dt       DATE            COMMENT 'First payment date parsed -> DATE (modern first_payment_date)',
    ln_nxt_pmt_dt       DATE            COMMENT 'Next payment date parsed -> DATE (modern next_payment_date)',

    -- Status (expanded per mapping: ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE)
    ln_stat_cd          STRING          COMMENT 'Loan status expanded from CDW codes',
    ln_dlq_days         INT             COMMENT 'Delinquency days parsed -> INT (modern delinquency_days)',

    -- Audit / ETL metadata
    src_sys_cd          STRING      COMMENT 'Source system code',
    etl_load_ts         TIMESTAMP   COMMENT 'ETL load timestamp',
    rec_eff_dt          DATE        COMMENT 'Record effective date for SCD tracking'
)
COMMENT 'Staging: current balance data for active/forbearance contracts. Typed per column_mappings.md.'
PARTITIONED BY (
    as_of_dt            STRING      COMMENT 'Snapshot date partition (YYYY-MM-DD)'
)
STORED AS ORC
TBLPROPERTIES (
    'orc.compress' = 'SNAPPY',
    'transactional' = 'false'
);


-- =============================================================================
-- 4. STAGING LAYER: work_schema.cad_nccb
-- =============================================================================
-- Contract Account Detail - Non-Current Credit Balance.
-- Contains balance data for non-current contracts (closed, defaulted).
-- Applies to contracts where ln_stat_cd IN ('CLO','DFT') — closed or
-- defaulted. Structure mirrors cad_cb but tracks historical/closed positions.
-- MOEND snapshots are typical for non-current; DAILY included for completeness.
-- =============================================================================
DROP TABLE IF EXISTS work_schema.cad_nccb;

CREATE TABLE work_schema.cad_nccb (
    -- Data source indicator
    -- For non-current accounts:
    --   DAILY ('D'): tracks newly closed/defaulted contracts during the month
    --   MOEND ('M'): official month-end non-current position for regulatory reporting
    data_src_ind        STRING      COMMENT 'Load frequency: D=DAILY, M=MOEND',

    -- Contract keys
    ln_acct_nbr         STRING      COMMENT 'Loan account number (CDW_LN_ACCT.LN_ACCT_NBR)',
    borr_id             STRING      COMMENT 'Borrower ID for FK resolution to cad_id',
    prod_cd             STRING      COMMENT 'Product code for FK resolution to loan_products',

    -- Balance fields at time of closure/default (typed per mapping)
    ln_orig_amt         DECIMAL(12,2)   COMMENT 'Original amount -> DECIMAL (modern original_amount)',
    ln_curr_bal         DECIMAL(12,2)   COMMENT 'Remaining balance at closure -> DECIMAL (modern current_balance)',
    ln_int_rt           DECIMAL(5,3)    COMMENT 'Interest rate -> DECIMAL (modern interest_rate)',
    ln_pmt_amt          DECIMAL(10,2)   COMMENT 'Last monthly payment -> DECIMAL (modern monthly_payment)',
    ln_escrow_bal       DECIMAL(10,2)   COMMENT 'Escrow balance at closure -> DECIMAL (modern escrow_balance)',
    ln_ltv_pct          DECIMAL(5,2)    COMMENT 'LTV percent at closure -> DECIMAL (modern ltv_percent)',

    -- Term and dates (typed per mapping)
    ln_term_mos         INT             COMMENT 'Term months -> INT (modern term_months)',
    ln_orig_dt          DATE            COMMENT 'Origination date -> DATE (modern origination_date)',
    ln_mat_dt           DATE            COMMENT 'Maturity date -> DATE (modern maturity_date)',
    ln_1st_pmt_dt       DATE            COMMENT 'First payment date -> DATE (modern first_payment_date)',
    ln_nxt_pmt_dt       DATE            COMMENT 'Next payment date (NULL for closed) -> DATE',

    -- Status (expanded: CLO->CLOSED, DFT->DEFAULT)
    ln_stat_cd          STRING          COMMENT 'Loan status expanded: CLO->CLOSED, DFT->DEFAULT',
    ln_dlq_days         INT             COMMENT 'Delinquency days at closure -> INT',

    -- Closure details
    closure_dt          DATE            COMMENT 'Date the contract was closed or defaulted',
    closure_reason_cd   STRING          COMMENT 'Reason code for closure: PAID_OFF, CHARGED_OFF, REFINANCED',

    -- Audit / ETL metadata
    src_sys_cd          STRING      COMMENT 'Source system code',
    etl_load_ts         TIMESTAMP   COMMENT 'ETL load timestamp',
    rec_eff_dt          DATE        COMMENT 'Record effective date for SCD tracking'
)
COMMENT 'Staging: non-current balance data for closed/defaulted contracts. Mirrors cad_cb structure for historical positions.'
PARTITIONED BY (
    as_of_dt            STRING      COMMENT 'Snapshot date partition (YYYY-MM-DD)'
)
STORED AS ORC
TBLPROPERTIES (
    'orc.compress' = 'SNAPPY',
    'transactional' = 'false'
);


-- =============================================================================
-- 5. AUDIT LAYER: audit.cad_arrg_dim
-- =============================================================================
-- Contract Arrangement Dimension.
-- Dimensional reference table combining contract terms, product details,
-- and property information. Used for slice-and-dice analysis in the
-- audit layer. Populated from td_contracts + CDW_LN_PROD mappings.
-- Both DAILY and MOEND versions maintained for SCD Type 2 tracking.
-- =============================================================================
DROP TABLE IF EXISTS audit.cad_arrg_dim;

CREATE TABLE audit.cad_arrg_dim (
    -- Surrogate key for the dimension
    arrg_dim_sk         BIGINT      COMMENT 'Surrogate key for arrangement dimension',

    -- Data source indicator
    -- DAILY ('D'): reflects intra-month arrangement changes (e.g. modifications)
    -- MOEND ('M'): official month-end arrangement snapshot
    data_src_ind        STRING      COMMENT 'Load frequency: D=DAILY, M=MOEND',

    -- Natural keys
    ln_acct_nbr         STRING      COMMENT 'Loan account number (natural key)',
    borr_id             STRING      COMMENT 'Borrower external ID',

    -- Product details (from CDW_LN_PROD via column_mappings.md)
    prod_cd             STRING      COMMENT 'Product code -> modern code (direct copy)',
    prod_desc_txt       STRING      COMMENT 'Product description -> modern name (direct copy)',
    prod_typ_cd         STRING      COMMENT 'Product type: FXD, ARM, FHA, VA -> modern type',
    prod_rt_typ         STRING      COMMENT 'Rate type: FIXED, VARIABLE -> modern rate_type',
    prod_term_mos       INT         COMMENT 'Product term months -> INT (modern term_months)',
    prod_min_amt        DECIMAL(12,2) COMMENT 'Min loan amount -> DECIMAL (modern min_amount)',
    prod_max_amt        DECIMAL(12,2) COMMENT 'Max loan amount -> DECIMAL (modern max_amount)',
    prod_is_active      STRING      COMMENT 'Product active flag: ACT->true, INA->false (modern is_active)',
    prod_eff_dt         DATE        COMMENT 'Product effective date -> DATE (modern effective_date)',
    prod_exp_dt         DATE        COMMENT 'Product expiration date -> DATE (modern expiration_date)',

    -- Contract terms (typed per mapping)
    ln_int_rt           DECIMAL(5,3)    COMMENT 'Interest rate -> DECIMAL (modern interest_rate)',
    ln_term_mos         INT             COMMENT 'Contract term months -> INT (modern term_months)',
    ln_orig_dt          DATE            COMMENT 'Origination date -> DATE (modern origination_date)',
    ln_mat_dt           DATE            COMMENT 'Maturity date -> DATE (modern maturity_date)',

    -- Property details (from CDW_LN_ACCT property columns via mapping)
    prop_addr_ln1       STRING      COMMENT 'Property address -> modern property_address (direct copy)',
    prop_cty_nm         STRING      COMMENT 'Property city -> modern property_city (direct copy)',
    prop_st_cd          STRING      COMMENT 'Property state -> modern property_state (direct copy)',
    prop_zip_cd         STRING      COMMENT 'Property zip -> modern property_zip (direct copy)',
    prop_typ_cd         STRING      COMMENT 'Property type expanded: SFR->Single Family, CND->Condominium',
    prop_aprs_val       DECIMAL(12,2) COMMENT 'Appraised value -> DECIMAL (modern appraised_value)',

    -- Status (expanded per mapping)
    ln_stat_cd          STRING      COMMENT 'Loan status expanded: ACT->ACTIVE, CLO->CLOSED, etc.',

    -- SCD Type 2 tracking columns
    rec_eff_dt          DATE        COMMENT 'Effective start date for this dimension version',
    rec_exp_dt          DATE        COMMENT 'Effective end date (9999-12-31 for current)',
    curr_rec_ind        STRING      COMMENT 'Current record indicator: Y or N',

    -- Audit / ETL metadata
    src_sys_cd          STRING      COMMENT 'Source system code',
    etl_load_ts         TIMESTAMP   COMMENT 'ETL load timestamp'
)
COMMENT 'Audit dimension: contract arrangement details combining product, terms, and property info. SCD Type 2.'
PARTITIONED BY (
    as_of_dt            STRING      COMMENT 'Snapshot date partition (YYYY-MM-DD)'
)
STORED AS ORC
TBLPROPERTIES (
    'orc.compress' = 'SNAPPY',
    'transactional' = 'false'
);


-- =============================================================================
-- 6. AUDIT LAYER: audit.cad_actg_unit_bal_fact
-- =============================================================================
-- Accounting Unit Balance Fact - Current Contracts.
-- Fact table containing balance and payment measures for active/forbearance
-- contracts. Grain: one row per contract per snapshot date per data_src_ind.
-- Joins to audit.cad_arrg_dim on arrg_dim_sk for dimensional analysis.
-- Maps to CDW_LN_ACCT balance + CDW_PMT_HIST payment columns.
-- =============================================================================
DROP TABLE IF EXISTS audit.cad_actg_unit_bal_fact;

CREATE TABLE audit.cad_actg_unit_bal_fact (
    -- Dimension foreign key
    arrg_dim_sk         BIGINT      COMMENT 'FK to audit.cad_arrg_dim surrogate key',

    -- Data source indicator
    -- DAILY ('D'): intra-month balance and payment activity
    -- MOEND ('M'): month-end official balance position for financial reporting
    data_src_ind        STRING      COMMENT 'Load frequency: D=DAILY, M=MOEND',

    -- Natural keys
    ln_acct_nbr         STRING      COMMENT 'Loan account number',
    borr_id             STRING      COMMENT 'Borrower external ID',

    -- Balance measures (typed per column_mappings.md)
    ln_orig_amt         DECIMAL(12,2)   COMMENT 'Original loan amount -> DECIMAL (modern original_amount)',
    ln_curr_bal         DECIMAL(12,2)   COMMENT 'Current balance -> DECIMAL (modern current_balance)',
    ln_escrow_bal       DECIMAL(10,2)   COMMENT 'Escrow balance -> DECIMAL (modern escrow_balance)',
    ln_ltv_pct          DECIMAL(5,2)    COMMENT 'Loan-to-value percent -> DECIMAL (modern ltv_percent)',
    ln_pmt_amt          DECIMAL(10,2)   COMMENT 'Monthly payment -> DECIMAL (modern monthly_payment)',

    -- Delinquency measure
    ln_dlq_days         INT             COMMENT 'Delinquency days -> INT (modern delinquency_days)',

    -- Latest payment details (from CDW_PMT_HIST via mapping)
    last_pmt_dt         DATE            COMMENT 'Last payment date parsed -> DATE (from CDW_PMT_HIST.PMT_DT)',
    last_pmt_amt        DECIMAL(10,2)   COMMENT 'Last payment total -> DECIMAL (from CDW_PMT_HIST.PMT_AMT)',
    last_pmt_prin_amt   DECIMAL(10,2)   COMMENT 'Last principal portion -> DECIMAL (from CDW_PMT_HIST.PMT_PRIN_AMT)',
    last_pmt_int_amt    DECIMAL(10,2)   COMMENT 'Last interest portion -> DECIMAL (from CDW_PMT_HIST.PMT_INT_AMT)',
    last_pmt_escrow_amt DECIMAL(10,2)   COMMENT 'Last escrow portion -> DECIMAL (from CDW_PMT_HIST.PMT_ESCROW_AMT)',
    last_pmt_late_fee   DECIMAL(10,2)   COMMENT 'Last late fee -> DECIMAL (from CDW_PMT_HIST.PMT_LATE_FEE)',

    -- Payment type and status (expanded per mapping)
    last_pmt_typ_cd     STRING      COMMENT 'Payment type: REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT',
    last_pmt_stat_cd    STRING      COMMENT 'Payment status: PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING',

    -- Loan status (expanded per mapping)
    ln_stat_cd          STRING      COMMENT 'Loan status expanded: ACT->ACTIVE, FRB->FORBEARANCE',

    -- Appraised value for LTV calculations
    prop_aprs_val       DECIMAL(12,2)   COMMENT 'Appraised value -> DECIMAL (modern appraised_value)',

    -- Audit / ETL metadata
    src_sys_cd          STRING      COMMENT 'Source system code',
    etl_load_ts         TIMESTAMP   COMMENT 'ETL load timestamp'
)
COMMENT 'Audit fact: current contract balances and payment activity. Grain = contract x snapshot x data_src_ind.'
PARTITIONED BY (
    as_of_dt            STRING      COMMENT 'Snapshot date partition (YYYY-MM-DD)'
)
STORED AS ORC
TBLPROPERTIES (
    'orc.compress' = 'SNAPPY',
    'transactional' = 'false'
);


-- =============================================================================
-- 7. AUDIT LAYER: audit.cad_nc_actg_unit_bal_fact
-- =============================================================================
-- Non-Current Accounting Unit Balance Fact.
-- Fact table for closed/defaulted contract balances. Structure mirrors
-- cad_actg_unit_bal_fact but captures the terminal state of non-current
-- contracts. Used for charge-off reporting and loss provisioning.
-- Contracts with ln_stat_cd IN ('CLO','DFT') flow here.
-- MOEND snapshots are primary; DAILY captures intra-month closures.
-- =============================================================================
DROP TABLE IF EXISTS audit.cad_nc_actg_unit_bal_fact;

CREATE TABLE audit.cad_nc_actg_unit_bal_fact (
    -- Dimension foreign key
    arrg_dim_sk         BIGINT      COMMENT 'FK to audit.cad_arrg_dim surrogate key',

    -- Data source indicator
    -- DAILY ('D'): captures intra-month closures and defaults as they happen
    -- MOEND ('M'): official month-end non-current position for regulatory reporting
    data_src_ind        STRING      COMMENT 'Load frequency: D=DAILY, M=MOEND',

    -- Natural keys
    ln_acct_nbr         STRING      COMMENT 'Loan account number',
    borr_id             STRING      COMMENT 'Borrower external ID',

    -- Balance measures at closure (typed per column_mappings.md)
    ln_orig_amt         DECIMAL(12,2)   COMMENT 'Original loan amount -> DECIMAL',
    ln_curr_bal         DECIMAL(12,2)   COMMENT 'Remaining balance at closure -> DECIMAL',
    ln_escrow_bal       DECIMAL(10,2)   COMMENT 'Escrow balance at closure -> DECIMAL',
    ln_ltv_pct          DECIMAL(5,2)    COMMENT 'LTV percent at closure -> DECIMAL',
    ln_pmt_amt          DECIMAL(10,2)   COMMENT 'Last scheduled payment -> DECIMAL',

    -- Delinquency measure at closure
    ln_dlq_days         INT             COMMENT 'Delinquency days at closure -> INT',

    -- Final payment details (from CDW_PMT_HIST)
    last_pmt_dt         DATE            COMMENT 'Last payment date before closure -> DATE',
    last_pmt_amt        DECIMAL(10,2)   COMMENT 'Last payment total before closure -> DECIMAL',
    last_pmt_prin_amt   DECIMAL(10,2)   COMMENT 'Last principal portion -> DECIMAL',
    last_pmt_int_amt    DECIMAL(10,2)   COMMENT 'Last interest portion -> DECIMAL',
    last_pmt_escrow_amt DECIMAL(10,2)   COMMENT 'Last escrow portion -> DECIMAL',
    last_pmt_late_fee   DECIMAL(10,2)   COMMENT 'Last late fee -> DECIMAL',

    -- Payment type and status (expanded per mapping)
    last_pmt_typ_cd     STRING      COMMENT 'Payment type expanded: REG->REGULAR, EXT->EXTRA, PRT->PARTIAL, PRE->PREPAYMENT',
    last_pmt_stat_cd    STRING      COMMENT 'Payment status expanded: PST->POSTED, REV->REVERSED, NSF->NSF, PND->PENDING',

    -- Loan status (expanded per mapping)
    ln_stat_cd          STRING      COMMENT 'Non-current status expanded: CLO->CLOSED, DFT->DEFAULT',

    -- Closure details
    closure_dt          DATE            COMMENT 'Date the contract was closed or defaulted',
    closure_reason_cd   STRING          COMMENT 'Closure reason: PAID_OFF, CHARGED_OFF, REFINANCED',

    -- Loss provisioning
    loss_amt            DECIMAL(12,2)   COMMENT 'Calculated loss amount (orig_amt - recoveries)',
    recovery_amt        DECIMAL(12,2)   COMMENT 'Amount recovered post-default',

    -- Appraised value for LTV at closure
    prop_aprs_val       DECIMAL(12,2)   COMMENT 'Appraised value at closure -> DECIMAL',

    -- Audit / ETL metadata
    src_sys_cd          STRING      COMMENT 'Source system code',
    etl_load_ts         TIMESTAMP   COMMENT 'ETL load timestamp'
)
COMMENT 'Audit fact: non-current contract balances at closure. For charge-off reporting and loss provisioning.'
PARTITIONED BY (
    as_of_dt            STRING      COMMENT 'Snapshot date partition (YYYY-MM-DD)'
)
STORED AS ORC
TBLPROPERTIES (
    'orc.compress' = 'SNAPPY',
    'transactional' = 'false'
);


-- =============================================================================
-- VALIDATION VIEWS
-- =============================================================================
-- Convenience views for validating data_src_ind logic across load frequencies.
-- These demonstrate how DAILY and MOEND records should be queried.
-- =============================================================================

-- View: DAILY-only current balance records for intra-month monitoring
CREATE VIEW IF NOT EXISTS audit.v_daily_actg_bal AS
SELECT *
FROM   audit.cad_actg_unit_bal_fact
WHERE  data_src_ind = 'D'
    -- DAILY records: loaded every business day for real-time balance tracking
;

-- View: MOEND-only current balance records for month-end reporting
CREATE VIEW IF NOT EXISTS audit.v_moend_actg_bal AS
SELECT *
FROM   audit.cad_actg_unit_bal_fact
WHERE  data_src_ind = 'M'
    -- MOEND records: loaded at month-end for official financial reporting
;

-- View: DAILY-only non-current balance records
CREATE VIEW IF NOT EXISTS audit.v_daily_nc_actg_bal AS
SELECT *
FROM   audit.cad_nc_actg_unit_bal_fact
WHERE  data_src_ind = 'D'
    -- DAILY non-current: captures intra-month closures and defaults
;

-- View: MOEND-only non-current balance records for regulatory reporting
CREATE VIEW IF NOT EXISTS audit.v_moend_nc_actg_bal AS
SELECT *
FROM   audit.cad_nc_actg_unit_bal_fact
WHERE  data_src_ind = 'M'
    -- MOEND non-current: official month-end non-current position
;

-- =============================================================================
-- DATA_SRC_IND LOGIC REFERENCE
-- =============================================================================
-- The data_src_ind column encodes the load frequency for each record:
--
-- +----------+-------+----------------------------------------------------------+
-- | Value    | Label | Description                                              |
-- +----------+-------+----------------------------------------------------------+
-- | 'D'      | DAILY | Business-day snapshot. Loaded every trading day.          |
-- |          |       | Use for intra-month monitoring, real-time dashboards,     |
-- |          |       | and operational reporting.                                |
-- +----------+-------+----------------------------------------------------------+
-- | 'M'      | MOEND | Month-end snapshot. Loaded on the last business day of    |
-- |          |       | each month. Use for official financial reporting,          |
-- |          |       | regulatory submissions, and period-close reconciliation.  |
-- +----------+-------+----------------------------------------------------------+
--
-- Typical query patterns:
--   DAILY only:  WHERE data_src_ind = 'D' AND as_of_dt = '2024-01-15'
--   MOEND only:  WHERE data_src_ind = 'M' AND as_of_dt = '2024-01-31'
--   Both:        No filter on data_src_ind (union of both frequencies)
--
-- In staging (work_schema), both DAILY and MOEND records coexist.
-- In audit tables, views (v_daily_*, v_moend_*) provide pre-filtered access.
-- =============================================================================
