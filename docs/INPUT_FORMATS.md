# Bank input formats and adapter fixture coverage

Untangle's canonical bank input has `value_date,narration,credit,debit` columns.
The loader also accepts a CSV header after metadata rows and normalizes common
Indian-export labels (`Date`/`Value Dt`, `Particulars`, `Deposit Amt.`,
`Withdrawal Amt.`, and reference aliases). Dates may be ISO or common
day-first forms (`DD/MM/YYYY`, `DD-MM-YYYY`, `DD/MM/YY`, `DD.MM.YYYY`). Amounts
are parsed with `Decimal`, including Indian comma grouping and trailing `CR`/`DR`.

`fixtures/bank_statement_ood.csv` is an independently hand-authored,
synthetic-format parser fixture. It is not a real customer or bank statement,
does not establish compatibility with HDFC or any other bank, and is not a
complete reconciliation/OOD evaluation. It verifies metadata/header
normalization, day-first dates, accounting markers in separate credit/debit
columns, and parsing of unfamiliar narration vocabulary. A combined Amount
column with an embedded direction is not supported. Real bank compatibility
requires a sanitized export and a provider-specific regression suite.
See [BANK_FORMAT_EVIDENCE.md](BANK_FORMAT_EVIDENCE.md) for the complete bank-format support matrix.
