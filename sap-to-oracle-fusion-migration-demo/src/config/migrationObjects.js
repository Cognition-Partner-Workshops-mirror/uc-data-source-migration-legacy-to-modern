// Central configuration for every SAP object migrated to Oracle Fusion.
//
// Each object declares:
//   - identity (id, label, SAP source table, Oracle Fusion target + FBDI template)
//   - a SAP-field -> Oracle-Fusion-field mapping (with a transform + required flag)
//   - a small set of sample source rows (keyed by SAP field name)
//
// The sample rows are the single source of truth: they are used both to generate
// the downloadable CSVs under public/sample-data/ (see scripts/generate-sample-data.js)
// and by the in-app "Load Sample Data" action, so the UI always reflects real data.
//
// A few rows intentionally contain bad values (missing required fields / non-numeric
// amounts) so the Validation step surfaces realistic data-quality errors.

export const MIGRATION_OBJECTS = [
  {
    id: 'customers',
    label: 'Customers / Business Partners',
    sapTable: 'KNA1 (Customer Master)',
    oracleTarget: 'Oracle Fusion Trading Community — Party (HZ_PARTIES)',
    fbdiTemplate: 'TradingCommunityPartyImportTemplate.xlsm',
    fields: [
      { sap: 'KUNNR', sapType: 'string', oracle: 'PartyNumber', transform: 'trim', required: true },
      { sap: 'NAME1', sapType: 'string', oracle: 'PartyName', transform: 'trim', required: true },
      { sap: 'LAND1', sapType: 'string', oracle: 'Country', transform: 'upper', required: true },
      { sap: 'ORT01', sapType: 'string', oracle: 'City', transform: 'trim', required: false },
      { sap: 'PSTLZ', sapType: 'string', oracle: 'PostalCode', transform: 'trim', required: false },
      { sap: 'STRAS', sapType: 'string', oracle: 'Address1', transform: 'trim', required: false },
      { sap: 'SMTP_ADDR', sapType: 'string', oracle: 'EmailAddress', transform: 'lower', required: false },
    ],
    sample: [
      { KUNNR: '0000100001', NAME1: 'Acme Manufacturing Inc', LAND1: 'us', ORT01: 'Charlotte', PSTLZ: '28202', STRAS: '100 N Tryon St', SMTP_ADDR: 'AP@Acme.com' },
      { KUNNR: '0000100002', NAME1: 'Globex Corporation', LAND1: 'us', ORT01: 'Dallas', PSTLZ: '75201', STRAS: '500 Main St', SMTP_ADDR: 'billing@globex.com' },
      { KUNNR: '0000100003', NAME1: 'Initech LLC', LAND1: 'us', ORT01: 'Austin', PSTLZ: '73301', STRAS: '1 Innovation Way', SMTP_ADDR: 'accounts@initech.com' },
      { KUNNR: '0000100004', NAME1: 'Umbrella Health', LAND1: 'ca', ORT01: 'Toronto', PSTLZ: 'M5H 2N2', STRAS: '20 Bay St', SMTP_ADDR: 'finance@umbrella.ca' },
      { KUNNR: '0000100005', NAME1: 'Stark Industries', LAND1: 'us', ORT01: 'New York', PSTLZ: '10001', STRAS: '200 Park Ave', SMTP_ADDR: 'ap@stark.com' },
      // Bad row: missing required PartyName (NAME1)
      { KUNNR: '0000100006', NAME1: '', LAND1: 'gb', ORT01: 'London', PSTLZ: 'EC1A 1BB', STRAS: '1 Poultry', SMTP_ADDR: 'ap@wayne.co.uk' },
    ],
  },
  {
    id: 'vendors',
    label: 'Vendors / Suppliers',
    sapTable: 'LFA1 (Vendor Master)',
    oracleTarget: 'Oracle Fusion Procurement — Supplier (POZ_SUPPLIERS)',
    fbdiTemplate: 'SupplierImportTemplate.xlsm',
    fields: [
      { sap: 'LIFNR', sapType: 'string', oracle: 'SupplierNumber', transform: 'trim', required: true },
      { sap: 'NAME1', sapType: 'string', oracle: 'SupplierName', transform: 'trim', required: true },
      { sap: 'LAND1', sapType: 'string', oracle: 'Country', transform: 'upper', required: true },
      { sap: 'ORT01', sapType: 'string', oracle: 'City', transform: 'trim', required: false },
      { sap: 'STCD1', sapType: 'string', oracle: 'TaxRegistrationNumber', transform: 'trim', required: false },
      { sap: 'BANKN', sapType: 'string', oracle: 'BankAccountNumber', transform: 'trim', required: false },
      { sap: 'SMTP_ADDR', sapType: 'string', oracle: 'Email', transform: 'lower', required: false },
    ],
    sample: [
      { LIFNR: '0000500001', NAME1: 'Office Supplies Co', LAND1: 'us', ORT01: 'Chicago', STCD1: '36-1234567', BANKN: '000123456789', SMTP_ADDR: 'orders@officesupplies.com' },
      { LIFNR: '0000500002', NAME1: 'Global Logistics Ltd', LAND1: 'de', ORT01: 'Hamburg', STCD1: 'DE811234567', BANKN: '000987654321', SMTP_ADDR: 'invoices@globallog.de' },
      { LIFNR: '0000500003', NAME1: 'Nimbus Cloud Services', LAND1: 'us', ORT01: 'Seattle', STCD1: '91-7654321', BANKN: '000112233445', SMTP_ADDR: 'billing@nimbus.io' },
      { LIFNR: '0000500004', NAME1: 'Sterling Facilities', LAND1: 'gb', ORT01: 'Manchester', STCD1: 'GB123456789', BANKN: '000556677889', SMTP_ADDR: 'ap@sterling.co.uk' },
      { LIFNR: '0000500005', NAME1: 'Pacific Components', LAND1: 'jp', ORT01: 'Osaka', STCD1: 'JP7010001', BANKN: '000998877665', SMTP_ADDR: 'sales@paccomp.jp' },
    ],
  },
  {
    id: 'gl_accounts',
    label: 'GL Accounts',
    sapTable: 'SKA1 / SKB1 (G/L Account Master)',
    oracleTarget: 'Oracle Fusion GL — Chart of Accounts Value',
    fbdiTemplate: 'ChartOfAccountsValueImport.xlsm',
    fields: [
      { sap: 'SAKNR', sapType: 'string', oracle: 'AccountValue', transform: 'trim', required: true },
      { sap: 'TXT50', sapType: 'string', oracle: 'Description', transform: 'trim', required: true },
      { sap: 'KTOKS', sapType: 'string', oracle: 'AccountType', transform: 'accountType', required: false },
      { sap: 'WAERS', sapType: 'string', oracle: 'CurrencyCode', transform: 'upper', required: false },
      { sap: 'XBILK', sapType: 'string', oracle: 'FinancialCategory', transform: 'trim', required: false },
    ],
    sample: [
      { SAKNR: '0000100000', TXT50: 'Cash - Operating', KTOKS: 'ASST', WAERS: 'usd', XBILK: 'ASSET' },
      { SAKNR: '0000110000', TXT50: 'Accounts Receivable', KTOKS: 'ASST', WAERS: 'usd', XBILK: 'ASSET' },
      { SAKNR: '0000200000', TXT50: 'Accounts Payable', KTOKS: 'LIAB', WAERS: 'usd', XBILK: 'LIABILITY' },
      { SAKNR: '0000400000', TXT50: 'Product Revenue', KTOKS: 'REV', WAERS: 'usd', XBILK: 'REVENUE' },
      { SAKNR: '0000500000', TXT50: 'Salaries Expense', KTOKS: 'EXP', WAERS: 'usd', XBILK: 'EXPENSE' },
      // Bad row: missing required Description (TXT50)
      { SAKNR: '0000600000', TXT50: '', KTOKS: 'EXP', WAERS: 'usd', XBILK: 'EXPENSE' },
    ],
  },
  {
    id: 'materials',
    label: 'Materials / Items',
    sapTable: 'MARA (Material Master)',
    oracleTarget: 'Oracle Fusion PDH — Item Import (EGP_SYSTEM_ITEMS)',
    fbdiTemplate: 'ItemImportTemplate.xlsm',
    fields: [
      { sap: 'MATNR', sapType: 'string', oracle: 'ItemNumber', transform: 'trim', required: true },
      { sap: 'MAKTX', sapType: 'string', oracle: 'ItemDescription', transform: 'trim', required: true },
      { sap: 'MTART', sapType: 'string', oracle: 'ItemClass', transform: 'itemClass', required: false },
      { sap: 'MEINS', sapType: 'string', oracle: 'PrimaryUOM', transform: 'upper', required: true },
      { sap: 'MATKL', sapType: 'string', oracle: 'ItemCategory', transform: 'trim', required: false },
      { sap: 'BRGEW', sapType: 'number', oracle: 'GrossWeight', transform: 'toNumber', required: false },
      { sap: 'NTGEW', sapType: 'number', oracle: 'NetWeight', transform: 'toNumber', required: false },
    ],
    sample: [
      { MATNR: 'MAT-0001', MAKTX: 'Steel Bolt M8', MTART: 'HAWA', MEINS: 'ea', MATKL: 'FASTENERS', BRGEW: '0.05', NTGEW: '0.045' },
      { MATNR: 'MAT-0002', MAKTX: 'Aluminium Sheet 2mm', MTART: 'ROH', MEINS: 'm2', MATKL: 'METALS', BRGEW: '5.4', NTGEW: '5.4' },
      { MATNR: 'MAT-0003', MAKTX: 'Hydraulic Pump A12', MTART: 'FERT', MEINS: 'ea', MATKL: 'PUMPS', BRGEW: '12.8', NTGEW: '12.0' },
      { MATNR: 'MAT-0004', MAKTX: 'Packaging Box Large', MTART: 'VERP', MEINS: 'ea', MATKL: 'PACKAGING', BRGEW: '0.3', NTGEW: '0.3' },
      // Bad row: non-numeric GrossWeight
      { MATNR: 'MAT-0005', MAKTX: 'Lubricant Oil 5L', MTART: 'HAWA', MEINS: 'l', MATKL: 'CHEMICALS', BRGEW: 'N/A', NTGEW: '4.6' },
    ],
  },
  {
    id: 'cost_centers',
    label: 'Cost Centers',
    sapTable: 'CSKS / CSKT (Cost Center Master)',
    oracleTarget: 'Oracle Fusion GL — Cost Center Segment Value',
    fbdiTemplate: 'CostCenterValueImport.xlsm',
    fields: [
      { sap: 'KOSTL', sapType: 'string', oracle: 'CostCenterCode', transform: 'trim', required: true },
      { sap: 'KTEXT', sapType: 'string', oracle: 'CostCenterName', transform: 'trim', required: true },
      { sap: 'KOKRS', sapType: 'string', oracle: 'LedgerName', transform: 'trim', required: false },
      { sap: 'PRCTR', sapType: 'string', oracle: 'ProfitCenter', transform: 'trim', required: false },
      { sap: 'VERAK', sapType: 'string', oracle: 'Manager', transform: 'trim', required: false },
      { sap: 'DATBI', sapType: 'date', oracle: 'EndDate', transform: 'dateISO', required: false },
    ],
    sample: [
      { KOSTL: 'CC1000', KTEXT: 'Corporate Finance', KOKRS: 'BOFA', PRCTR: 'PC100', VERAK: 'J. Smith', DATBI: '20991231' },
      { KOSTL: 'CC2000', KTEXT: 'Retail Banking Ops', KOKRS: 'BOFA', PRCTR: 'PC200', VERAK: 'M. Johnson', DATBI: '20991231' },
      { KOSTL: 'CC3000', KTEXT: 'Technology', KOKRS: 'BOFA', PRCTR: 'PC300', VERAK: 'A. Lee', DATBI: '20991231' },
      { KOSTL: 'CC4000', KTEXT: 'Risk & Compliance', KOKRS: 'BOFA', PRCTR: 'PC400', VERAK: 'R. Patel', DATBI: '20991231' },
      { KOSTL: 'CC5000', KTEXT: 'Marketing', KOKRS: 'BOFA', PRCTR: 'PC500', VERAK: 'S. Chen', DATBI: '20991231' },
    ],
  },
  {
    id: 'fixed_assets',
    label: 'Fixed Assets',
    sapTable: 'ANLA (Asset Master)',
    oracleTarget: 'Oracle Fusion Assets — Mass Additions (FA_MASS_ADDITIONS)',
    fbdiTemplate: 'MassAdditionsImport.xlsm',
    fields: [
      { sap: 'ANLN1', sapType: 'string', oracle: 'AssetNumber', transform: 'trim', required: true },
      { sap: 'TXT50', sapType: 'string', oracle: 'Description', transform: 'trim', required: true },
      { sap: 'ANLKL', sapType: 'string', oracle: 'AssetCategory', transform: 'assetCategory', required: false },
      { sap: 'AKTIV', sapType: 'date', oracle: 'DatePlacedInService', transform: 'dateISO', required: true },
      { sap: 'KANSW', sapType: 'number', oracle: 'AssetCost', transform: 'toNumber', required: true },
      { sap: 'KOSTL', sapType: 'string', oracle: 'CostCenter', transform: 'trim', required: false },
      { sap: 'MENGE', sapType: 'number', oracle: 'Units', transform: 'toNumber', required: false },
    ],
    sample: [
      { ANLN1: 'AST-0001', TXT50: 'Data Center Server Rack', ANLKL: '3000', AKTIV: '20220115', KANSW: '125000.00', KOSTL: 'CC3000', MENGE: '10' },
      { ANLN1: 'AST-0002', TXT50: 'Branch Office Furniture', ANLKL: '2000', AKTIV: '20210310', KANSW: '48000.00', KOSTL: 'CC2000', MENGE: '1' },
      { ANLN1: 'AST-0003', TXT50: 'Company Vehicle Fleet', ANLKL: '4000', AKTIV: '20230601', KANSW: '210000.00', KOSTL: 'CC1000', MENGE: '5' },
      { ANLN1: 'AST-0004', TXT50: 'ATM Machines', ANLKL: '3000', AKTIV: '20200922', KANSW: '360000.00', KOSTL: 'CC2000', MENGE: '12' },
      // Bad row: non-numeric AssetCost + invalid date
      { ANLN1: 'AST-0005', TXT50: 'Office Renovation', ANLKL: '2000', AKTIV: 'PENDING', KANSW: 'TBD', KOSTL: 'CC5000', MENGE: '1' },
    ],
  },
  {
    id: 'journals',
    label: 'Journals / Balances',
    sapTable: 'BKPF / BSEG (Accounting Documents)',
    oracleTarget: 'Oracle Fusion GL — Journal Import (GL_INTERFACE)',
    fbdiTemplate: 'JournalImportTemplate.xlsm',
    fields: [
      { sap: 'BELNR', sapType: 'string', oracle: 'JournalName', transform: 'trim', required: true },
      { sap: 'BUDAT', sapType: 'date', oracle: 'AccountingDate', transform: 'dateISO', required: true },
      { sap: 'HKONT', sapType: 'string', oracle: 'AccountCombination', transform: 'trim', required: true },
      { sap: 'DMBTR', sapType: 'number', oracle: 'EnteredAmount', transform: 'toNumber', required: true },
      { sap: 'SHKZG', sapType: 'string', oracle: 'DrCrIndicator', transform: 'drcr', required: true },
      { sap: 'WAERS', sapType: 'string', oracle: 'CurrencyCode', transform: 'upper', required: true },
      { sap: 'SGTXT', sapType: 'string', oracle: 'Description', transform: 'trim', required: false },
    ],
    sample: [
      { BELNR: '4900000001', BUDAT: '20240131', HKONT: '0000100000', DMBTR: '15000.00', SHKZG: 'S', WAERS: 'usd', SGTXT: 'Cash receipt' },
      { BELNR: '4900000001', BUDAT: '20240131', HKONT: '0000400000', DMBTR: '15000.00', SHKZG: 'H', WAERS: 'usd', SGTXT: 'Product revenue' },
      { BELNR: '4900000002', BUDAT: '20240215', HKONT: '0000500000', DMBTR: '8200.50', SHKZG: 'S', WAERS: 'usd', SGTXT: 'Payroll run' },
      { BELNR: '4900000002', BUDAT: '20240215', HKONT: '0000100000', DMBTR: '8200.50', SHKZG: 'H', WAERS: 'usd', SGTXT: 'Payroll cash out' },
      // Bad row: non-numeric amount
      { BELNR: '4900000003', BUDAT: '20240301', HKONT: '0000200000', DMBTR: 'error', SHKZG: 'H', WAERS: 'usd', SGTXT: 'Vendor accrual' },
    ],
  },
]

export function getObject(id) {
  return MIGRATION_OBJECTS.find((o) => o.id === id)
}
