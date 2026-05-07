"""
Delta Lake schema definition for the borrowers dimension table.

Migrated from legacy CDW_BORR_MSTR (all-VARCHAR, cryptic column names)
to a strongly-typed, cleanly-named borrower dimension.

Partitioned by: status (low cardinality; supports common filtered queries
such as "all active borrowers").
"""

from pyspark.sql.types import (
    DateType,
    DecimalType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

BORROWERS_SCHEMA = StructType([
    StructField("id", LongType(), nullable=False),
    StructField("external_id", StringType(), nullable=False),
    StructField("first_name", StringType(), nullable=False),
    StructField("last_name", StringType(), nullable=False),
    StructField("middle_initial", StringType(), nullable=True),
    StructField("ssn_hash", StringType(), nullable=True),
    StructField("date_of_birth", DateType(), nullable=True),
    StructField("address_line1", StringType(), nullable=True),
    StructField("address_line2", StringType(), nullable=True),
    StructField("city", StringType(), nullable=True),
    StructField("state", StringType(), nullable=True),
    StructField("zip_code", StringType(), nullable=True),
    StructField("phone", StringType(), nullable=True),
    StructField("email", StringType(), nullable=True),
    StructField("credit_score", IntegerType(), nullable=True),
    StructField("employment_status", StringType(), nullable=True),
    StructField("annual_income", DecimalType(12, 2), nullable=True),
    StructField("status", StringType(), nullable=False),
    StructField("created_at", TimestampType(), nullable=True),
    StructField("updated_at", TimestampType(), nullable=True),
])

BORROWERS_TABLE_NAME = "loan_warehouse.borrowers"
BORROWERS_PARTITION_COLS = ["status"]
BORROWERS_PATH = "/mnt/delta/loan_warehouse/borrowers"

BORROWERS_DDL = """
CREATE TABLE IF NOT EXISTS loan_warehouse.borrowers (
    id              BIGINT        NOT NULL,
    external_id     STRING        NOT NULL,
    first_name      STRING        NOT NULL,
    last_name       STRING        NOT NULL,
    middle_initial  STRING,
    ssn_hash        STRING,
    date_of_birth   DATE,
    address_line1   STRING,
    address_line2   STRING,
    city            STRING,
    state           STRING,
    zip_code        STRING,
    phone           STRING,
    email           STRING,
    credit_score    INT,
    employment_status STRING,
    annual_income   DECIMAL(12,2),
    status          STRING        NOT NULL,
    created_at      TIMESTAMP,
    updated_at      TIMESTAMP
)
USING DELTA
PARTITIONED BY (status)
LOCATION '/mnt/delta/loan_warehouse/borrowers'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
)
"""

# Legacy-to-modern column mapping reference
COLUMN_MAPPING = {
    "BORR_ID":         "external_id",
    "BORR_FST_NM":     "first_name",
    "BORR_LST_NM":     "last_name",
    "BORR_MID_INIT":   "middle_initial",
    "BORR_SSN_ENCR":   "ssn_hash",
    "BORR_DOB_DT":     "date_of_birth",
    "BORR_ADDR_LN1":   "address_line1",
    "BORR_ADDR_LN2":   "address_line2",
    "BORR_CTY_NM":     "city",
    "BORR_ST_CD":      "state",
    "BORR_ZIP_CD":     "zip_code",
    "BORR_PH_NBR":     "phone",
    "BORR_EMAIL_ADDR":  "email",
    "BORR_CRDT_SCR":   "credit_score",
    "BORR_EMP_STAT":   "employment_status",
    "BORR_ANN_INCM":   "annual_income",
    "BORR_STAT_CD":    "status",
    "BORR_CRET_DT":    "created_at",
    "BORR_UPDT_DT":    "updated_at",
    # BORR_REC_TYP is intentionally dropped (not needed in modern schema)
}
