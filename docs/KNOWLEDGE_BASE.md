# Knowledge Base — Loan Service (Data Source Migration)

## 1. Architecture Overview

### System Context

The **Loan Service** is a Spring Boot 3.2 monolithic microservice that exposes a REST API for querying loan, borrower, and payment data. It currently reads from a **legacy Corporate Data Warehouse (CDW)** schema simulated via an in-memory H2 database. The planned migration target is a normalized **modern relational schema** (also H2 for now, but designed to be database-agnostic).

```
┌────────────────────────────────────────────────────┐
│              Loan Service (Spring Boot 3.2)         │
│                                                    │
│  ┌──────────────┐    ┌──────────────┐              │
│  │ BorrowerCtrl │    │  LoanCtrl    │  REST Layer  │
│  └──────┬───────┘    └──────┬───────┘              │
│         │                   │                      │
│         └─────────┬─────────┘                      │
│                   ▼                                │
│          ┌────────────────┐                        │
│          │  LoanService   │  Service / Translation │
│          └────────┬───────┘                        │
│                   │                                │
│    ┌──────────────┼──────────────┐                 │
│    ▼              ▼              ▼                  │
│ LegacyBorrower LegacyLoanAcct LegacyPayment  Repos│
│ Repository     Repository      Repository          │
│    │              │              │                  │
│    └──────────────┼──────────────┘                  │
│                   ▼                                │
│        ┌─────────────────────┐                     │
│        │  H2 In-Memory DB    │                     │
│        │  (Legacy CDW Schema)│                     │
│        └─────────────────────┘                     │
└────────────────────────────────────────────────────┘
```

### Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Java | 17 |
| Framework | Spring Boot | 3.2.3 |
| ORM | Spring Data JPA / Hibernate | (managed by Spring Boot BOM) |
| Database | H2 (in-memory) | (managed by Spring Boot BOM) |
| Build | Apache Maven | Wrapper included |
| Testing | JUnit 5 / Spring Boot Test | (managed by Spring Boot BOM) |

### Dependency Inventory (from `pom.xml`)

| Dependency | Scope | Purpose |
|-----------|-------|---------|
| `spring-boot-starter-web` | compile | REST API, embedded Tomcat |
| `spring-boot-starter-data-jpa` | compile | JPA repositories, Hibernate ORM |
| `h2` | runtime | In-memory database for legacy DW simulation |
| `spring-boot-starter-test` | test | JUnit 5, MockMvc, Spring test context |

### Project Structure

```
uc-data-source-migration-legacy-to-modern/
├── pom.xml                              # Maven build definition
├── README.md                            # Project overview & quick start
├── data/
│   ├── legacy-schema/cdw_tables.sql     # Legacy DDL documentation
│   ├── modern-schema/modern_tables.sql  # Target modern DDL
│   └── mappings/column_mappings.md      # Legacy→modern field mapping reference
├── docs/
│   └── MIGRATION_TASKS.md              # Workshop task breakdown
├── src/main/java/com/workshop/loanservice/
│   ├── LoanServiceApplication.java      # Spring Boot entry point
│   ├── controller/
│   │   ├── BorrowerController.java      # /api/borrowers endpoints
│   │   └── LoanController.java          # /api/loans, /api/loans/{id}/payments
│   ├── dto/
│   │   ├── BorrowerDto.java             # API response for borrower data
│   │   ├── LoanSummaryDto.java          # API response for loan data
│   │   └── PaymentDto.java              # API response for payment data
│   ├── entity/
│   │   ├── LegacyBorrower.java          # CDW_BORR_MSTR JPA entity
│   │   ├── LegacyLoanAccount.java       # CDW_LN_ACCT JPA entity
│   │   ├── LegacyLoanProduct.java       # CDW_LN_PROD JPA entity
│   │   └── LegacyPayment.java           # CDW_PMT_HIST JPA entity
│   ├── repository/
│   │   ├── LegacyBorrowerRepository.java
│   │   ├── LegacyLoanAccountRepository.java
│   │   ├── LegacyLoanProductRepository.java
│   │   └── LegacyPaymentRepository.java
│   └── service/
│       └── LoanService.java             # Business logic + legacy data translation
├── src/main/resources/
│   ├── application.properties           # App config (H2, JPA, SQL init)
│   ├── schema-legacy.sql                # Legacy CDW DDL (4 tables)
│   └── data-legacy.sql                  # Seed data (5 borrowers, 5 products, 5 loans, 10 payments)
└── src/test/java/com/workshop/loanservice/
    └── LoanServiceApplicationTests.java # Single context-load smoke test
```

---

## 2. Data Models

### Legacy Schema (Current State)

All four legacy tables use **VARCHAR for every column** — dates, amounts, integers, and codes are all stored as strings. There are **no foreign key constraints**.

#### CDW_BORR_MSTR (Borrower Master)

| Column | Type | Description |
|--------|------|-------------|
| `BORR_ID` (PK) | VARCHAR(20) | Borrower identifier |
| `BORR_FST_NM` | VARCHAR(50) | First name |
| `BORR_LST_NM` | VARCHAR(50) | Last name |
| `BORR_MID_INIT` | VARCHAR(1) | Middle initial |
| `BORR_SSN_ENCR` | VARCHAR(100) | Encrypted SSN |
| `BORR_DOB_DT` | VARCHAR(10) | Date of birth (MM/DD/YYYY string) |
| `BORR_ADDR_LN1` | VARCHAR(100) | Address line 1 |
| `BORR_ADDR_LN2` | VARCHAR(100) | Address line 2 |
| `BORR_CTY_NM` | VARCHAR(50) | City |
| `BORR_ST_CD` | VARCHAR(2) | State code |
| `BORR_ZIP_CD` | VARCHAR(10) | ZIP code |
| `BORR_PH_NBR` | VARCHAR(15) | Phone number |
| `BORR_EMAIL_ADDR` | VARCHAR(100) | Email address |
| `BORR_CRDT_SCR` | VARCHAR(5) | Credit score (string) |
| `BORR_EMP_STAT` | VARCHAR(20) | Employment status |
| `BORR_ANN_INCM` | VARCHAR(15) | Annual income (string with commas) |
| `BORR_CRET_DT` | VARCHAR(10) | Created date (MM/DD/YYYY) |
| `BORR_UPDT_DT` | VARCHAR(10) | Updated date (MM/DD/YYYY) |
| `BORR_STAT_CD` | VARCHAR(5) | Status code (ACT, INA) |
| `BORR_REC_TYP` | VARCHAR(10) | Record type |

#### CDW_LN_PROD (Loan Products)

| Column | Type | Description |
|--------|------|-------------|
| `PROD_CD` (PK) | VARCHAR(10) | Product code |
| `PROD_DESC_TXT` | VARCHAR(200) | Product description |
| `PROD_TYP_CD` | VARCHAR(5) | Product type (FXD, ARM, FHA, VA) |
| `PROD_TERM_MOS` | VARCHAR(5) | Term in months (string) |
| `PROD_RT_TYP` | VARCHAR(10) | Rate type (FIXED, VARIABLE) |
| `PROD_MIN_AMT` | VARCHAR(15) | Minimum amount (string) |
| `PROD_MAX_AMT` | VARCHAR(15) | Maximum amount (string) |
| `PROD_STAT_CD` | VARCHAR(5) | Status code |
| `PROD_EFF_DT` | VARCHAR(10) | Effective date (MM/DD/YYYY) |
| `PROD_EXP_DT` | VARCHAR(10) | Expiration date (MM/DD/YYYY) |

#### CDW_LN_ACCT (Loan Accounts — Denormalized)

| Column | Type | Description |
|--------|------|-------------|
| `LN_ACCT_NBR` (PK) | VARCHAR(20) | Loan account number |
| `BORR_ID` | VARCHAR(20) | Borrower ID (no FK) |
| `BORR_FST_NM` | VARCHAR(50) | **Denormalized** borrower first name |
| `BORR_LST_NM` | VARCHAR(50) | **Denormalized** borrower last name |
| `BORR_SSN_LST4` | VARCHAR(4) | **Denormalized** SSN last 4 |
| `PROD_CD` | VARCHAR(10) | Product code (no FK) |
| `LN_ORIG_AMT` | VARCHAR(15) | Original amount (string) |
| `LN_CURR_BAL` | VARCHAR(15) | Current balance (string) |
| `LN_INT_RT` | VARCHAR(8) | Interest rate (string) |
| `LN_TERM_MOS` | VARCHAR(5) | Term months (string) |
| `LN_PMT_AMT` | VARCHAR(15) | Monthly payment (string) |
| `LN_ORIG_DT` | VARCHAR(10) | Origination date (string) |
| `LN_MAT_DT` | VARCHAR(10) | Maturity date (string) |
| `LN_1ST_PMT_DT` | VARCHAR(10) | First payment date (string) |
| `LN_NXT_PMT_DT` | VARCHAR(10) | Next payment date (string) |
| `LN_STAT_CD` | VARCHAR(5) | Status code (ACT, CLO, DFT, FRB) |
| `LN_DLQ_DAYS` | VARCHAR(5) | Delinquency days (string) |
| `LN_ESCROW_BAL` | VARCHAR(15) | Escrow balance (string) |
| `LN_LTV_PCT` | VARCHAR(8) | LTV percentage (string) |
| `PROP_ADDR_LN1` | VARCHAR(100) | Property address |
| `PROP_CTY_NM` | VARCHAR(50) | Property city |
| `PROP_ST_CD` | VARCHAR(2) | Property state |
| `PROP_ZIP_CD` | VARCHAR(10) | Property ZIP |
| `PROP_TYP_CD` | VARCHAR(10) | Property type (SFR, CND, MFR, TWN) |
| `PROP_APRS_VAL` | VARCHAR(15) | Appraised value (string) |
| `LN_CRET_DT` | VARCHAR(10) | Created date (string) |
| `LN_UPDT_DT` | VARCHAR(10) | Updated date (string) |

#### CDW_PMT_HIST (Payment History)

| Column | Type | Description |
|--------|------|-------------|
| `PMT_SEQ_NBR` (PK) | VARCHAR(20) | Payment sequence number |
| `LN_ACCT_NBR` | VARCHAR(20) | Loan account number (no FK) |
| `PMT_DT` | VARCHAR(10) | Payment date (MM/DD/YYYY) |
| `PMT_AMT` | VARCHAR(15) | Total payment amount (string) |
| `PMT_PRIN_AMT` | VARCHAR(15) | Principal portion (string) |
| `PMT_INT_AMT` | VARCHAR(15) | Interest portion (string) |
| `PMT_ESCROW_AMT` | VARCHAR(15) | Escrow portion (string) |
| `PMT_LATE_FEE` | VARCHAR(15) | Late fee (string) |
| `PMT_TYP_CD` | VARCHAR(5) | Payment type (REG, EXT, PRT, PRE) |
| `PMT_STAT_CD` | VARCHAR(5) | Payment status (PST, REV, NSF, PND) |
| `PMT_RECV_DT` | VARCHAR(10) | Received date (string) |
| `PMT_PROC_DT` | VARCHAR(10) | Processed date (string) |
| `PMT_CRET_DT` | VARCHAR(10) | Created date (string) |
| `PMT_UPDT_DT` | VARCHAR(10) | Updated date (string) |

### Modern Schema (Target State)

The modern schema introduces **proper data types**, **foreign key constraints**, **auto-increment PKs**, **indexes**, and **normalized structure**. See `data/modern-schema/modern_tables.sql` for full DDL.

| Table | PK | Key Relationships | Notable Improvements |
|-------|-----|-------------------|---------------------|
| `borrowers` | `id` (BIGINT AUTO_INCREMENT) | — | DATE for DOB, INTEGER for credit score, DECIMAL for income, TIMESTAMP for audit fields |
| `loan_products` | `id` (BIGINT AUTO_INCREMENT) | — | INTEGER for term, DECIMAL for amounts, BOOLEAN for active status |
| `loan_accounts` | `id` (BIGINT AUTO_INCREMENT) | FK → `borrowers.id`, FK → `loan_products.id` | Denormalized borrower fields removed, DECIMAL for all amounts, DATE for all dates |
| `payments` | `id` (BIGINT AUTO_INCREMENT) | FK → `loan_accounts.id` | DECIMAL for all amounts, DATE for dates, expanded status/type strings |

### Seed Data Volume

| Entity | Record Count |
|--------|-------------|
| Borrowers | 5 |
| Loan Products | 5 (FXD30, FXD15, ARM51, FHA30, VA30) |
| Loan Accounts | 5 |
| Payments | 10 (2 per loan) |

---

## 3. API Surface Map

Base URL: `http://localhost:8080`

### BorrowerController (`/api/borrowers`)

| Method | Path | Description | Request | Response |
|--------|------|-------------|---------|----------|
| `GET` | `/api/borrowers` | List all borrowers | — | `List<BorrowerDto>` |
| `GET` | `/api/borrowers/{id}` | Get borrower by ID with associated loans | `id` (path) | `BorrowerDto` (includes `List<LoanSummaryDto>`) |

### LoanController (`/api/loans`)

| Method | Path | Description | Request | Response |
|--------|------|-------------|---------|----------|
| `GET` | `/api/loans` | List all loans | — | `List<LoanSummaryDto>` |
| `GET` | `/api/loans/{id}` | Get loan by account number | `id` (path) | `LoanSummaryDto` |
| `GET` | `/api/loans/{loanId}/payments` | Get payment history for a loan | `loanId` (path) | `List<PaymentDto>` |

### DTO Shapes

**BorrowerDto:**
```json
{
  "id": "B-10001",
  "fullName": "James R. Mitchell",
  "email": "j.mitchell@email.com",
  "phone": "217-555-0142",
  "city": "Springfield",
  "state": "IL",
  "creditScore": 745,
  "employmentStatus": "EMPLOYED",
  "loans": [ /* LoanSummaryDto[] — only populated for GET /api/borrowers/{id} */ ]
}
```

**LoanSummaryDto:**
```json
{
  "loanAccountNumber": "LN-2019-00142",
  "borrowerName": "James Mitchell",
  "productDescription": "30-Year Fixed Rate Mortgage",
  "originalAmount": 285000,
  "currentBalance": 271432.56,
  "interestRate": 4.750,
  "monthlyPayment": 1487.02,
  "status": "Active",
  "originationDate": "02/15/2019",
  "propertyAddress": "742 Elm Street, Springfield, IL 62701",
  "propertyType": "Single Family Residence"
}
```

**PaymentDto:**
```json
{
  "paymentId": "PMT-2025120001",
  "loanAccountNumber": "LN-2019-00142",
  "paymentDate": "12/15/2025",
  "totalAmount": 1487.02,
  "principalAmount": 456.78,
  "interestAmount": 1074.69,
  "escrowAmount": 355.55,
  "lateFee": 0.00,
  "type": "Regular",
  "status": "Posted"
}
```

### Additional Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/h2-console` | H2 Database web console (debugging) |

---

## 4. Business Logic Inventory

### LoanService — Core Translation Layer

The `LoanService` class (`src/main/java/.../service/LoanService.java`) is the **sole service class** and contains all business logic. It performs two key functions:

1. **Data Retrieval:** Orchestrates reads across 4 legacy repositories to assemble DTOs.
2. **Legacy Data Translation:** Converts string-typed legacy fields to proper Java types.

#### Translation Methods

| Method | Purpose | Input → Output |
|--------|---------|----------------|
| `parseLegacyAmount()` | Parse currency strings with commas | `"285,000"` → `BigDecimal(285000)` |
| `parseLegacyDecimal()` | Parse plain decimal strings | `"4.750"` → `BigDecimal(4.750)` |
| `parseLegacyInteger()` | Parse integer strings | `"745"` → `Integer(745)` |
| `expandStatusCode()` | Expand loan status abbreviation | `"ACT"` → `"Active"`, `"CLO"` → `"Closed"`, `"DFT"` → `"Default"`, `"FRB"` → `"Forbearance"` |
| `expandPropertyType()` | Expand property type abbreviation | `"SFR"` → `"Single Family Residence"`, `"CND"` → `"Condominium"`, etc. |
| `expandPaymentType()` | Expand payment type abbreviation | `"REG"` → `"Regular"`, `"EXT"` → `"Extra"`, etc. |
| `expandPaymentStatus()` | Expand payment status abbreviation | `"PST"` → `"Posted"`, `"REV"` → `"Reversed"`, etc. |

#### Key Business Rules

- **Borrower full name assembly:** First name + optional middle initial (with period) + last name.
- **Property address assembly:** Concatenates address, city, state, and ZIP with commas.
- **Product lookup by code:** Products are loaded into a map keyed by `productCode` for O(1) lookups.
- **Loan-to-borrower association:** The `getBorrowerById` endpoint eagerly loads all associated loans via `findByBorrowerId`.
- **Payment ordering:** Payments are returned in descending date order (`OrderByPaymentDateDesc`).

---

## 5. Integration Points

| Integration | Type | Details |
|-------------|------|---------|
| **H2 Database** | Embedded in-memory | JDBC URL: `jdbc:h2:mem:legacydw`, Schema auto-initialized on startup via `schema-legacy.sql` + `data-legacy.sql` |
| **H2 Console** | Web UI | Available at `/h2-console` for debugging; enabled via `spring.h2.console.enabled=true` |

There are **no external integrations**:
- No message brokers
- No external APIs consumed
- No caching layer
- No authentication/authorization provider
- No service discovery or configuration server
- No monitoring/metrics endpoints beyond default Spring Boot Actuator (not configured)

---

## 6. Build and Deployment Summary

### Build

```bash
# Build and run tests
mvn clean package

# Run application
mvn spring-boot:run
# OR
java -jar target/loan-service-1.0.0.jar
```

### Configuration

| Property | Value | Notes |
|----------|-------|-------|
| `spring.datasource.url` | `jdbc:h2:mem:legacydw` | In-memory; data lost on restart |
| `spring.jpa.hibernate.ddl-auto` | `none` | Schema managed by SQL init scripts |
| `spring.sql.init.mode` | `always` | Schema + data loaded on every startup |
| `spring.jpa.show-sql` | `true` | SQL logging enabled (dev-only) |
| Server port | `8080` (default) | Not explicitly configured |

### Deployment

- **No containerization** — no Dockerfile or docker-compose.
- **No CI/CD pipeline** configured in the repository.
- **No environment profiles** — single `application.properties` with no profile-specific overrides.
- **No externalized configuration** — all config is local.

### Known Build Issue

The `pom.xml` contains a typo: `<relativeTo/>` instead of `<relativePath/>` in the parent section. The environment blueprint includes a `sed` fix for this during setup.
