"""
Delta Lake schema definition for the payments table.

Migrated from legacy CDW_PMT_HIST.

Partitioned by: status
  - Payment status (POSTED, REVERSED, NSF, PENDING) is the dominant filter
    in reconciliation and reporting queries.
  - Low cardinality keeps partition count small.
"""

from pyspark.sql.types import (
    DateType,
    DecimalType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

PAYMENTS_SCHEMA = StructType([
    StructField("id", LongType(), nullable=False),
    StructField("loan_account_id", LongType(), nullable=False),
    StructField("payment_date", DateType(), nullable=False),
    StructField("total_amount", DecimalType(10, 2), nullable=False),
    StructField("principal_amount", DecimalType(10, 2), nullable=True),
    StructField("interest_amount", DecimalType(10, 2), nullable=True),
    StructField("escrow_amount", DecimalType(10, 2), nullable=True),
    StructField("late_fee", DecimalType(10, 2), nullable=True),
    StructField("type", StringType(), nullable=False),
    StructField("status", StringType(), nullable=False),
    StructField("received_date", DateType(), nullable=True),
    StructField("processed_date", DateType(), nullable=True),
    StructField("legacy_sequence_number", StringType(), nullable=True),
    StructField("created_at", TimestampType(), nullable=True),
    StructField("updated_at", TimestampType(), nullable=True),
])

PAYMENTS_TABLE_NAME = "loan_warehouse.payments"
PAYMENTS_PARTITION_COLS = ["status"]
PAYMENTS_PATH = "/mnt/delta/loan_warehouse/payments"

PAYMENTS_DDL = """
CREATE TABLE IF NOT EXISTS loan_warehouse.payments (
    id                      BIGINT          NOT NULL,
    loan_account_id         BIGINT          NOT NULL,
    payment_date            DATE            NOT NULL,
    total_amount            DECIMAL(10,2)   NOT NULL,
    principal_amount        DECIMAL(10,2),
    interest_amount         DECIMAL(10,2),
    escrow_amount           DECIMAL(10,2),
    late_fee                DECIMAL(10,2),
    type                    STRING          NOT NULL,
    status                  STRING          NOT NULL,
    received_date           DATE,
    processed_date          DATE,
    legacy_sequence_number  STRING,
    created_at              TIMESTAMP,
    updated_at              TIMESTAMP
)
USING DELTA
PARTITIONED BY (status)
LOCATION '/mnt/delta/loan_warehouse/payments'
TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
)
"""

COLUMN_MAPPING = {
    "PMT_SEQ_NBR":     "legacy_sequence_number",
    "LN_ACCT_NBR":     "loan_account_id",  # resolved via loan_accounts lookup
    "PMT_DT":          "payment_date",
    "PMT_AMT":         "total_amount",
    "PMT_PRIN_AMT":    "principal_amount",
    "PMT_INT_AMT":     "interest_amount",
    "PMT_ESCROW_AMT":  "escrow_amount",
    "PMT_LATE_FEE":    "late_fee",
    "PMT_TYP_CD":      "type",
    "PMT_STAT_CD":     "status",
    "PMT_RECV_DT":     "received_date",
    "PMT_PROC_DT":     "processed_date",
    "PMT_CRET_DT":     "created_at",
    "PMT_UPDT_DT":     "updated_at",
}

PAYMENT_TYPE_CODES = {
    "REG": "REGULAR",
    "EXT": "EXTRA",
    "PRT": "PARTIAL",
    "PRE": "PREPAYMENT",
}

PAYMENT_STATUS_CODES = {
    "PST": "POSTED",
    "REV": "REVERSED",
    "NSF": "NSF",
    "PND": "PENDING",
}
