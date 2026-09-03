# untangle — UI Completion Checklist (finish today; video tomorrow)

Living tracker so nothing slips. Status: ✅ done · 🔨 in progress · ❌ not started · ⏸ blocked-on-input.

## Design system (locked)
- ✅ One system: audit-engine sidebar (`untangle` · "Audit Engine v1.0"), brand blue `#2b5edb`, flat hairline cards.
- ✅ Dropped the `/overview` Google-blue console variant (removed).
- ✅ Screens on it: Landing · Dashboard (Settlement close) · Investigate · Upload · Verify.

## Must finish today
- 🔨 **Two paths (demo vs your-run).** Upload flows through Dashboard → Investigate → Verify with the user's OWN data via an ephemeral in-memory session (no DB; discarded on TTL). Clear `DEMO DATA` vs `YOUR RUN` badge. Landing split into two doors: "See the demo" / "Reconcile your files".
- ❌ **Certificate document.** Downloadable, printable close certificate (→ PDF via browser print) rendered from the real cert data, PLUS keep the verifiable JSON. Verify already accepts a `.json` file.
- ❌ **Verify shows your run's certificate** (download + one-click verify) when a run is active.
- ❌ **`SAFETY.md` + README done/pending checklist** (read-only, no money movement, abstain-not-guess, proof-backed, independently verifiable).
- ❌ **Single ₹-at-risk / ₹-recoverable headline** on landing + dashboard (honest "up to / if confirmed").
- ❌ **Empty / loading / error states** first-class (skeletons; honest "all clear"; error-with-next-action).
- ❌ **Responsive** (sidebar → top bar; tables → key-value at <768px).
- ⏸ **Milan's evidence data** (competitor repo; possibly a real Razorpay dataset) — WAITING on the user to share it; add the evidence piece once received. Do NOT fabricate.

## Then
- ❌ Final consistency + full test pass + one PR + one Qodo review (per fast-workflow).
- ❌ Deploy public URL (Render) — user's task, after the app is final.
