"""
test_cases.py - runs normal, edge and failure test cases through the pipeline and
saves results.csv (use these numbers on the 'Testing and Evaluation' slide).

Run:   python test_cases.py                         (demo mode, no API key)
       set GEMINI_API_KEY=your_key & python test_cases.py   (Windows, live Gemini)
       GEMINI_API_KEY=your_key python test_cases.py          (Mac/Linux, live Gemini)

IMPORTANT: run it with your API key for the final numbers; demo mode only tests
the pipeline logic, not the quality of the LLM output.
"""

import csv
from datetime import date

from agents import LLM, Logger, run_pipeline

START = date(2026, 11, 23)  # a Monday


def case(name, kind, topic, audience, platform, tone, days, ppw, expect_ok=True, llm=None):
    return dict(name=name, kind=kind, expect_ok=expect_ok, llm=llm,
                inp=dict(topic=topic, audience=audience, platform=platform, tone=tone,
                         days=days, posts_per_week=ppw, start_date=START))


CASES = [
    case("T1 Fitness on Instagram", "Normal", "Fitness tips", "college students", "Instagram", "Friendly", 7, 3),
    case("T2 Same topic on LinkedIn", "Normal", "Fitness tips", "college students", "LinkedIn", "Professional", 7, 3),
    case("T3 Same topic on X", "Normal", "Fitness tips", "college students", "X (Twitter)", "Funny", 7, 3),
    case("T4 Cooking channel, 2 weeks", "Normal", "Budget cooking", "hostel students", "Instagram", "Educational", 14, 4),
    case("T5 Very short topic", "Edge", "Tea", "tea lovers", "Instagram", "Friendly", 7, 2),
    case("T6 Long plan (30 days, daily)", "Edge", "Study techniques", "engineering students", "LinkedIn", "Inspirational", 30, 7),
    case("T7 Empty topic", "Failure", "", "students", "Instagram", "Friendly", 7, 3, expect_ok=False),
    case("T8 Invalid API key (graceful fallback)", "Failure", "Personal finance", "first-year students",
         "Instagram", "Friendly", 7, 3, expect_ok=True, llm=LLM(api_key="invalid-key-for-test")),
]


def main():
    default_llm = LLM()
    print(f"Mode: {default_llm.mode}\n")
    rows = []
    for c in CASES:
        llm = c["llm"] or default_llm
        result = run_pipeline(c["inp"], llm, Logger())
        if result["ok"]:
            passed = c["expect_ok"] and result["remaining_failures"] == 0
            posts, fixed = len(result["posts"]), result["initial_failures"] - result["remaining_failures"]
            seconds = result["seconds"]
            note = "all posts passed review" if passed else "some posts still flagged"
        else:
            passed = not c["expect_ok"]
            posts, fixed, seconds = 0, 0, 0
            note = "rejected with message: " + result["errors"][0]
        rows.append({"test": c["name"], "type": c["kind"], "posts": posts,
                     "fixed_by_reviewer": fixed, "seconds": seconds,
                     "result": "PASS" if passed else "FAIL", "note": note})
        print(f"{rows[-1]['result']:5} {c['name']:42} posts={posts:3} fixed={fixed:2} time={seconds}s")

    with open("results.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    ok = [r for r in rows if r["result"] == "PASS"]
    timed = [r["seconds"] for r in rows if r["posts"]]
    print(f"\nTask success rate: {len(ok)}/{len(rows)} = {len(ok) / len(rows):.0%}")
    if timed:
        print(f"Average latency: {sum(timed) / len(timed):.1f}s per plan")
    print("Saved results.csv")


if __name__ == "__main__":
    main()
