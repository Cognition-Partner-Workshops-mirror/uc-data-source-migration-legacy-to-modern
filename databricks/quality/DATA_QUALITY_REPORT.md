# Data Quality Report

**Run timestamp:** *(generated at runtime)*

**Total checks:** 0  
**Passed:** 0  
**Failed:** 0  

---

> This file is a placeholder. Run `data_quality_checks.py` after ingestion to populate
> this report with actual pass/fail results. The script will overwrite this file with
> a fully formatted quality report covering:
>
> - **Row Count Reconciliation** — source vs. target for all four tables
> - **Null Checks** — required fields verified as non-null
> - **Referential Integrity** — FK relationships between loans, borrowers, products, payments
> - **Business Rules** — balance > 0 for active loans, valid date ordering, credit score ranges
> - **Status Code Expansion** — no legacy abbreviations remain in modern tables
> - **Uniqueness** — key columns (external_id, code, account_number) are unique
>
> ### How to Run
>
> ```bash
> spark-submit databricks/quality/data_quality_checks.py \
>     --borrowers-source  /mnt/landing/cdw_borr_mstr/ \
>     --products-source   /mnt/landing/cdw_ln_prod/ \
>     --accounts-source   /mnt/landing/cdw_ln_acct/ \
>     --payments-source   /mnt/landing/cdw_pmt_hist/ \
>     --output            databricks/quality/DATA_QUALITY_REPORT.md
> ```

---

**Overall result: NOT YET RUN**
