---
name: charity-donor-outreach
description: Generate personalized fundraising letter drafts for ASPCA donors from an uploaded donor list. Use whenever the user provides a donor CSV or spreadsheet and wants campaign letters, donor appeals, solicitation emails, or segmented outreach for an annual fund, emergency appeal, capital campaign, or event fundraiser, even if they just say "write to our donors." Do not use for general email drafting, grant writing, volunteer coordination, internal reports, or communication tasks unrelated to donor solicitation.
compatibility: Requires the ability to run Python 3 scripts and write files to disk.
---

# Charity Donor Outreach Letter Generator

Turn a donor CSV into consistent letter drafts that are ready for staff review. All segmentation, ask calculation, and letter assembly happen in a deterministic script, so the same inputs always produce the same outputs. Claude's job is to gather inputs, run the script, surface everything the script flagged, and optionally enrich individual letters. The letters are drafts. Nothing in this skill sends anything.

## Inputs to collect before running

1. The donor file. The uploaded CSV is the single source of truth for donor data. Never pull donor details from anywhere else, and never invent values that are missing from the file.
2. The campaign type. One of `emergency`, `annual`, `capital`, `event`.
3. Config values, confirmed by the user and never guessed.
   * Charity display name (defaults to "the ASPCA")
   * Donation page URL (required)
   * Signer name and title (required, must be a real person or team)
4. Optional values.
   * Reference date for recency logic. Defaults to today. Set it to match the vintage of the donor data if the file is a historical export.
   * Confirmed matching gift details, only if a real match exists
   * Confirmed registration count for event campaigns

If a required value is missing, ask the user for it. Do not proceed on a guess.

## Donor CSV schema

| Column | Required | Notes |
|---|---|---|
| donor_name | yes | Full name |
| title | no | e.g. Ms., Dr. Used only when present. Never inferred from a first name. |
| tier | no | Platinum, Gold, Silver, or Bronze. Cross checked against the computed tier. |
| region | no | Used for light localization in the campaign paragraph. |
| gifts | yes* | Giving history in the form "2019: $500, 2021: $1,200" |
| largest_gift, lifetime_total, last_gift_year | yes* | Accepted together as an alternative when full history is unavailable |
| volunteer | no | Yes or No. Defaults to No. |
| relationship_manager | no | Overrides the signer on that donor's letter when present |

*Each row needs either a parseable `gifts` value or all three of the alternative columns. Rows that satisfy neither are skipped and listed in the review summary with a reason. They are never filled in with assumptions, because a guessed name or amount reaching a real donor is worse than a skipped row.

## Workflow

1. Inspect the CSV header and a few rows. Confirm the campaign type and config values with the user.
2. Run the generator.

```bash
python scripts/generate_letters.py \
  --csv /path/to/donors.csv \
  --campaign annual \
  --donation-url "https://example.org/donate" \
  --signer-name "Jane Doe" \
  --signer-title "Development Director" \
  --outdir output
```

3. Read `output/review_summary.csv`. Report the results in chat, including counts per segment, the total amount asked, every skipped row with its reason, and every flag. Flags exist so a human can catch problems before a letter reaches a donor, so never bury them.
4. Present the letters and the review summary to the user as files, clearly labeled as drafts pending staff review.
5. Optional enrichment. If the user wants deeper personalization for specific donors, edit only the campaign paragraph of those letters, using only facts present in that donor's row. Never change computed ask amounts, salutations, or lifetime totals, and never add claims that are not in the data or the confirmed config.

## Segmentation rules

The script is the source of truth for everything in this section and the next. The summary here is for explaining results to the user.

Giving tier comes from lifetime total. Platinum is $50,000 and above. Gold is $10,000 and above. Silver is $1,000 and above. Bronze is below $1,000. If the CSV supplies a tier that disagrees with the computed tier, the CSV tier is used, since staff may have CRM context the file does not show, and the row is flagged `tier_mismatch` for review.

Lapsed is a recency status, not a tier. A donor is lapsed when more than 3 full years have passed since `last_gift_year`, measured against the reference date. Lapsed Silver and Bronze donors receive the reengagement letter. Lapsed Gold and Platinum donors are excluded from the bulk run and flagged `high_value_lapsed`, because a $50 form letter to a major donor damages the relationship. Those donors should get personal outreach from staff.

## Ask amount rules

Applied in this exact order.

1. Base ask. Platinum takes 40%, Gold takes 25%, and Silver takes 15% of the donor's largest single gift. Bronze uses a flat $150 base and skips step 2, since the flat amount is independent of gift history.
2. Loyalty uplift. If the donor gave in the reference year or the year before it, multiply by 1.10.
3. Volunteer bonus. Add $100 when the donor is a volunteer.
4. Emergency multiplier. For an emergency appeal, multiply by 1.2.
5. Rounding happens last. Round to the nearest $50, with halves rounding up.
6. Lapsed donors skip all of the above and receive a flat $50 reengagement ask.
7. Guardrail. When the final ask is lower than the donor's most recent gift, the letter is still generated but the row is flagged `ask_below_last_gift`. The tier percentages frequently produce asks below recent giving for donors on an upward trend, so surface these flags and suggest that the fundraising team confirm the percentage table.

## Salutations and tone

* Platinum and Gold use "Dear [Title] [Last Name]," when a title exists in the data, otherwise "Dear [Full Name],". Titles are never guessed from first names, because misgendering a major donor is far worse than a slightly formal fallback.
* Silver and Bronze use "Hi [First Name],".
* Lapsed uses "We've missed you, [First Name]!".
* Tone for the campaign paragraph during enrichment. Platinum formal, Gold warm and professional, Silver friendly, Bronze casual and encouraging, Lapsed warm and welcoming rather than apologetic.

## Campaign messaging

* Emergency appeal. Urgency is appropriate. A matching gift is mentioned only when the user supplied confirmed match details. Never state or imply an unconfirmed match. Promising a match that does not exist is deceptive solicitation and a legal and reputational risk for the charity.
* Annual fund. Consistency and community. The script computes a consecutive year giving streak and mentions it when it reaches 3 or more years.
* Capital campaign. Legacy and permanence, with building imagery.
* Event fundraiser. Fun and social proof. A registration count appears only when the user supplied one. Never invent attendance numbers.

Tier lines. Platinum letters invite a conversation about naming opportunities. Gold letters mention legacy giving. Silver letters mention a monthly giving upgrade. Bronze letters mention peer fundraising pages. Lapsed letters offer a tote bag as a welcome back gift.

## Guardrails

* Never fabricate donor data, staff names, URLs, matching gifts, or attendance numbers.
* Never infer gender or titles from names.
* Present every letter as a draft. A human reviews before anything is sent.
* If the file contains unexpected sensitive fields such as payment details, leave them out of the letters and tell the user.
* If the environment cannot execute the script, stop and tell the user. Never compute ask amounts by hand, because hand computed math breaks the consistency guarantee this skill exists to provide.

## Files

* `scripts/generate_letters.py` is the deterministic generator and the source of truth for all rules above.
* `assets/letter_template.html` is the letter template.
* `examples/sample_donors.csv` is mocked sample data for testing. It contains no real donors.
* `scripts/run_tests.py` checks every rule and reruns the full sample end to end. Run it with `python scripts/run_tests.py` if results ever look wrong.
