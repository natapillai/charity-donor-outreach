#!/usr/bin/env python3
"""Checks for the charity-donor-outreach rules.

Runs unit checks on every business rule, then an end to end run against
examples/sample_donors.csv that must reproduce known numbers exactly.
Usage: python scripts/run_tests.py
"""

import csv
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_letters as gl

SKILL_DIR = Path(__file__).resolve().parent.parent
PASSED = 0


def check(label, actual, expected):
    global PASSED
    if actual != expected:
        print(f"FAIL  {label}  expected {expected!r} got {actual!r}")
        sys.exit(1)
    PASSED += 1
    print(f"ok    {label}")


def main():
    # Rounding rounds to the nearest 50 with halves up
    check("round 1255 down to 1250", gl.round_to_50(1255), 1250)
    check("round half 1225 up to 1250", gl.round_to_50(1225), 1250)
    check("round half 25 up to 50", gl.round_to_50(25), 50)
    check("round 1224.99 down to 1200", gl.round_to_50(1224.99), 1200)

    # Tier boundaries use inclusive lower bounds so no amount falls in a gap
    check("tier at exactly 50000 is Platinum", gl.compute_tier(50000), "Platinum")
    check("tier at 49999 is Gold", gl.compute_tier(49999), "Gold")
    check("tier at exactly 10000 is Gold", gl.compute_tier(10000), "Gold")
    check("tier at 9999 is Silver", gl.compute_tier(9999), "Silver")
    check("tier at exactly 1000 is Silver", gl.compute_tier(1000), "Silver")
    check("tier at 999 is Bronze", gl.compute_tier(999), "Bronze")

    # Ask amounts, ordered modifiers, rounding last
    check("Platinum volunteer no uplift (Earl case)",
          gl.compute_ask("Platinum", False, 90000, 2022, True, "annual", 2024), 36100)
    check("Silver uplift plus volunteer (Ruth as Silver)",
          gl.compute_ask("Silver", False, 7000, 2023, True, "annual", 2024), 1250)
    check("Bronze skips uplift, keeps bonus and emergency",
          gl.compute_ask("Bronze", False, 800, 2023, True, "emergency", 2024), 300)
    check("lapsed is flat 50 even with volunteer and emergency",
          gl.compute_ask("Gold", True, 12000, 2019, True, "emergency", 2024), 50)

    # Lapsed means strictly more than 3 full years since the last gift
    check("3 years since last gift is not lapsed", (2024 - 2021) > gl.LAPSED_AFTER_YEARS, False)
    check("4 years since last gift is lapsed", (2024 - 2020) > gl.LAPSED_AFTER_YEARS, True)

    # Giving streak counts the consecutive run ending at the latest year
    check("five consecutive years", gl.giving_streak([(y, 100) for y in range(2019, 2024)]), 5)
    check("gap resets the streak", gl.giving_streak([(2018, 1), (2019, 1), (2023, 1)]), 1)
    check("no gifts means no streak", gl.giving_streak([]), 0)

    # Salutations never guess a title
    check("formal with title", gl.build_salutation("Jane Doe", "Dr.", "Gold", False), "Dear Dr. Doe,")
    check("formal without title falls back to full name",
          gl.build_salutation("Jane Doe", "", "Platinum", False), "Dear Jane Doe,")
    check("casual for Silver", gl.build_salutation("Jane Doe", "", "Silver", False), "Hi Jane,")
    check("lapsed greeting", gl.build_salutation("Jane Doe", "", "Gold", True), "We've missed you, Jane!")

    # End to end. The sample data must reproduce these exact numbers.
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [sys.executable, str(SKILL_DIR / "scripts" / "generate_letters.py"),
               "--csv", str(SKILL_DIR / "examples" / "sample_donors.csv"),
               "--campaign", "annual",
               "--donation-url", "https://example.org/donate",
               "--signer-name", "Jane Doe",
               "--as-of", "2024-12-31",
               "--outdir", tmp]
        result = subprocess.run(cmd, capture_output=True, text=True)
        check("generator exits cleanly", result.returncode, 0)

        with open(Path(tmp) / "review_summary.csv", newline="") as f:
            rows = list(csv.DictReader(f))
        by_name = {r["donor_name"]: r for r in rows}

        check("50 rows in the summary", len(rows), 50)
        check("48 letters drafted",
              sum(1 for r in rows if r["action"] == "letter_drafted"), 48)
        check("2 routed to personal outreach",
              sorted(r["donor_name"] for r in rows if r["action"] == "personal_outreach"),
              ["Robert Svensson", "Walter Adeyemi"])
        check("no rows skipped", sum(1 for r in rows if r["action"] == "skipped"), 0)
        check("all 4 tier mismatches caught",
              sum(1 for r in rows if "tier_mismatch" in r["flags"]), 4)
        check("30 asks flagged below the last gift",
              sum(1 for r in rows if "ask_below_last_gift" in r["flags"]), 30)
        check("Earl Fontaine ask", by_name["Earl Fontaine"]["ask_amount"], "36100")
        check("Ruth Andersen ask", by_name["Ruth Andersen"]["ask_amount"], "1250")
        check("Ruth Andersen carries both flags",
              "tier_mismatch" in by_name["Ruth Andersen"]["flags"]
              and "ask_below_last_gift" in by_name["Ruth Andersen"]["flags"], True)
        check("letters written to disk",
              len(list((Path(tmp) / "letters").glob("*.html"))), 48)

    print(f"\nAll {PASSED} checks passed.")


if __name__ == "__main__":
    main()
