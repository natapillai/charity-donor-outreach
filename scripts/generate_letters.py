#!/usr/bin/env python3
"""Deterministic donor letter generator for the charity-donor-outreach skill.

This script is the source of truth for segmentation, ask calculation, and
letter assembly. Identical inputs always produce identical outputs. It never
invents data. Rows with missing required data are skipped and reported in the
review summary instead of being filled with assumptions.
"""

import argparse
import csv
import math
import re
import sys
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

TIER_PCT = {"Platinum": 0.40, "Gold": 0.25, "Silver": 0.15}
VALID_TIERS = {"platinum": "Platinum", "gold": "Gold", "silver": "Silver", "bronze": "Bronze"}
CAMPAIGNS = ("emergency", "annual", "capital", "event")

LAPSED_AFTER_YEARS = 3      # lapsed when ref_year minus last_gift_year exceeds this
RECENT_WITHIN_YEARS = 1     # loyalty uplift when the last gift is this recent or newer
LAPSED_ASK = 50
BRONZE_BASE = 150.0
VOLUNTEER_BONUS = 100.0
LOYALTY_UPLIFT = 1.10
EMERGENCY_MULTIPLIER = 1.2
STREAK_MENTION_MIN = 3

FIELDNAMES = [
    "donor_name", "tier_used", "computed_tier", "lapsed", "lifetime_total",
    "largest_gift", "last_gift_year", "volunteer", "ask_amount", "action",
    "flags", "letter_file",
]

GIFT_RE = re.compile(r"(\d{4})\s*:\s*\$?\s*([\d,]+(?:\.\d{1,2})?)")

TIER_LINE = {
    "Platinum": ("As one of our most dedicated supporters, we would be honored to "
                 "speak with you about naming opportunities that recognize your "
                 "extraordinary impact."),
    "Gold": ("If you would like your compassion for animals to carry on for "
             "generations, we would be glad to share information about legacy giving."),
    "Silver": ("Many supporters at your level choose a monthly gift as an easy way to "
               "deepen their impact, and we would be happy to help you set that up."),
    "Bronze": ("You can multiply your impact by starting a peer fundraising page and "
               "inviting friends and family to join you."),
}


def parse_money(text):
    if text is None or str(text).strip() == "":
        return None
    cleaned = str(text).replace(",", "").replace("$", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_gifts(text):
    """Parse a history string like '2019: $500, 2021: $1,200' into (year, amount) pairs."""
    return sorted((int(y), float(a.replace(",", ""))) for y, a in GIFT_RE.findall(text or ""))


def parse_bool(text):
    return str(text or "").strip().lower() in {"yes", "y", "true", "1"}


def parse_year(text):
    try:
        return int(float(str(text).strip()))
    except (TypeError, ValueError):
        return None


def parse_ref_date(text):
    if not text:
        return date.today()
    t = str(text).strip()
    if re.fullmatch(r"\d{4}", t):
        return date(int(t), 12, 31)
    return date.fromisoformat(t)


def compute_tier(lifetime_total):
    if lifetime_total >= 50000:
        return "Platinum"
    if lifetime_total >= 10000:
        return "Gold"
    if lifetime_total >= 1000:
        return "Silver"
    return "Bronze"


def giving_streak(gifts):
    """Length of the consecutive year run ending at the most recent gift year."""
    years = sorted({y for y, _ in gifts})
    if not years:
        return 0
    streak = 1
    for prev, curr in zip(years, years[1:]):
        streak = streak + 1 if curr == prev + 1 else 1
    return streak


def round_to_50(amount):
    """Round to the nearest 50, halves round up."""
    return int(math.floor(amount / 50.0 + 0.5)) * 50


def compute_ask(tier, lapsed, largest_gift, last_gift_year, volunteer, campaign, ref_year):
    if lapsed:
        return LAPSED_ASK
    if tier == "Bronze":
        ask = BRONZE_BASE
    else:
        ask = largest_gift * TIER_PCT[tier]
        if last_gift_year is not None and last_gift_year >= ref_year - RECENT_WITHIN_YEARS:
            ask *= LOYALTY_UPLIFT
    if volunteer:
        ask += VOLUNTEER_BONUS
    if campaign == "emergency":
        ask *= EMERGENCY_MULTIPLIER
    return round_to_50(ask)


def build_salutation(name, title, tier, lapsed):
    parts = name.split()
    first = parts[0]
    last = parts[-1]
    if lapsed:
        return f"We've missed you, {first}!"
    if tier in ("Platinum", "Gold"):
        if title:
            return f"Dear {title} {last},"
        return f"Dear {name},"
    return f"Hi {first},"


def region_phrase(region):
    if not region:
        return ""
    r = region.strip()
    if r.lower() == "international":
        return " around the world"
    return f" in the {r} region"


def build_campaign_paragraph(campaign, region, streak, match_details,
                             registered_count, charity_name):
    where = region_phrase(region)
    if campaign == "emergency":
        text = (f"Right now, animals{where} urgently need rescue, shelter, and medical "
                f"care, and gifts made today are put to work immediately. Every hour "
                f"truly counts for an animal in crisis.")
        if match_details:
            text += " " + match_details.strip()
        return text
    if campaign == "annual":
        streak_clause = ""
        if streak >= STREAK_MENTION_MIN:
            streak_clause = f", including {streak} consecutive years of giving,"
        return (f"Steady support from friends like you{where} is what allows "
                f"{charity_name} to plan ahead and be there for animals every single "
                f"day. Your history with us{streak_clause} means more than we can say.")
    if campaign == "capital":
        return (f"We are building something permanent{where}, a place of safety and "
                f"healing that will serve animals for generations to come. A gift to "
                f"this campaign lays a foundation that will stand long after the "
                f"ribbon is cut.")
    if registered_count:
        lead = (f"Over {registered_count:,} supporters have already registered, and we "
                f"would love for you to join the fun{where}.")
    else:
        lead = f"Supporters are already signing up, and we would love for you to join the fun{where}."
    return lead + " It is a wonderful way to celebrate the animals and the community that cares for them."


def build_ask_sentence(ask, lapsed, tier):
    amount = f"${ask:,}"
    if lapsed:
        return (f"We would love to welcome you back with a gift of "
                f"<strong>{amount}</strong> to restart your giving journey. As a "
                f"welcome back thank you, we will also send you one of our tote bags.")
    return (f"Today, I would like to invite you to make a gift of "
            f"<strong>{amount}</strong>. " + TIER_LINE[tier])


def render_letter(template, mapping):
    out = template
    for key, value in mapping.items():
        out = out.replace("{{" + key + "}}", str(value))
    return out


def slugify(name):
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", ascii_name).strip("_").lower()
    return slug or "donor"


def make_row(**kwargs):
    row = {key: "" for key in FIELDNAMES}
    row.update({key: str(value) for key, value in kwargs.items()})
    return row


def main():
    parser = argparse.ArgumentParser(
        description="Generate donor outreach letter drafts from a donor CSV.")
    parser.add_argument("--csv", required=True, help="Path to the donor CSV file.")
    parser.add_argument("--campaign", required=True, choices=CAMPAIGNS)
    parser.add_argument("--charity-name", default="the ASPCA")
    parser.add_argument("--donation-url", required=True,
                        help="Confirmed donation page URL. Never guessed.")
    parser.add_argument("--signer-name", required=True,
                        help="Real staff signer. Never invented.")
    parser.add_argument("--signer-title", default="Donor Relations")
    parser.add_argument("--as-of", default=None,
                        help="Reference date, YYYY-MM-DD or YYYY. Defaults to today.")
    parser.add_argument("--match-details", default=None,
                        help="One confirmed matching gift sentence. Omit when no confirmed match exists.")
    parser.add_argument("--registered-count", type=int, default=None,
                        help="Confirmed event registration count.")
    parser.add_argument("--outdir", default="output")
    args = parser.parse_args()

    try:
        ref_date = parse_ref_date(args.as_of)
    except ValueError:
        sys.exit("Could not parse --as-of. Use YYYY-MM-DD or YYYY.")
    ref_year = ref_date.year
    letter_date = f"{ref_date.strftime('%B')} {ref_date.day}, {ref_date.year}"

    template_path = Path(__file__).resolve().parent.parent / "assets" / "letter_template.html"
    if not template_path.exists():
        sys.exit(f"Template not found at {template_path}")
    template = template_path.read_text(encoding="utf-8")

    csv_path = Path(args.csv)
    if not csv_path.exists():
        sys.exit(f"CSV not found at {csv_path}")

    outdir = Path(args.outdir)
    letters_dir = outdir / "letters"
    letters_dir.mkdir(parents=True, exist_ok=True)

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        raw_rows = list(csv.DictReader(f))
    if not raw_rows:
        sys.exit("The CSV appears to be empty.")

    summary_rows = []
    flag_counter = Counter()
    used_slugs = {}
    counts = Counter()
    total_asked = 0
    personal_outreach_names = []

    for raw in raw_rows:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        name = row.get("donor_name", "")
        flags = []

        if not name:
            summary_rows.append(make_row(donor_name="(missing)", action="skipped",
                                         flags="missing_donor_name"))
            flag_counter["missing_donor_name"] += 1
            counts["skipped"] += 1
            continue

        gifts = parse_gifts(row.get("gifts", ""))
        last_amount = None
        if gifts:
            largest = max(a for _, a in gifts)
            lifetime = sum(a for _, a in gifts)
            last_year = max(y for y, _ in gifts)
            last_amount = max(a for y, a in gifts if y == last_year)
        else:
            largest = parse_money(row.get("largest_gift"))
            lifetime = parse_money(row.get("lifetime_total"))
            last_year = parse_year(row.get("last_gift_year"))
            if largest is None or lifetime is None or last_year is None:
                summary_rows.append(make_row(donor_name=name, action="skipped",
                                             flags="missing_giving_data"))
                flag_counter["missing_giving_data"] += 1
                counts["skipped"] += 1
                continue

        computed = compute_tier(lifetime)
        provided = row.get("tier", "").strip().lower()
        if provided in VALID_TIERS:
            tier = VALID_TIERS[provided]
            if tier != computed:
                flags.append(f"tier_mismatch(csv={tier},computed={computed})")
                flag_counter["tier_mismatch"] += 1
        else:
            tier = computed
            if provided and provided not in {"lapsed", "unknown"}:
                flags.append("unrecognized_tier_value")
                flag_counter["unrecognized_tier_value"] += 1

        lapsed = (ref_year - last_year) > LAPSED_AFTER_YEARS
        if provided == "lapsed" and not lapsed:
            flags.append("csv_says_lapsed_but_recent_gift")
            flag_counter["csv_says_lapsed_but_recent_gift"] += 1

        volunteer = parse_bool(row.get("volunteer"))
        region = row.get("region", "")
        title = row.get("title", "")

        if lapsed and tier in ("Platinum", "Gold"):
            flags.append("high_value_lapsed")
            flag_counter["high_value_lapsed"] += 1
            summary_rows.append(make_row(
                donor_name=name, tier_used=tier, computed_tier=computed, lapsed="yes",
                lifetime_total=f"{lifetime:.0f}", largest_gift=f"{largest:.0f}",
                last_gift_year=last_year, volunteer="yes" if volunteer else "no",
                action="personal_outreach", flags="|".join(flags)))
            counts["personal_outreach"] += 1
            personal_outreach_names.append(name)
            continue

        ask = compute_ask(tier, lapsed, largest, last_year, volunteer,
                          args.campaign, ref_year)
        if not lapsed and last_amount is not None and ask < last_amount:
            flags.append("ask_below_last_gift")
            flag_counter["ask_below_last_gift"] += 1

        streak = giving_streak(gifts) if gifts else 0
        signer = row.get("relationship_manager") or args.signer_name

        mapping = {
            "DATE": letter_date,
            "SALUTATION": build_salutation(name, title, tier, lapsed),
            "CHARITY_NAME": args.charity_name,
            "LIFETIME_TOTAL": f"{lifetime:,.0f}",
            "CAMPAIGN_PARAGRAPH": build_campaign_paragraph(
                args.campaign, region, streak, args.match_details,
                args.registered_count, args.charity_name),
            "ASK_SENTENCE": build_ask_sentence(ask, lapsed, tier),
            "DONATION_URL": args.donation_url,
            "SIGNER_NAME": signer,
            "SIGNER_TITLE": args.signer_title,
        }

        slug = slugify(name)
        if slug in used_slugs:
            used_slugs[slug] += 1
            slug = f"{slug}_{used_slugs[slug]}"
        else:
            used_slugs[slug] = 1
        letter_path = letters_dir / f"{slug}.html"
        letter_path.write_text(render_letter(template, mapping), encoding="utf-8")

        segment = tier + (" (lapsed)" if lapsed else "")
        counts[segment] += 1
        counts["letters"] += 1
        total_asked += ask

        summary_rows.append(make_row(
            donor_name=name, tier_used=segment, computed_tier=computed,
            lapsed="yes" if lapsed else "no", lifetime_total=f"{lifetime:.0f}",
            largest_gift=f"{largest:.0f}", last_gift_year=last_year,
            volunteer="yes" if volunteer else "no", ask_amount=ask,
            action="letter_drafted", flags="|".join(flags),
            letter_file=str(letter_path)))

    summary_path = outdir / "review_summary.csv"
    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"Campaign type          {args.campaign}")
    print(f"Reference date         {ref_date.isoformat()}")
    print(f"Rows read              {len(raw_rows)}")
    print(f"Letter drafts written  {counts['letters']}")
    print(f"Flagged for personal outreach  {counts['personal_outreach']}")
    if personal_outreach_names:
        print("  " + ", ".join(personal_outreach_names))
    print(f"Rows skipped           {counts['skipped']}")
    print(f"Total asked across drafts  ${total_asked:,}")
    segments = [k for k in counts if k not in ("letters", "personal_outreach", "skipped")]
    for segment in sorted(segments):
        print(f"  {segment}: {counts[segment]} letters")
    if flag_counter:
        print("Flags for staff review")
        for flag, n in flag_counter.most_common():
            print(f"  {flag}: {n}")
    print(f"Letters directory      {letters_dir}")
    print(f"Review summary         {summary_path}")
    print("All letters are DRAFTS. A human must review before sending.")


if __name__ == "__main__":
    main()
