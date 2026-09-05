# untangle — Explained (for defending it in the room)

Plain-language walkthrough + the exact questions an engineer will ask, with answers you
can give. Read this until you can say it in your own words without notes.

## 1. What problem does it solve, in one breath?

"An Indian shop's bank account gets money from lots of places at once — Razorpay, a second
payment gateway, direct UPI, courier COD payouts, even personal transfers. Razorpay's own
report can reconcile the Razorpay transactions, but only *after* you know which bank credits
are even Razorpay's. Nobody solves that first step. untangle does — and it says 'I don't
know' instead of guessing, because a wrong guess quietly breaks your books."

## 2. The concepts, in kitchen language

- **Rail** = where a credit came from (Razorpay / other gateway / UPI / COD / unrelated).
- **Attribution** = deciding the rail for each bank credit.
- **UTR** = a bank transaction reference number. Razorpay's report lists a `settlement_utr`
  for each payout. If a bank credit's narration contains that exact UTR, it's almost
  certainly that Razorpay settlement. That's our strongest clue.
- **Evidence & confidence** = each clue (UTR match, a keyword like "DELHIVERY", the amount
  matching a settlement total, the dates lining up) is a weighted signal. We add them up
  into a confidence score.
- **Threshold (τ) / abstain** = if confidence is too low, we output UNKNOWN instead of a
  guess. Saying "unknown" is a feature, not a bug.
- **Precision vs recall** = *precision* = "when I say Razorpay, how often am I right?" (ours
  is 100%). *Recall* = "of all the real Razorpay credits, how many did I catch?" (ours is
  ~86–94%; the rest we abstain on). We deliberately favour precision.
- **Reconciliation (next phase)** = for the Razorpay credits, match each one to the exact
  set of transactions it paid for, down to the paise.
- **Fee-GST (next phase)** = Razorpay charges a fee, and GST on that fee. That GST is money
  the merchant can often reclaim as input tax credit — but it's buried in the lumped credit.
  We surface it *using Razorpay's own numbers*, so we never invent tax math.

## 3. How a single credit gets decided (follow one line)

1. **Ingest** reads the credit and makes a stable `line_key` (a hash of its own contents —
   not any id the data handed us, so it works on a real statement too).
2. **Evidence** looks for: a UTR that matches Razorpay's report, rail keywords, an amount
   equal to a settlement total, dates lining up, Razorpay identity tokens.
3. **Attribute** combines them: exact UTR → decided (Tier A). Otherwise score the clues
   (Tier B). If it looks Razorpay but the amount is a *sum* of settlements, try that (Tier C).
4. **Abstain** checks the score against τ. Below it → UNKNOWN.
5. If AI is on and the line is still UNKNOWN with messy text, the **LLM** may read the
   narration and propose a rail — but a deterministic rule must confirm it, and it can never
   invent a Razorpay verdict on its own.
6. The decision, its confidence, and the evidence trail are written to the report and the
   **audit ledger**.

## 4. The questions they'll ask — and your answers

**Q: "Your report already has the settlement UTR — what are you actually inferring?"**
A: "Your *recon* report reconciles the Razorpay transactions you already know are yours. My
input is the merchant's *bank statement*, where Razorpay credits are mixed with a second
gateway, UPI, COD payouts and personal transfers. I decide which bank lines are Razorpay's
in the first place — the step your report assumes is already done."

**Q: "Why not just grep for 'Razorpay' in the narration?"**
A: "Because real settlements often arrive brand-less (just a bank code and a UTR), and
decoys exist — a vendor refund literally says 'RAZORPAYX PAYOUTS'. I measured it: a brand
grep gets 0% recall on brand-less lines and 100% false-positives on decoys. My engine gets
zero decoy false-positives across five seeds."

**Q: "Why a set-sum / constraint solver instead of just widening the amount tolerance?"**
A: "One bank credit can pay for a *set* of settlements (merges, carry-forwards). Widening a
tolerance would match coincidental amounts and create false positives. A bounded set-sum
finds the actual covering set or abstains — it never guesses. The established exact 2–3-term
search handles pools up to 200; exact 4–5-term expansion is limited to pools of 16 or fewer
with a fixed combination budget."

**Q: "Precision 1.000 is suspicious. Is it leaking the answer?"**
A: "No — and I had it audited for exactly that. `engine/` never reads the ground truth or
the generator; a static test enforces it. Precision is 1.000 because the engine only commits
on a real tie back to the settlement report and abstains otherwise, so it's rarely *wrong*;
recall is ~0.91 (0.84 on a sealed holdout) because even split-settlement legs are recovered
when their amounts *provably* sum to a real settlement net. I validated on *unseen* seeds —
precision and zero-decoy-FP hold. Those are out-of-sample numbers, not a memorised benchmark."

**Q: "Where do you use AI, and where did you choose not to?"**
A: "Not in any money decision — matching, arithmetic and the Razorpay verdict are all
deterministic and unit-tested. AI only reads *ambiguous free-text narration* the rules
couldn't classify, and even then a deterministic rule confirms it. I can run the entire
system with AI switched off and report exactly what the model adds."

**Q: "What breaks it? What's the weakest part?"**
A: "Split settlements whose per-leg UTR the bank destroyed used to be my weakest class. I now
recover them the *provable* way: when two–three abstained bank legs' amounts UNIQUELY sum to a real
settlement net within the value-date window, that's a genuine tie back to the settlement report, so
I attribute them Razorpay (Tier C). If more than one distinct subset sums to the net, it's ambiguous
and I abstain — I never guess a decomposition. That's why recall jumped without touching precision.
The remaining weakness: my benchmark shares one generator's narration vocabulary, so true
novel-vocabulary generalization is unproven
until I test on a real statement — I say that openly rather than hide it."

## 5. What to be able to draw on a whiteboard

Three files in → ingest → evidence → three tiers → abstain → (optional AI edge) → report +
audit; eval scores it against a blind answer key. If you can draw that and name why each box
exists, you can defend this.
