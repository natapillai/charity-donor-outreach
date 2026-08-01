# charity-donor-outreach

A [Claude Skill](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview) that turns a donor CSV into personalized fundraising letter drafts, ready for staff review.

Every decision that affects a donor is made by a deterministic Python script rather than by the model: which segment they fall into, how much they are asked for, how they are greeted. The same CSV always produces the same letters. Claude's job is to collect the inputs, run the script, and surface everything the script flagged for a human.

## Why the logic lives in a script

Fundraising letters go to real people and quote real money. Three properties matter more than flexibility:

* **Reproducibility.** Rerunning a campaign a week later must not quietly change anyone's ask amount.
* **Auditability.** A fundraising director can read `scripts/generate_letters.py` and see exactly why a donor was asked for $1,250.
* **No fabrication.** Missing data is skipped and reported, never filled in with a plausible guess. A wrong name or invented matching gift reaching a real donor is worse than a blank row.

So the skill splits the work. The script owns arithmetic and rules. Claude owns conversation, judgment, and optional enrichment of individual letters within stated bounds.

## What it produces

```
output/
  letters/
    margaret_alcott.html
    ruth_andersen.html
    ...
  review_summary.csv
```

Each letter is marked **DRAFT** in the body. The review summary has one row per input row with the tier used, the computed tier, lapsed status, the ask amount, the action taken, and any flags raised.

Nothing in this skill sends anything.

## Quick start

Requires Python 3 and no third party packages. On macOS and Linux, substitute `python3` if `python` is not on your PATH.

```bash
python scripts/generate_letters.py \
  --csv examples/sample_donors.csv \
  --campaign annual \
  --donation-url "https://example.org/donate" \
  --signer-name "Jane Doe" \
  --signer-title "Development Director" \
  --as-of 2024-12-31 \
  --outdir output
```

Output:

```
Campaign type          annual
Reference date         2024-12-31
Rows read              50
Letter drafts written  48
Flagged for personal outreach  2
  Robert Svensson, Walter Adeyemi
Rows skipped           0
Total asked across drafts  $129,900
  Bronze: 11 letters
  Bronze (lapsed): 6 letters
  Gold: 12 letters
  Platinum: 3 letters
  Silver: 12 letters
  Silver (lapsed): 4 letters
Flags for staff review
  ask_below_last_gift: 30
  tier_mismatch: 4
  high_value_lapsed: 2
Letters directory      output/letters
Review summary         output/review_summary.csv
All letters are DRAFTS. A human must review before sending.
```

### Options

| Flag | Required | Notes |
|---|---|---|
| `--csv` | yes | Path to the donor CSV |
| `--campaign` | yes | `emergency`, `annual`, `capital`, or `event` |
| `--donation-url` | yes | Confirmed donation page. Never guessed |
| `--signer-name` | yes | A real staff member. Never invented |
| `--signer-title` | no | Defaults to `Donor Relations` |
| `--charity-name` | no | Defaults to `the ASPCA` |
| `--as-of` | no | `YYYY-MM-DD` or `YYYY`. Defaults to today. Set it to match the vintage of a historical export |
| `--match-details` | no | One confirmed sentence about a matching gift. Omitted entirely when no real match exists |
| `--registered-count` | no | Confirmed event registration count |
| `--outdir` | no | Defaults to `output` |

## Donor CSV schema

| Column | Required | Notes |
|---|---|---|
| `donor_name` | yes | Full name |
| `title` | no | e.g. `Ms.`, `Dr.` Used only when present, never inferred from a first name |
| `tier` | no | Platinum, Gold, Silver, Bronze. Cross checked against the computed tier |
| `region` | no | Light localization in the campaign paragraph |
| `gifts` | yes\* | Giving history as `2019: $500, 2021: $1,200` |
| `largest_gift`, `lifetime_total`, `last_gift_year` | yes\* | Accepted together when full history is unavailable |
| `volunteer` | no | Yes or No, defaults to No |
| `relationship_manager` | no | Overrides the signer on that donor's letter |

\* Each row needs either a parseable `gifts` value or all three alternative columns. Rows satisfying neither are skipped and listed in the review summary with a reason.

## The rules

### Segmentation

Tier comes from lifetime total. **Platinum** is $50,000 and above, **Gold** is $10,000 and above, **Silver** is $1,000 and above, **Bronze** is below $1,000.

When the CSV supplies a tier that disagrees with the computed one, **the CSV wins** and the row is flagged `tier_mismatch`. Staff may have CRM context the export does not show, so the file is trusted. The disagreement is never hidden.

Lapsed is a recency status rather than a tier: more than 3 full years since `last_gift_year`, measured against the reference date.

### Ask amounts

Applied in this exact order, rounding last:

1. **Base.** Platinum 40%, Gold 25%, Silver 15% of the largest single gift. Bronze uses a flat $150 and skips step 2.
2. **Loyalty uplift.** ×1.10 if the donor gave in the reference year or the one before.
3. **Volunteer bonus.** +$100.
4. **Emergency multiplier.** ×1.2 for emergency appeals.
5. **Round** to the nearest $50, halves up.
6. **Lapsed donors skip all of it** and get a flat $50 reengagement ask.

### Two guardrails worth calling out

**Major donors who lapse are pulled out of the bulk run.** A lapsed Platinum or Gold donor is excluded, flagged `high_value_lapsed`, and routed to personal staff outreach. A $50 form letter to someone who once gave $50,000 damages the relationship more than sending nothing.

**Asks below the last gift are flagged rather than silently corrected.** The tier percentages routinely produce an ask lower than a donor's most recent gift when they are trending upward. 30 of the 48 sample letters hit this. The letter is still generated, but the row carries `ask_below_last_gift` so the fundraising team can decide whether the percentage table needs revisiting. That is a policy question for humans, not something a script should paper over.

### Salutations

Platinum and Gold get `Dear [Title] [Last Name],` when a title is present in the data, otherwise `Dear [Full Name],`. Titles are **never** inferred from first names, because misgendering a major donor is far worse than a slightly formal fallback. Silver and Bronze get `Hi [First Name],`. Lapsed donors get `We've missed you, [First Name]!`.

## Safety constraints

* Never fabricate donor data, staff names, URLs, matching gifts, or attendance numbers.
* Matching gifts and event registration counts appear **only** when explicitly supplied. Promising a match that does not exist is deceptive solicitation and a legal risk for the charity.
* Never infer gender or titles from names.
* Every letter is a draft. A human reviews before anything is sent.
* If the CSV contains unexpected sensitive fields such as payment details, they are kept out of the letters and reported to the user.
* If the script cannot run, the skill stops rather than computing asks by hand, because hand computed math breaks the consistency guarantee the skill exists to provide.

## Tests

```bash
python scripts/run_tests.py
```

34 checks covering rounding behavior, tier boundaries, modifier ordering, lapsed thresholds, streak counting, and salutation fallbacks, plus a full end to end run against the sample data that must reproduce exact known numbers: 48 letters, 2 routed to personal outreach, 4 tier mismatches, 30 ask flags.

## Layout

```
SKILL.md                          Skill definition and workflow Claude follows
scripts/generate_letters.py       Deterministic generator, source of truth for all rules
scripts/run_tests.py              Rule checks and end to end verification
assets/letter_template.html       Letter template with {{PLACEHOLDER}} tokens
examples/sample_donors.csv        50 mocked donors, no real people
Natarajan_Pillai_Case_Study.pdf   Written case study accompanying this skill
```

`examples/sample_donors.csv` is fabricated test data. It contains no real donors.
