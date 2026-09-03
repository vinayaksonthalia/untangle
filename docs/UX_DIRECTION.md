# untangle — UX Direction Brief

*Senior design-lead critique of the console (`overview.html`) and evidence room (`investigate.html`). Design judgment only — no code.*

---

## 1. Verdict on the console direction

Yes — the dense audit-console aesthetic is the right instinct for a proof-first tool sold to Indian finance controllers, and it already reads more like an internal treasury system than a marketing site, which is exactly the trust posture you want. But right now it reads as *competent admin panel*, not *authoritative financial instrument*: the density is uniform (everything is small, bordered, and equally loud), so nothing signals what to look at first. The bones are correct; the problem is hierarchy and restraint, not concept.

---

## 2. Top 5 UX improvements (prioritized)

**1. Give the console one dominant answer, not four equal metric cards.**
Today the four cards (`Total bank credits`, `Reconciled to paise`, `Needs evidence`, `Recoverable fee GST`) are the same size and weight. A controller opening this screen has exactly one question: *did the close hold, and what's left?* Promote a single hero result — the reconciled-to-paise coverage with its denominator (`91 of 103 · residual ₹0.00`) — to ~2x scale, and demote the other three to a quiet supporting row. *Why:* the one-hero-per-screen rule (your own DESIGN.md §4) is what separates a dashboard you *read* from one you *scan*. Equal weight = no hierarchy = cognitive load on every visit.

**2. Kill the `Confidence` column in the per-line table — it contradicts your own brand.**
`overview.html` renders a numeric `Confidence` (`0.94`) column, but DESIGN.md §4 explicitly says "a confidence score is not a green-to-red truth meter; show the evidence tier and disposition instead." A decimal confidence is precisely the "guess" the product refuses to make. Replace it with **evidence tier + matched reference** (the *reason* it reconciled). *Why:* trust signals must be consistent — a probability score on a "proof, not guesses" product is a self-inflicted credibility wound the first time a controller asks "0.94 of what?"

**3. Unify the two screens into one design system — they are visibly different products right now.**
`overview.html` uses a Material-style token set (`surface-container-*`, focus ring `#005bbf`, brand `#005bbf`) and a 256px sidebar labelled "console"; `investigate.html` uses a different token vocabulary (`background`/`on-background`), a **240px** sidebar labelled "Audit Engine v1.0", brand blue `#2b5edb`, focus ring `#0f172a`, and hardcoded amber `#F59E0B`. Two blues, two focus colors, two sidebar widths, two nav labels. *Why:* inconsistency is the single fastest way to read as "assembled by a team under deadline" rather than "one deliberate product." Pick one token file, one brand blue, one sidebar. This is the cheapest premium-perception win available.

**4. Design the empty, loading, and error states as first-class — not as `—` placeholders and a red sentence.**
Both screens hydrate from `fetch()` and, on failure, collapse to a single centered red line (`Could not load run…`); before load they show em-dashes everywhere. For an audit tool, the *absence* of data is itself information (DESIGN.md §7 mandates this). Give: (a) a skeleton state that preserves layout so numbers don't pop in and look provisional, (b) the honest empty states already written in DESIGN.md §5 ("No exceptions require review. Every supported variance closed within tolerance."), and (c) an error state with a next action, not a dead end. *Why:* controllers distrust tools that flicker or vanish; calm, deliberate absence *is* the trust signal.

**5. Fix mobile/responsive collapse for the sidebar and the verdict table.**
Both shells use a `fixed` left sidebar with hard `pl-64`/`ml-60` offsets and no documented < 768px behavior; the per-line table is the core evidence surface and will horizontal-scroll off-screen. DESIGN.md §7 promises "at 375px the primary action and current status remain visible." *Why:* controllers check closes from phones between meetings, and a promised responsive contract that isn't built is worse than one you never claimed. At minimum: collapse the sidebar to a top bar, and convert the verdict table to labelled key-value rows (never silently drop the amount or tier column).

---

## 3. The single highest-impact move

**Make the "audit root / content hash / proof packets passed" strip the emotional center of the product, not a monospace afterthought in the header.**

Right now the provenance data — the audit-root SHA, the content hash, `N/N proof packets passed`, the signature status — is the *entire* reason untangle is different from every reconciliation tool, and it's rendered as 11px grey mono text tucked into a run strip and a small provenance box. Elevate it into a deliberate, quietly beautiful **"proof seal"** component: fixed-width hashes with a copy affordance, a clear `hash-bound` vs `authenticated` distinction (never flattened to "secure," per DESIGN.md §2), and the packets-passed count treated as the console's proudest number. A $1B fintech makes its hardest-won guarantee *feel* load-bearing. That one component — calm, precise, verifiable, copyable — is what turns "admin panel" into "instrument of record."

---

## 4. Anti-patterns to avoid (given the honesty constraint)

- **No trust theater.** No lock-icon walls, no "bank-grade," no faux-Merkle-tree animations, no neon "AI verified ✨" glow, no fabricated SOC2/ISO badges, no logo bar of "trusted by." Your competitors' mocks lean on these; your brand is that you *don't*.
- **Authority comes from precision, not decoration.** Look premium via: perfect decimal alignment, true tabular numerals on every amount/hash/percent, generous whitespace around the one hero number, hairline rules instead of heavy borders, and restrained motion. Modern Treasury and Polar feel expensive because they're *quiet*, not because they're shiny.
- **Don't animate money.** DESIGN.md §6 is right — no count-up-from-zero on audited totals; it makes verified values look provisional. Motion may clarify a state transition, never entertain.
- **Don't let semantic color drift.** Green = verified/reconciled only; amber = needs evidence/abstained only; never color-as-decoration. The hardcoded `#F59E0B` variance figure and the `animate-pulse` "live" dots are borderline — pulse implies a live system when this is a deterministic, read-only run. Reconsider both.
- **Never soften abstention into failure.** The "abstained / needs evidence" states must look as deliberate and dignified as the reconciled ones — same visual weight, tertiary (not red) color. Abstention is the feature.

---

## 5. North-star

**An instrument of record a controller would trust enough to sign their name under — calm, exact, and verifiable to the paise.**
