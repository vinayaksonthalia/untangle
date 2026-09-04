# Fintech Landing Page & Motion Study — for untangle

Research method: live-fetched via firecrawl_scrape (markdown + branding extraction) on 2026-09-03. All hexes, fonts, and copy below are pulled directly from the fetched DOM/CSS, cited per site. Motion/interaction descriptions are inferred from DOM structure, class names, and known patterns where animation isn't visible in static markdown — flagged as "(inferred)" where so.

---

## Stripe — stripe.com

**Hero.** Center-top headline in italic serif-leaning display type over a huge animated wave/gradient mesh background ("Financial infrastructure to grow your revenue"), CTA row (`Get started` / `Sign up with Google`) directly under subcopy, then a "bento grid" of live product mockups begins immediately below the fold — no single hero device, instead ~8 stacked interactive product cards (checkout UI in 3 locales, usage meter, agentic-commerce chat, card issuing, Connect dashboard).

**Imagery/product windows.** Checkout and dashboard mockups are rendered as literal miniature browser/app windows with real UI chrome (address-bar-less cards, rounded 12–16px corners, soft shadow, "roastery.com/checkout" as a fake URL label) sitting on a warm gradient "wave" photographic background (`wave-fallback-desktop.png`). No 3D tilt — flat, layered z-depth via shadow only.

**Motion.** Global GDP counter ticks live digits in the hero (`1.70906371%` interpolation node — a JS count-up). Multi-locale checkout carousel cycles currency/language variants in place (opacity/height crossfade, inferred ~4–6s dwell). "What's happening" carousel is a horizontally scrolling card rail. Scroll-linked reveal on bento cards (inferred from Next.js/Framer patterns typical of Stripe's site).

**Color & type.** Primary accent `#533AFD` (violet-blue), soft pink `#FFE0EF`, ink `#0D1738`, white ground. Headings in "Sohne"/SF Pro Display, body Sohne. Numbers/data in tabular mono for the GDP ticker. Big display type (48–90px) is restrained — mostly regular weight, not black.

**The one thing.** Restraint through whitespace + a single warm gradient wash tying dozens of disparate product screenshots into one visual family — every mockup, however different the product, sits on the same wave-gradient card so the page never feels like a grid of unrelated screenshots. Source: stripe.com hero and bento section.

---

## Ramp — ramp.com

**Hero.** Left-aligned bold headline "Time is money. Save both." with a single email-capture input inline (`Get started for free`), and directly above it a live ticking counter strip: "US corporate payments processed by Ramp: 0123456789..." — a slot-machine digit odometer that spins to a live number, plus a percentage counter. Below the fold, a second live counter block ("AGENTS AT WORK TODAY") lists 7 metrics (receipts processed, fields coded, agent interactions...) each with the same spinning-digit treatment.

**Imagery/product windows.** Product tiles use a "bento" of rounded cards (`platform-treasury-card`) with soft image renders of the dashboard UI — flat cards, no browser chrome, no 3D. A wireframe/dotted "stippled globe" illustration shows global spend by city (Tokyo, London, Stockholm, Mexico City) as a data-viz centerpiece for one feature module.

**Motion.** The odometer/counter is the site's signature device — every stat on the page (transactions, dollars saved, agent actions) animates as spinning digits on load/scroll into view, communicating "live system, not a static mockup." Logo carousel auto-scrolls horizontally. Testimonial cards appear to auto-rotate.

**Color & type.** Signature acid-yellow/chartreuse `#E4F222` primary, near-black `#0C0A08`/`#1A1919` secondary, pure white ground, blue link `#0066FF`. Display/body: "Lausanne" throughout (one typeface family for both). Tight 6px/4px-based spacing grid, small 6px button radius (not full-pill) — a deliberately "engineered," almost spreadsheet-adjacent geometry versus the softness of consumer fintech.

**The one thing.** The odometer motif — Ramp makes its own live operational scale into the hero graphic instead of a product screenshot. It's the clearest "borrow this" for untangle (see below). Source: ramp.com hero + "Agents at work today" section.

---

## Polar — polar.sh

**Hero.** Dark canvas (`#090909`), centered headline "Meet Polar — the billing stack for the intelligence era," single `Get Started` CTA. No hero image at all — instead 4 small feature-preview tiles (Usage billing / Subscriptions / Seats / Credits) directly under the CTA, each with a one-line description, functioning as the "device."

**Imagery/product windows.** Below the fold, real product UI is shown as small isolated widget snippets, not full browser windows — a meter readout ("gpt-4o · 1.2M tokens"), a plan-price line, a payout amount — floating on the dark background with no card border, just typographic hierarchy and subtle color-coded numbers (green `+86%`, presumably red for `-19%`). This is a "data fragment" style rather than a full screenshot.

**Motion.** (inferred) Numbers likely count up on scroll given the meter/margin framing; testimonial cards linked to X/Twitter posts suggest a horizontal-scroll wall-of-love.

**Color & type.** Near-black `#090909` background, white text/CTAs, pill-shaped buttons (`33554400px` radius = effectively `9999px`). Headings in "PP Neue Montreal," body Inter/InterDisplay, mono "GeistMono" for numeric/data readouts — a clear 3-tier type system (display / body / data-mono) that's directly relevant to untangle's own Hanken Grotesk / Inter / JetBrains Mono split.

**The one thing.** Confidence through absence — no hero illustration, no dashboard screenshot, just typography, dark ground, and small live-looking numeric fragments. It reads as "serious infrastructure," not "consumer app." Source: polar.sh hero section.

---

## Checkout.com — checkout.com

**Hero.** Dark theme (`#000000` background, `#186AFF` blue primary, acid `#BBFF00` as a link/accent flash color) — "Payment services to power your performance." Large 90px display headline set in a monospace-leaning custom face ("Checkout Apercu SemiMono") for numerals/headlines specifically, Inter for body — an unusual choice that gives the brand a "terminal/ledger" feel distinct from the roundness of most fintech.

**Imagery/product windows.** (not fully captured in this pass — branding-only fetch) but color system (`#186AFF` blue CTA on black, `#272932` secondary dark-gray buttons, sharp `0px`/`8px` mixed radii) signals a high-contrast, low-ornament dashboard-first aesthetic consistent with its enterprise-payments positioning.

**The one thing.** Monospace-in-headlines on a payments company is the standout move — it borrows credibility language from developer tools/terminals rather than consumer banking. Source: checkout.com branding extraction.

---

## Dodo Payments — dodopayments.com

**Hero.** Light background (`#FFFBED` warm cream), acid-green/yellow-green `#C6FE1E` primary CTA — "Billing & Payments Platform for AI-First Companies." Astro-built static site, so hero is likely a fast, minimal-JS composition — a light, high-energy palette that stands out from the navy/black seriousness of Checkout.com or Modern Treasury; reads closer to Polar/Creem's indie-hacker energy but daytime instead of dark-mode.

**Color & type.** `#C6FE1E` (chartreuse) primary button, `#FFFBED` cream background, `#00160D` near-black text. Multi-language `og:locale:alternate` list (15 locales) signals a genuinely global self-serve audience. Buttons: 8px radius, soft bordered.

**The one thing.** Loud chartreuse-on-cream is doing the same "AI-era, not legacy-bank" signaling as Ramp's yellow and Polar's black — a color-coded generational marker across nearly every 2025/26-era billing startup. Source: dodopayments.com branding extraction.

---

## Wise — wise.com

**Hero.** "The fast way to send money abroad" — headline over a **fully live interactive currency-conversion calculator** as the hero device: country-flag selector, live exchange rate ("1 USD = 0.8622 EUR, guaranteed for 16h"), amount input, fee breakdown, single `Send money` CTA. This is the most functionally interactive hero of the set — not a screenshot of the product, it *is* the product, embedded directly in the marketing page.

**Imagery/product windows.** Below the fold, a comparison table (Wise vs. Wells Fargo vs. Chase vs. PayPal) renders each competitor's logo + computed fee as a horizontal bar/row list — a "receipts" style comparison rather than screenshots. Feature cards show isolated UI fragments (a debit card render, an interest-rate badge) floating on white, not full app windows.

**Motion.** (inferred) The live-rate widget almost certainly recalculates on input with a debounced fetch + number transition; flag icons swap on country select.

**Color & type.** Signature bright green `#9FE870` on deep forest `#163300`, white ground. Pill-shaped buttons (`9999px` radius). Custom "Wise Sans" for headings, Inter for body. Large friendly numerals for exchange rates.

**The one thing.** The hero *is* a working calculator, not a picture of one — maximum credibility for a company selling "transparent, no-surprise pricing." Source: wise.com hero markdown.

---

## Creem — creem.io

**Hero.** Dark theme, mascot-illustration-driven ("Sell software globally") with a small eyes/mascot SVG inline in the headline itself. CTA `Get started` + `Copy prompt for AI` (a second CTA aimed explicitly at AI-agent users pasting the page into an LLM — notable pattern). Below: a live-chat / support widget mockup as the first "proof" device (chat bubble + Discord online-count badge).

**Imagery/product windows.** Extremely dense feature-tile grid: each tile is a small flat card showing one UI fragment (revenue-split payout bars, an affiliate leaderboard with medal icons, a phone-shaped app mockup with notch, a real syntax-highlighted code block for the SDK). Cards use a thick black border + hard drop shadow (`3px 3px 0px black`) — a neo-brutalist/sticker aesthetic, not soft shadows or glassmorphism.

**Motion.** (inferred, heavy) Live "webhook feed" ticker shown as scrolling timestamped POST events (`14:32:01 POST checkout.completed …`) — a fake-live-log pattern borrowed from devtools UIs (also seen at Stripe). Chat-bubble typing animation implied by "Ready to help / GPT-4" framing.

**Color & type.** Warm coral `#FFBE98` primary on off-white `#F5F2F0`, mint-green `#4ECB71` secondary. Distinctive display face "Gasoek One" (a chunky geometric display font) for headlines, GeistSans body. Hard-edged 12px-radius buttons with a solid black offset shadow — very "indie hacker sticker sheet" versus the corporate softness of Stripe/Checkout.com.

**The one thing.** A cartoon mascot + neo-brutalist card borders makes billing infrastructure feel approachable and fun rather than intimidating — a deliberate rejection of "enterprise fintech" seriousness. Source: creem.io hero + feature-tile markdown.

---

## CRED — cred.club

**Hero.** Full-bleed cinematic hero: "A REFLECTION OF CLARITY" lowercase-styled headline over what is described as a rotating/expandable visual ("click to expand") — likely a 3D card or mirror-reflection hero animation (site is Next.js with heavy custom imagery, poster-frame video assets named `phone-ticker-desktop-poster`). Single QR-code download CTA is persistent throughout the page (repeated 4+ times) rather than a text-input signup — CRED sells exclusivity via a QR/app-only funnel, not web signup.

**Imagery/product windows.** No literal browser-chrome screenshots — instead moody photographic/cinematic posters (`ccbp-fold-poster.jpg`, `rewards-desktop-poster.jpg`) suggesting full-bleed video loops behind copy, styled like a luxury brand microsite rather than a SaaS product page.

**Color & type.** Near-black `#000000` ground, electric blue `#0000EE` accent (very saturated, almost a "link blue" from early web reused as a brand signature), all-lowercase copy throughout ("not everyone makes it in") for a whispered, exclusive tone. Fonts: Gilroy/Overpass.

**The one thing.** All-lowercase copy + velvet-rope exclusivity language ("not everyone gets it," "crafted for the creditworthy") does more brand work than any UI screenshot — CRED sells status, not features. Source: cred.club hero markdown.

---

## Lago — getlago.com

**Hero.** "The AI-native billing platform" — headline over a **fanned/exploded 5-panel dashboard collage**: five screenshots (`home-hero-img-far-left/mid-left/center/mid-right/far-right`) arranged in a spread/staircase layout, each a real product screenshot at a slightly different depth/offset — the closest thing to a "product window" hero in this set that uses actual multiple screenshots rather than one.

**Imagery/product windows.** Real dashboard screenshots (not illustrated mockups) used directly, unframed (no browser chrome visible in file names, likely cropped UI panels with soft shadow only).

**Color & type.** Blue `#006CFA` primary, near-black `#131923` secondary, custom "gtAmerica" for both display and body — a single-family type system. Logo wall of recognizable names (Mistral AI, PayPal, Groq, Laravel) rendered as monochrome SVG marks in a horizontal marquee, each paired with a one-line customer quote beneath — this "logo → quote → link" triplet pattern repeats for every 3-logo group, doing double duty as both social proof and internal navigation.

**The one thing.** Real product screenshots fanned in a shallow 3D stagger (not tilted, just offset/scaled) — proof over promise, appropriate for an open-source dev tool audience that distrusts marketing gloss. Source: getlago.com hero + customer-logo section.

---

## Modern Treasury — moderntreasury.com

**Hero.** "Build Products That Move Money" — plain left-aligned headline, single `Talk to us` CTA (no self-serve signup — enterprise sales motion), directly followed by a 33-logo customer marquee (Anchorage, BambooHR, Gusto, Robinhood, Procore...) — the trust wall comes before any product visual at all.

**Imagery/product windows.** Two-panel "Problem → Solution" narrative: a screenshot of a "Business Account Onboarding Status" panel paired with a screenshot of a code editor showing payment-type constants — pairing a UI screenshot with a code screenshot side by side is the site's signature move, addressing both the "ops person" and "engineer" buyer personas in one scroll unit.

**Color & type.** Muted plum `#543B4E` primary, sage-mint `#BAE0CF` accent/button color, deep forest `#0C221D` secondary, white ground. Custom type family "mt-neue-display/text" + "mt-sans" — a bespoke, quiet, almost editorial palette (no bright saturated color anywhere) that reads as "bank-grade" restraint versus the neon of consumer fintech.

**The one thing.** Muted, desaturated plum/sage palette signals institutional trust — Modern Treasury is the most visually "boring" (in the best sense) of the set, appropriate for infrastructure that banks themselves rely on. Source: moderntreasury.com hero + color tokens.

---

## PayU — payu.in

**Hero.** "Grow more. Do more. Be more." — three-line stacked bold headline, dual CTA (`Get Started` / `Contact Us`), immediately followed by a "What's New" content carousel (blog-style cards) rather than a product screenshot — PayU leads with content marketing, not a hero device. Logo wall (Netflix, Airbnb, Myntra, Ola) appears directly under the fold.

**Color & type.** Teal-green `#00AB88` primary on a light warm-gray `#EEF1EF` background, Roboto Slab for headings (a slab-serif — unusual for fintech, gives a slightly more traditional/institutional feel than the geometric sans used everywhere else in this set), Open Sans body.

**The one thing.** Slab-serif headings on an Indian payments gateway is a deliberate departure from the geometric-sans consensus — reads as approachable/local rather than Silicon-Valley-generic. Source: payu.in branding extraction.

---

## Square — squareup.com

**Hero.** Large illustrated/photographic collage hero (10 stacked frame illustrations of small-business scenes — florist, pizza shop, mechanic, bar) rather than app screenshots — Square's homepage leads with an illustrated "meet real small businesses" mosaic before showing any hardware or software. Hardware section follows immediately with literal product photography (Register, Handheld, Terminal, Stand) each with pricing directly under the image.

**Color & type.** Blue `#006AFF` primary, green `#0BB634` accent/link, "Cash Sans"/"Square Sans" custom type family shared with sibling Cash App — a distinctly friendly, rounded, illustration-forward brand versus the flat data-dashboard look of B2B payment infra sites.

**The one thing.** Illustration-led storytelling (people and shops, not screens) because Square sells hardware + in-person commerce, not a dashboard — the hero has to sell the physical retail moment. Source: squareup.com hero markdown.

---

## Revolut — revolut.com

**Hero.** "Banking & Beyond" centered headline, single `Download the app` CTA, badge row of press/rating logos (Trustpilot 4.7, "World's Best Digital Bank") directly below — app-store-first funnel, no dashboard screenshot in the primary hero; card/app renders appear further down for feature sections (savings, cards, AIR AI assistant).

**Color & type.** Monochrome black-and-white (`#000000`/`#1F1F1F`) primary palette with pill buttons (`9999px` radius) — Revolut deliberately avoids color in its CTA system, using stark black/white contrast instead of a brand accent hue. Aeonik Pro for display, Inter body. Huge type scale (h1 136px, h2 80px) — the largest display sizes of any site studied.

**The one thing.** Monochrome minimalism at very large type scale — Revolut trusts white space and scale rather than color to feel premium. Source: revolut.com hero + typography tokens.

---

# FOR UNTANGLE

**Constraint recap:** self-hosted, hardened CSP (`default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'`) — no CDNs, no Google Fonts, no external images/scripts. Every pattern below is scoped to what's CSP-safe with that policy: inline `<style>`/`<script>` tags are fine (`'unsafe-inline'` covers both), external `<link>`/`<script src>` to any third-party origin is not.

## The hero device: a live "evidence courtroom" replay, not a screenshot

Borrow Wise's principle — the hero *is* the product, not a picture of it. Build an inline SVG + vanilla-JS mini-replay: a transaction row enters, a matching ledger row enters from the other side, a connecting line draws between them (SVG `<path>` with `stroke-dasharray` animated via CSS to look "drawn"), then the row flips from amber (`needs-evidence`) to green (`verified`) with a check icon. Loop it every ~6s with 2–3 transaction pairs. This demonstrates untangle's actual mechanism (matching + evidence + verification) the way Ramp's odometer demonstrates "live scale" and Wise's calculator demonstrates "real rates" — it's honest, not decorative.

## Product-window rendering: flat cards with real screenshots, staggered like Lago — not tilted 3D

Lago's shallow-offset 5-panel stagger is the right model: use real app screenshots (PNG or self-hosted, not CDN), laid out with CSS `position:absolute` + small `translate`/`scale` offsets and soft `box-shadow` (no browser chrome, no fake address bar — untangle isn't a consumer web app metaphor). Avoid Checkout.com/Creem's heavy neo-brutalist borders (wrong register for a finance-trust product) and avoid 3D perspective tilt (adds complexity, no CSP issue but pure cost/benefit — Lago and Stripe both skip it too). CSP note: this is 100% safe — self-hosted PNG/WebP + inline CSS.

## Motion plan (all pure CSS or inline `<script>`, zero external libs)

1. **Count-ups for verified-amount stats** (à la Ramp's odometer, Stripe's GDP ticker) — implement with `requestAnimationFrame` in an inline `<script>` easing a number from 0 to target over ~1.2s, triggered by `IntersectionObserver` on scroll-into-view. No library needed; this is exactly the kind of thing GSAP is used for elsewhere but a 15-line vanilla implementation is CSP-safe and dependency-free.
2. **Scroll reveals**: `IntersectionObserver` toggling a `.is-visible` class that triggers a CSS `transition` (`opacity`/`translateY`), same mechanism Stripe/Lago/Ramp all use under the hood regardless of framework.
3. **The SVG "match line" draw**: CSS `@keyframes` animating `stroke-dashoffset` — the exact technique for Polar-style "quiet confidence" data visualization, fully inline-SVG and CSP-safe.
4. **Status-color transition**: amber→green background/border color CSS `transition` on the evidence card, mirroring untangle's own semantic palette (`--verified: green; --needs-evidence: amber; --failed: red`) — this *is* the brand story, so make it the most polished single micro-interaction on the page.
5. **Hover on evidence cards**: subtle `box-shadow` lift + `translateY(-2px)` on hover, à la Lago/Stripe bento cards — cheap, standard, and communicates "clickable/interactive," not "static image."

## Color & type — keep the existing brand, borrow restraint from Modern Treasury / Polar

Untangle's ink `#0b1c30` / blue `#2b5edb` / green-amber-red semantic system is already closer to Modern Treasury's muted-institutional palette than to Ramp/Dodo's neon-chartreuse energy — lean into that; a finance-controller/reconciliation tool should read as trustworthy infrastructure (Modern Treasury, Lago) rather than an indie SaaS toy (Creem, Dodo). Use Hanken Grotesk at large confident sizes for the hero headline (Revolut's lesson: scale + restraint over color for premium feel), Inter for body, and reserve JetBrains Mono specifically for the evidence/ledger numbers in the hero device — exactly the "display / body / data-mono" three-tier system Polar uses (PP Neue Montreal / Inter / GeistMono).

## Five specific "borrow this" moves

1. **From Ramp**: a live odometer-style counter for "discrepancies resolved" or "₹ matched" in the hero or right below it — spinning digits communicate an operating system, not a static dashboard.
2. **From Wise**: make at least one hero element genuinely interactive (e.g., drag a transaction onto a ledger row to see the match-and-verify animation play) rather than autoplay-only — interactivity earns more trust than a looping video ever does.
3. **From Lago**: real product screenshots, shallow-staggered, no fake browser chrome, no 3D tilt — screenshots as proof, not screenshots as decoration.
4. **From Modern Treasury**: pair a UI screenshot with a code/API screenshot side-by-side in one feature section — untangle has both a human reviewer UI and an agent/API surface, and showing both in one glance sells to both buyer personas at once.
5. **From Polar**: use the numeric data itself (amounts, percentages, timestamps) as the primary visual texture in feature sections instead of illustration — quiet, confident, and on-brand for a finance tool that should look like it takes money seriously.

## CSP flags — what NOT to copy verbatim

- Google Fonts (`fonts.googleapis.com`) used by nearly every site studied — self-host Hanken Grotesk / Inter / JetBrains Mono as woff2 under `/fonts/` instead, declared via `@font-face` in an inline or self-hosted stylesheet.
- Any GSAP/Framer Motion/Lottie CDN script (common on Stripe/Ramp/Creem-style sites) — reimplement the small set of animations above in vanilla CSS/JS; none of them need a library at this scale.
- Third-party chat widgets, analytics beacons, or embedded video players (Creem's Discord widget, CRED's video posters via external CDNs) — if analytics/support chat is wanted, self-host or proxy through `'self'`.
- Inline `data:` SVG logos (used everywhere here, e.g., Stripe/Wise/Ramp) are actually fine under this CSP — no `img-src` restriction was specified beyond default-src 'self', but to be safe, prefer self-hosted `.svg` files served from your own origin over inline `data:` URIs at scale, and reserve inline SVG for the animated hero device itself where`'unsafe-inline'` on `style-src`/`script-src` already covers it.
