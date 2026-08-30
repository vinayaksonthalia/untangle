# Bank input formats and OOD coverage

Untangle's canonical bank input has `value_date,narration,credit,debit` columns.
The loader also accepts a CSV header after metadata rows and normalizes common
Indian-export labels (`Date`/`Value Dt`, `Particulars`, `Deposit Amt.`,
`Withdrawal Amt.`, and reference aliases). Dates may be ISO or common
day-first forms (`DD/MM/YYYY`, `DD-MM-YYYY`, `DD/MM/YY`, `DD.MM.YYYY`). Amounts
are parsed with `Decimal`, including Indian comma grouping and trailing `CR`/`DR`.

`fixtures/bank_statement_ood.csv` is an independently hand-authored,
synthetic-format/OOD fixture. It is not a real customer or bank statement and
does not establish compatibility with HDFC or any other bank. The fixture is
used to verify metadata/header normalization, day-first dates, accounting
markers, and safe handling of unfamiliar narration vocabulary. Real bank
format compatibility requires a sanitized export and a provider-specific
regression suite.
