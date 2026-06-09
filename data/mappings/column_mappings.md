# Legacy to Modern Column Mappings

## CDW_BORR_MSTR → borrowers

| Legacy Column | Legacy Type | Modern Column | Modern Type | Transformation |
|---------------|-------------|---------------|-------------|----------------|
| `BORR_ID` | VARCHAR(20) | `external_id` | VARCHAR(20) | Direct copy |
| `BORR_FST_NM` | VARCHAR(50) | `first_name` | VARCHAR(50) | Direct copy |
| `BORR_LST_NM` | VARCHAR(50) | `last_name` | VARCHAR(50) | Direct copy |
| `BORR_MID_INIT` | VARCHAR(1) | `middle_initial` | VARCHAR(1) | Direct copy |
| `BORR_SSN_ENCR` | VARCHAR(100) | `ssn_hash` | VARCHAR(100) | Direct copy (re-encrypt recommended) |
| `BORR_DOB_DT` | VARCHAR(10) | `date_of_birth` | DATE | Parse MM/DD/YYYY → DATE |
| `BORR_ADDR_LN1` | VARCHAR(100) | `address_line1` | VARCHAR(100) | Direct copy |
| `BORR_ADDR_LN2` | VARCHAR(100) | `address_line2` | VARCHAR(100) | Direct copy |
| `BORR_CTY_NM` | VARCHAR(50) | `city` | VARCHAR(50) | Direct copy |
| `BORR_ST_CD` | VARCHAR(2) | `state` | VARCHAR(2) | Direct copy |
| `BORR_ZIP_CD` | VARCHAR(10) | `zip_code` | VARCHAR(10) | Direct copy |
| `BORR_PH_NBR` | VARCHAR(15) | `phone` | VARCHAR(15) | Direct copy |
| `BORR_EMAIL_ADDR` | VARCHAR(100) | `email` | VARCHAR(100) | Direct copy |
| `BORR_CRDT_SCR` | VARCHAR(5) | `credit_score` | INTEGER | Parse string → integer |
| `BORR_EMP_STAT` | VARCHAR(20) | `employment_status` | VARCHAR(20) | Direct copy |
| `BORR_ANN_INCM` | VARCHAR(15) | `annual_income` | DECIMAL(12,2) | Remove commas, parse → decimal |
| `BORR_CRET_DT` | VARCHAR(10) | `created_at` | TIMESTAMP | Parse MM/DD/YYYY → timestamp |
| `BORR_UPDT_DT` | VARCHAR(10) | `updated_at` | TIMESTAMP | Parse MM/DD/YYYY → timestamp |
| `BORR_STAT_CD` | VARCHAR(5) | `status` | VARCHAR(10) | Expand: ACT→ACTIVE, INA→INACTIVE |
| `BORR_REC_TYP` | VARCHAR(10) | *(dropped)* | — | Not needed in modern schema |

## CDW_LN_PROD → loan_products

| Legacy Column | Legacy Type | Modern Column | Modern Type | Transformation |
|---------------|-------------|---------------|-------------|----------------|
| `PROD_CD` | VARCHAR(10) | `code` | VARCHAR(10) | Direct copy |
| `PROD_DESC_TXT` | VARCHAR(200) | `name` | VARCHAR(200) | Direct copy |
| `PROD_TYP_CD` | VARCHAR(5) | `type` | VARCHAR(5) | Direct copy |
| `PROD_TERM_MOS` | VARCHAR(5) | `term_months` | INTEGER | Parse string → integer |
| `PROD_RT_TYP` | VARCHAR(10) | `rate_type` | VARCHAR(10) | Direct copy |
| `PROD_MIN_AMT` | VARCHAR(15) | `min_amount` | DECIMAL(12,2) | Remove commas, parse → decimal |
| `PROD_MAX_AMT` | VARCHAR(15) | `max_amount` | DECIMAL(12,2) | Remove commas, parse → decimal |
| `PROD_STAT_CD` | VARCHAR(5) | `is_active` | BOOLEAN | ACT→true, INA→false |
| `PROD_EFF_DT` | VARCHAR(10) | `effective_date` | DATE | Parse MM/DD/YYYY → DATE |
| `PROD_EXP_DT` | VARCHAR(10) | `expiration_date` | DATE | Parse MM/DD/YYYY → DATE |

## CDW_LN_ACCT → loan_accounts

| Legacy Column | Legacy Type | Modern Column | Modern Type | Transformation |
|---------------|-------------|---------------|-------------|----------------|
| `LN_ACCT_NBR` | VARCHAR(20) | `account_number` | VARCHAR(20) | Direct copy |
| `BORR_ID` | VARCHAR(20) | `borrower_id` | BIGINT | Lookup borrowers.id by external_id |
| `BORR_FST_NM` | VARCHAR(50) | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_LST_NM` | VARCHAR(50) | *(dropped)* | — | Denormalized; use borrower FK |
| `BORR_SSN_LST4` | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK |
| `PROD_CD` | VARCHAR(10) | `product_id` | BIGINT | Lookup loan_products.id by code |
| `LN_ORIG_AMT` | VARCHAR(15) | `original_amount` | DECIMAL(12,2) | Remove commas, parse → decimal |
| `LN_CURR_BAL` | VARCHAR(15) | `current_balance` | DECIMAL(12,2) | Remove commas, parse → decimal |
| `LN_INT_RT` | VARCHAR(8) | `interest_rate` | DECIMAL(5,3) | Parse string → decimal |
| `LN_TERM_MOS` | VARCHAR(5) | `term_months` | INTEGER | Parse string → integer |
| `LN_PMT_AMT` | VARCHAR(15) | `monthly_payment` | DECIMAL(10,2) | Remove commas, parse → decimal |
| `LN_ORIG_DT` | VARCHAR(10) | `origination_date` | DATE | Parse MM/DD/YYYY → DATE |
| `LN_MAT_DT` | VARCHAR(10) | `maturity_date` | DATE | Parse MM/DD/YYYY → DATE |
| `LN_1ST_PMT_DT` | VARCHAR(10) | `first_payment_date` | DATE | Parse MM/DD/YYYY → DATE |
| `LN_NXT_PMT_DT` | VARCHAR(10) | `next_payment_date` | DATE | Parse MM/DD/YYYY → DATE |
| `LN_STAT_CD` | VARCHAR(5) | `status` | VARCHAR(15) | Expand: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE, DLQ→DELINQUENT |
| `LN_DLQ_DAYS` | VARCHAR(5) | `delinquency_days` | INTEGER | Parse string → integer |
| `LN_ESCROW_BAL` | VARCHAR(15) | `escrow_balance` | DECIMAL(10,2) | Remove commas, parse → decimal |
| `LN_LTV_PCT` | VARCHAR(8) | `ltv_percent` | DECIMAL(5,2) | Parse string → decimal |
| `PROP_ADDR_LN1` | VARCHAR(100) | `property_address` | VARCHAR(100) | Direct copy |
| `PROP_CTY_NM` | VARCHAR(50) | `property_city` | VARCHAR(50) | Direct copy |
| `PROP_ST_CD` | VARCHAR(2) | `property_state` | VARCHAR(2) | Direct copy |
| `PROP_ZIP_CD` | VARCHAR(10) | `property_zip` | VARCHAR(10) | Direct copy |
| `PROP_TYP_CD` | VARCHAR(10) | `property_type` | VARCHAR(30) | Expand: SFR→Single Family, CND→Condominium, etc. |
| `PROP_APRS_VAL` | VARCHAR(15) | `appraised_value` | DECIMAL(12,2) | Remove commas, parse → decimal |
| `LN_CRET_DT` | VARCHAR(10) | `created_at` | TIMESTAMP | Parse MM/DD/YYYY → timestamp |
| `LN_UPDT_DT` | VARCHAR(10) | `updated_at` | TIMESTAMP | Parse MM/DD/YYYY → timestamp |

## CDW_PMT_HIST → payments

| Legacy Column | Legacy Type | Modern Column | Modern Type | Transformation |
|---------------|-------------|---------------|-------------|----------------|
| `PMT_SEQ_NBR` | VARCHAR(20) | `id` | BIGINT | Auto-generated; legacy ID stored if needed |
| `LN_ACCT_NBR` | VARCHAR(20) | `loan_account_id` | BIGINT | Lookup loan_accounts.id by account_number |
| `PMT_DT` | VARCHAR(10) | `payment_date` | DATE | Parse MM/DD/YYYY → DATE |
| `PMT_AMT` | VARCHAR(15) | `total_amount` | DECIMAL(10,2) | Remove commas, parse → decimal |
| `PMT_PRIN_AMT` | VARCHAR(15) | `principal_amount` | DECIMAL(10,2) | Remove commas, parse → decimal |
| `PMT_INT_AMT` | VARCHAR(15) | `interest_amount` | DECIMAL(10,2) | Remove commas, parse → decimal |
| `PMT_ESCROW_AMT` | VARCHAR(15) | `escrow_amount` | DECIMAL(10,2) | Remove commas, parse → decimal |
| `PMT_LATE_FEE` | VARCHAR(15) | `late_fee` | DECIMAL(10,2) | Remove commas, parse → decimal |
| `PMT_TYP_CD` | VARCHAR(5) | `type` | VARCHAR(15) | Expand: REG→REGULAR, EXT→EXTRA, PRT→PARTIAL, PRE→PREPAYMENT |
| `PMT_STAT_CD` | VARCHAR(5) | `status` | VARCHAR(15) | Expand: PST→POSTED, REV→REVERSED, NSF→NSF, PND→PENDING |
| `PMT_RECV_DT` | VARCHAR(10) | `received_date` | DATE | Parse MM/DD/YYYY → DATE |
| `PMT_PROC_DT` | VARCHAR(10) | `processed_date` | DATE | Parse MM/DD/YYYY → DATE |
| `PMT_CRET_DT` | VARCHAR(10) | `created_at` | TIMESTAMP | Parse MM/DD/YYYY → timestamp |
| `PMT_UPDT_DT` | VARCHAR(10) | `updated_at` | TIMESTAMP | Parse MM/DD/YYYY → timestamp |

## Common Transformation Patterns

1. **Date conversion:** `MM/DD/YYYY` string → `DATE` or `TIMESTAMP` type
2. **Amount conversion:** Remove commas from string, parse to `DECIMAL`
3. **Status expansion:** Short codes → readable values (ACT→ACTIVE, etc.)
4. **Denormalization removal:** Drop borrower fields from loan_accounts, use FK instead
5. **ID resolution:** Legacy string IDs → modern auto-increment BIGINT with FK lookups
