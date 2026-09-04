# UI/UX Study: Dashboard & Investigation Design for untangle

Deep-study of fintech dashboard/in-app design, synthesized into concrete tokens and component patterns for untangle's Dashboard + Investigate screens. All facts below are sourced; opinions are marked as such.

---

## 1. APP SHELL

**Ramp** — token extraction (DesignMD, [designmd.co/d/ramp](https://www.designmd.co/d/ramp)) confirms an 8px spacing grid, `#000000` near-black primary rather than a saturated brand color, and a system font stack — i.e. Ramp's shell leans on near-monochrome ink + generous whitespace rather than brand color to carry hierarchy. This matches its product reputation: left sidebar, flat icons, brand color used only for CTA/active states, not chrome.

**Linear** — [designlang extraction](https://www.designlang.app/gallery/linear-app) and [open-design.ai](https://open-design.ai/plugins/design-system-linear-app/) agree: dark app shell (`#08090a` bg / `#f7f8f8` fg), Inter Variable at 14px base (unusually small — this is *the* reason Linear feels dense-but-calm), sidebar built on an 8px-derived scale (`--space-1:4px` … `--space-6:24px`), radius scale 6/8/12px. Linear's sidebar nav rows are single-line, icon+label, no card chrome around nav items — the calm comes from *not* boxing every nav element.

**Modern Treasury** redesigned its shell around jobs-to-be-done, not object lists ([moderntreasury.com/journal/behind-the-scenes-designing-our-new-ui](https://www.moderntreasury.com/journal/behind-the-scenes-designing-our-new-ui), Feb 2024, Head of Design Duncan Graham). Concretely: they promoted "Approvals" to a flagged badge in the top-left of the sidebar (not buried in a list), added ⌘K "Quickswitch" for jump-to-object, and made **Reconciliation its own top-level nav section** instead of a sub-tab inside each account — because usage data showed the old nested placement got "very little usage." Direct lesson for untangle: Investigate/exceptions should be a first-class sidebar item, not nested under a generic "Transactions" page.

**Stripe** dashboard shell: navy (`#0a2540`) headings, `#425466` body text, `#e6ebf1` hairline borders, white/near-white (`#f6f9fc`) section backgrounds — flat, no heavy shadows in-app ([designsystems.one/design-systems/stripe-design](https://www.designsystems.one/design-systems/stripe-design)). Stripe's own docs on Stripe Apps styling confirm the Dashboard exposes its chrome tokens for app-builders to match visually ([docs.stripe.com/stripe-apps/style](https://docs.stripe.com/stripe-apps/style)).

**untangle today**: 240px sidebar, 1400px max content width, rounded-lg hairline cards — this is directionally correct against all four references (sidebar not top-nav, hairline not heavy shadow, generous max-width). **Refinement, not rebuild**: promote Investigate to a top-level sidebar slot with its own icon (Modern Treasury pattern), and consider a ⌘K command palette for jumping straight to a transaction/case id (Linear + Modern Treasury both ship this; it's cheap to build and reads as "serious software").

---

## 2. METRIC / KPI CARDS

Stripe's documented type scale ([designsystems.one](https://www.designsystems.one/design-systems/stripe-design)): display 56px/64px line-height, heading-1 34px/44px, heading-2 24px/32px, body 15px/24px, small 13px/20px. Applied to KPI cards, Stripe-style products use heading-2 (24px) for the number and small (13px) uppercase-tracked label above it — **not** a giant 40px+ number, which is what makes "wall of tiles" dashboards feel loud. Linear's h3 (20px/590 weight) plays the same numeric role in its own product screens.

Concrete pattern across Ramp/Stripe/Linear:
- Label (11–13px, medium weight, muted `#62666d`-class ink, letter-spacing ~0.02em) sits *above* the value, never beside it.
- Value at 20–24px, tabular numerals (`font-variant-numeric: tabular-nums`), semibold, full-ink color (not muted).
- 3–4 KPI cards max per row before it becomes a "wall" — Modern Treasury's redesigned dashboard deliberately cut down to four widgets (Balances, Bank Accounts, Reconciliation Stats, Payment Alerts) instead of a longer tile grid, each with a drill-down link rather than being a dead-end tile.
- Cards use hairline border, not shadow, at rest; shadow (if any) appears only on hover to signal interactivity.

**For untangle**: KPI row should read "amount recovered," "cases open," "avg time-to-close," "auto-match rate" — each with a one-line drill-down link under the number (Modern Treasury's "link to next task" pattern), so the KPI row is an entry point into Investigate, not a static summary.

---

## 3. DATA TABLES (critical path for untangle)

This is where reconciliation products live or die on "calm density." Findings:

- **Modern Treasury's rebuilt Reconcile view** uses a **side-by-side two-pane table**: bank/ledger transactions on one side, Expected Payments on the other, so a human works through unmatched rows one-by-one without navigating away ([behind-the-scenes article](https://www.moderntreasury.com/journal/behind-the-scenes-designing-our-new-ui), screenshot "Side-by-side reconciliation in Modern Treasury's new UI"). Their matching engine auto-reconciles up to 95%; the UI's entire job is to make the *remaining 5%* fast — this is the single most relevant precedent for untangle's Investigate table.
- **Right-align all numeric/amount columns**; left-align identifiers (transaction id, counterparty, description) and dates. This is universal across Stripe, Ramp, and Modern Treasury table screenshots and is non-negotiable for a finance table — misaligned decimals are the single biggest "amateur" tell.
- **Row height**: dense financial tables (Stripe Dashboard, Ramp transaction list) run 36–44px rows, not the 56px+ rows common in consumer SaaS — density is a *feature* here, since operators scan hundreds of rows.
- **Header treatment**: small-caps or 11–12px uppercase, muted ink, sits on a barely-tinted background (not white, not heavy grey) so it reads as "frame" not "content." Sticky on scroll.
- **Hairline row separators, not zebra striping** — zebra striping reads as spreadsheet/legacy; hairline `1px` borders in a low-contrast grey (Stripe's `#e6ebf1`) is what modern fintech tables use, reserving color entirely for status/semantic cells.
- **Totals rows**: pinned to the bottom (or top) with a stronger 1.5–2px top border and semibold weight — never just another row, so the eye can find "does this reconcile" instantly.
- **Empty states**: Stripe and Ramp both treat "0 unmatched transactions" as a positive illustrated state (checkmark + short copy), not a bare "No data" — critical for a recon product since an empty exceptions queue is the *product goal*, and should feel like a reward.
- **Pagination**: cursor-based "Load more" / infinite scroll for transaction lists (Ramp, Stripe) rather than numbered pages — numbered pagination reads as "reporting tool," infinite scroll reads as "live operational tool."

**For untangle**: keep the current flat hairline card table, but (a) confirm tabular-nums + right-aligned amounts everywhere, (b) add a pinned totals/reconciled-vs-outstanding summary row at table bottom, (c) build the empty "all matched" state as a genuine moment (checkmark, brief line, maybe the last-cleared amount) rather than a generic empty box.

---

## 4. EVIDENCE / DETAIL PANELS (Investigate screen)

- **Modern Treasury Reconciliation Rules UI** renders rule logic in **human language by default**, with JSON available behind a toggle — direct customer-feedback-driven decision documented in the article ("more likely that a finance persona would be creating a rule and prefer human language over code"). Directly applicable to untangle's evidence panel: default to a plain-English "why this matched / why this is flagged" narrative, with a "view raw" toggle for JSON/rule trace underneath.
- **Stripe Radar** organizes review around a risk *evidence* list per charge (device, velocity, network, past disputes) rather than a single score — Stripe's own marketing states Radar's fraud signal is probabilistic ("92% likelihood a charge is from a card Stripe has seen before," [stripe.com/radar](https://stripe.com/radar)) and the review UI is built to let a human see the contributing signals, not just trust one number. Lesson: untangle's evidence drawer should list each signal that contributed to a verdict (amount match, date match, counterparty match, rule fired) as discrete rows with individual pass/fail marks, not collapse to one score.
- **Progressive disclosure**: the pattern across Modern Treasury and Stripe Apps docs is a right-side drawer over the table (not a full-page navigation away), so the operator's place in the queue is preserved — closing the drawer returns to the same scroll position. This is the standard "don't lose my place" pattern reconciliation queues need.
- **"What was ruled out"**: none of the studied products expose this well publicly (it's a genuine differentiation opportunity for untangle, not a "borrow"). Recommend a collapsed "other candidates considered" section in the evidence drawer showing near-miss matches and why each was rejected (amount off by X, date outside window) — this is the kind of transparency that separates a trustworthy reconciliation agent from a black box, and it's explicitly part of untangle's "evidence courtroom" positioning.

---

## 5. STATUS / VERIFICATION UI

Semantic color must be reserved and never decorative — confirmed across every source. Stripe's documented palette assigns exactly one green (`#24b47e`/`#15be53` depending on source) to success/verified and one red (`#cd3d64`) to error, with everything else neutral ([designsystems.one](https://www.designsystems.one/design-systems/stripe-design), [open-design.ai](https://open-design.ai/plugins/design-system-stripe/)). Ramp's near-monochrome palette (`#000000` primary) makes status color pop *because* it's rare everywhere else in the UI — the fewer places color appears outside status badges, the more legible status badges become.

Multi-state badge pattern (not binary check/no-check): financial review UIs (Stripe Radar reviews, Modern Treasury reconciliation) use at minimum: matched/verified (green), needs review/pending (amber/yellow), failed/rejected (red), and a neutral "not yet processed" (grey) — four states minimum, never a single checkmark toggle, because "not yet checked" and "checked and failed" must never look the same.

**untangle already has this right**: green=verified / amber=needs-evidence / red=failed is the correct three-plus-neutral model. Recommendation: add the explicit fourth neutral/grey "not yet run" state distinct from amber, since amber should mean "a human looked and evidence is incomplete," not "the system hasn't gotten to this yet" — conflating those two is the most common status-UI mistake in review queues.

---

## 6. TOKENS: DOCUMENTED SOURCES vs. WHAT'S TRANSFERABLE

| Product | Base font size | Spacing base | Radius scale | Notes / source |
|---|---|---|---|---|
| Stripe | body 15px/24px | 4px | 4 / 8 / 16 / pill | [designsystems.one](https://www.designsystems.one/design-systems/stripe-design) |
| Linear | body **14px**/21px | 4px (`--space-1..6`: 4/8/12/16/20/24) | 4 / 7 / 12 / 16 / 20 | [designlang.app](https://www.designlang.app/gallery/linear-app), [open-design.ai](https://open-design.ai/plugins/design-system-linear-app/) |
| Ramp | — (system stack) | 8px | — | [designmd.co/d/ramp](https://www.designmd.co/d/ramp) |
| Stripe motion | 150ms `cubic-bezier(.215,.61,.355,1)` | — | — | [designsystems.one](https://www.designsystems.one/design-systems/stripe-design) |
| Linear motion | 100ms / 160ms / 400ms | — | — | [designlang.app](https://www.designlang.app/gallery/linear-app) |

**Transferable to untangle**: 4px spacing base (Stripe + Linear agree), radius in the 6–8px "medium" range for cards/buttons (Linear `md:7-8px`, Stripe `medium:8px` both land here — matches untangle's existing `rounded-lg`), a body text size of 14–15px for dense tables (Linear's 14px is worth adopting for table rows specifically, even if marketing/prose stays at 16px), and fast 100–200ms ease-out motion for hover/expand states (both Stripe and Linear keep interaction motion under 200ms — nothing in a finance tool should feel slow to respond).

**Not transferable**: Linear's near-black dashboard chrome (`#08090a`) — wrong for untangle's "calm ink-on-paper" brief, which wants a light, paper-like ground, not a dark IDE-like shell. Stripe's blurple/cyan gradient brand system — untangle's flat two-tone (`un`=`#0b1c30`, `tangle`=`#2b5edb`) should stay flat, no gradients, to preserve the "evidence courtroom," not "consumer fintech marketing" tone.

### Recommended token block (Tailwind-ready, CSP-safe — no external fonts/CDNs)

```js
// tailwind.config.js — untangle design tokens
// Fonts assumed self-hosted as woff2: Hanken Grotesk (display), Inter (body), JetBrains Mono (data)
module.exports = {
  theme: {
    extend: {
      colors: {
        ink: {
          900: '#0b1c30', // brand "un", primary heading ink
          700: '#1f2f42',
          500: '#425466', // Stripe-derived body ink
          300: '#8a93a3',
          100: '#e6ebf1', // hairline borders (Stripe-derived)
          50:  '#f7f8fa', // paper ground
        },
        brand: {
          DEFAULT: '#2b5edb', // "tangle"
          hover:   '#1e4bc0',
        },
        status: {
          verified:      '#1a9d5c', // green
          'verified-bg': '#e7f6ee',
          pending:       '#b7791f', // amber — "needs evidence"
          'pending-bg':  '#fdf3e0',
          failed:        '#c23b3b', // red
          'failed-bg':   '#fbe9e9',
          neutral:       '#6b7280', // grey — "not yet run"
          'neutral-bg':  '#f1f2f4',
        },
      },
      fontFamily: {
        display: ['"Hanken Grotesk"', 'sans-serif'],
        body:    ['Inter', 'sans-serif'],
        mono:    ['"JetBrains Mono"', 'monospace'],
      },
      fontSize: {
        // role: [size, { lineHeight, letterSpacing, fontWeight }]
        'kpi-label': ['12px', { lineHeight: '16px', letterSpacing: '0.03em', fontWeight: '600' }],
        'kpi-value': ['24px', { lineHeight: '30px', fontWeight: '600' }],
        'table-header': ['11px', { lineHeight: '14px', letterSpacing: '0.04em', fontWeight: '600' }],
        'table-cell': ['13.5px', { lineHeight: '20px', fontWeight: '400' }],
        body: ['15px', { lineHeight: '24px' }],
        small: ['13px', { lineHeight: '20px' }],
      },
      spacing: {
        // 4px base scale, Stripe/Linear-aligned
        1: '4px', 2: '8px', 3: '12px', 4: '16px', 5: '24px', 6: '32px', 8: '48px', 10: '64px',
      },
      borderRadius: {
        sm: '4px', DEFAULT: '6px', md: '8px', lg: '12px', pill: '9999px',
      },
      boxShadow: {
        // flat by default; shadow only on hover/elevation, not at rest
        card: '0 1px 2px rgba(11,28,48,0.04)',
        hover: '0 4px 12px rgba(11,28,48,0.08)',
        popover: '0 8px 24px rgba(11,28,48,0.12)',
      },
      transitionDuration: {
        fast: '120ms', DEFAULT: '160ms', slow: '240ms',
      },
      transitionTimingFunction: {
        DEFAULT: 'cubic-bezier(0.215, 0.61, 0.355, 1)', // Stripe-derived ease-out
      },
    },
  },
};
```

---

## FOR UNTANGLE: 7 specific moves

1. **Borrow from Modern Treasury** — promote "Investigate" to its own top-level sidebar item (not nested), and add a two-pane side-by-side layout for a case: candidate transaction on the left, matching ledger/bank record on the right, so evidence review happens without leaving the row. ([moderntreasury.com/journal/behind-the-scenes-designing-our-new-ui](https://www.moderntreasury.com/journal/behind-the-scenes-designing-our-new-ui))
2. **Borrow from Modern Treasury** — default the evidence/rule explanation to plain English ("matched because amount and date align, off by ₹0.40 rounding") with a "view raw trace" toggle underneath for JSON — don't lead with code.
3. **Borrow from Stripe Radar** — replace any single confidence score with a discrete signal checklist (amount match ✓, date match ✓, counterparty fuzzy-match ⚠, duplicate-check ✓) so operators see *why*, matching untangle's own "evidence courtroom" positioning. ([stripe.com/radar](https://stripe.com/radar))
4. **Borrow from Ramp** — keep brand/status color rare. Audit current screens for any non-status, non-CTA use of `#2b5edb` or the status colors and desaturate to ink greys; color should mean something every time it appears. ([designmd.co/d/ramp](https://www.designmd.co/d/ramp))
5. **Borrow from Linear** — adopt 14px body / 13.5px table-cell as the density baseline for the Investigate table specifically (keep 15–16px for prose/empty-states); this alone is most of what makes Linear read as "serious software" rather than a generic admin panel. ([designlang.app](https://www.designlang.app/gallery/linear-app))
6. **Borrow from Stripe** — treat the fully-reconciled / zero-exceptions state as a designed moment (checkmark illustration + one-line summary of what cleared), not a bare empty table — this is the product's win condition and should feel like one.
7. **New for untangle (not borrowed)** — build the "what was ruled out" panel: a collapsed list of near-miss candidates the matcher considered and rejected, with the specific reason (amount delta, date outside window, counterparty mismatch) for each. No competitor studied exposes this well; it is untangle's clearest differentiation from a black-box auto-matcher and should be a first-class section of the evidence drawer, always present even when empty ("no other candidates were close").
8. **Status model fix** — add the explicit fourth neutral/grey "not yet run" badge distinct from amber "needs evidence," so an unprocessed case can never be visually confused with a reviewed-but-incomplete one.

---

### Sources consulted
- Ramp tokens: https://www.designmd.co/d/ramp
- Linear tokens: https://www.designlang.app/gallery/linear-app , https://open-design.ai/plugins/design-system-linear-app/
- Stripe tokens: https://www.designsystems.one/design-systems/stripe-design , https://open-design.ai/plugins/design-system-stripe/ , https://docs.stripe.com/stripe-apps/style
- Modern Treasury UI redesign (primary, dated Feb 2024, by Head of Design): https://www.moderntreasury.com/journal/behind-the-scenes-designing-our-new-ui
- Modern Treasury Ledgers/Reconciliation product page: https://www.moderntreasury.com/products/ledgers
- Stripe Radar: https://stripe.com/radar , https://docs.stripe.com/radar/analytics
