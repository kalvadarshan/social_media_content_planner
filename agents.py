"""
agents.py - the four agents of the AI Social Media Content Planner.

Pipeline:  Research Agent -> Planner Agent -> Writer Agent -> Reviewer Agent
                                                  ^               |
                                                  +--- fix loop --+   (max 2 retries)

Each agent is a plain Python function that receives data and returns data
(JSON-like dicts/lists). The function `run_pipeline` is the "orchestrator"
that passes the output of one agent to the next.

If no Gemini API key is available (or an API call fails), every agent falls back
to a built-in template generator so the app still runs. This is shown clearly in
the log, so the user always knows which mode produced the output.
"""

import difflib
import json
import math
import os
import random
import re
import time
from datetime import date, datetime, timedelta

# --------------------------------------------------------------------------
# Platform rules (used by Planner and Reviewer)
# --------------------------------------------------------------------------
PLATFORM_RULES = {
    "Instagram": {
        "max_chars": 2200,
        "max_hashtags": 10,
        "post_types": ["Reel", "Carousel", "Single image", "Story poll", "Quote card"],
    },
    "LinkedIn": {
        "max_chars": 3000,
        "max_hashtags": 5,
        "post_types": ["Text post", "Carousel (PDF)", "Poll", "Article teaser", "Case study"],
    },
    "X (Twitter)": {
        "max_chars": 280,
        "max_hashtags": 3,
        "post_types": ["Tweet", "Thread opener", "Poll", "Tip", "Quote tweet"],
    },
}

TONES = ["Friendly", "Professional", "Funny", "Inspirational", "Educational"]

# Words that make unverifiable or risky promises. The Reviewer flags them.
RISKY_WORDS = [
    "guaranteed", "100% guaranteed", "miracle", "cure", "get rich", "risk-free",
    "no side effects", "doctors recommend", "proven to", "overnight success",
]

MAX_RETRIES = 2

# --------------------------------------------------------------------------
# Logger - records what each agent did (shown in the UI and used in the demo)
# --------------------------------------------------------------------------


class Logger:
    def __init__(self, on_event=None):
        self.entries = []
        self.on_event = on_event  # optional callback, e.g. to update Streamlit live

    def __call__(self, agent, message):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {agent}: {message}"
        self.entries.append(line)
        if self.on_event:
            self.on_event(line)


# --------------------------------------------------------------------------
# LLM wrapper (Gemini). Imported lazily so the project runs without the SDK
# in demo mode.
# --------------------------------------------------------------------------


def _parse_json(text):
    """Turn the model's reply into Python data, tolerating ```json fences."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\[.*\]|\{.*\})", text, re.S)
        if match:
            return json.loads(match.group(1))
        raise


class LLM:
    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.demo = not self.api_key
        self._client = None

    @property
    def mode(self):
        return "Demo mode (no API key)" if self.demo else f"Live: Gemini ({self.model})"

    def ask_json(self, prompt):
        """Send a prompt and return parsed JSON. Raises on any failure."""
        from google import genai
        from google.genai import types

        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        response = self._client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", temperature=0.8
            ),
        )
        return _parse_json(response.text)


def _with_fallback(log, agent, llm, llm_fn, fallback_fn):
    """Try the LLM version of an agent; if it fails, use the template version."""
    if llm.demo:
        log(agent, "no API key, using built-in template generator (demo mode)")
        return fallback_fn()
    try:
        return llm_fn()
    except Exception as exc:  # network error, quota, bad JSON ...
        log(agent, f"LLM call failed ({type(exc).__name__}); using template fallback")
        return fallback_fn()


# --------------------------------------------------------------------------
# Agent 1: Research Agent - turns topic + audience into content themes
# --------------------------------------------------------------------------


def research_agent(inp, llm, log):
    topic, audience = inp["topic"], inp["audience"]
    log("Research Agent", f"finding content themes for '{topic}' (audience: {audience})")

    def with_llm():
        prompt = f"""You are a social media strategist.
Topic: {topic}
Target audience: {audience}
Platform: {inp['platform']}
Tone: {inp['tone']}

Suggest 6 distinct content themes for a content calendar.
Return ONLY JSON: a list of objects with keys "theme" (short name) and "angle"
(one sentence on how to approach it for this audience)."""
        themes = llm.ask_json(prompt)
        if not isinstance(themes, list) or not themes:
            raise ValueError("bad themes")
        return themes

    def fallback():
        return [
            {"theme": "Beginner tips", "angle": f"Simple first steps in {topic} for {audience}."},
            {"theme": "Common mistakes", "angle": f"Mistakes {audience} make with {topic}, and fixes."},
            {"theme": "Myths vs facts", "angle": f"Clearing up popular myths about {topic}."},
            {"theme": "Behind the scenes", "angle": f"A real look at how {topic} works day to day."},
            {"theme": "Quick wins", "angle": f"Small actions {audience} can take today in {topic}."},
            {"theme": "Community Q&A", "angle": f"Answering questions {audience} ask about {topic}."},
        ]

    themes = _with_fallback(log, "Research Agent", llm, with_llm, fallback)
    log("Research Agent", f"produced {len(themes)} themes -> sending to Planner Agent")
    return themes


# --------------------------------------------------------------------------
# Agent 2: Planner Agent - builds the calendar (dates, post types, themes)
# --------------------------------------------------------------------------

# Which weekdays to post on, by posts per week (0 = Monday)
_WEEKDAY_PATTERN = {
    1: [2],
    2: [1, 4],
    3: [0, 2, 4],
    4: [0, 1, 3, 4],
    5: [0, 1, 2, 3, 4],
    6: [0, 1, 2, 3, 4, 5],
    7: [0, 1, 2, 3, 4, 5, 6],
}


def make_dates(start, days, posts_per_week):
    """Python (not the LLM) computes the dates, so scheduling is always correct."""
    pattern = _WEEKDAY_PATTERN[posts_per_week]
    dates = []
    for offset in range(days):
        d = start + timedelta(days=offset)
        if d.weekday() in pattern:
            dates.append(d)
    return dates


def planner_agent(inp, themes, llm, log):
    start = inp["start_date"]
    dates = make_dates(start, inp["days"], inp["posts_per_week"])
    types = PLATFORM_RULES[inp["platform"]]["post_types"]
    log("Planner Agent", f"{len(dates)} posting slots between {dates[0]} and {dates[-1]}"
        if dates else "no posting slots in the chosen range")
    if not dates:
        return []

    def with_llm():
        slots = [d.strftime("%a %d %b") for d in dates]
        prompt = f"""You are planning a content calendar for {inp['platform']}.
Themes: {json.dumps(themes)}
Available post types: {types}
Posting slots (in order): {slots}

Assign ONE theme, ONE post type and a short post idea (max 12 words) to every slot.
Rotate themes and post types so the calendar feels varied; do not repeat an idea.
Return ONLY JSON: a list with exactly {len(slots)} objects with keys
"theme", "post_type", "idea" (in the same order as the slots)."""
        plan = llm.ask_json(prompt)
        if not isinstance(plan, list) or len(plan) != len(dates):
            raise ValueError("planner returned wrong number of slots")
        return plan

    def fallback():
        plan = []
        for i in range(len(dates)):
            t = themes[i % len(themes)]
            plan.append({
                "theme": t["theme"],
                "post_type": types[i % len(types)],
                "idea": f"{t['theme']}: {t['angle']}",
            })
        return plan

    plan = _with_fallback(log, "Planner Agent", llm, with_llm, fallback)
    calendar = []
    for d, item in zip(dates, plan):
        calendar.append({
            "date": d.isoformat(),
            "day": d.strftime("%A"),
            "theme": item.get("theme", ""),
            "post_type": item.get("post_type", types[0]),
            "idea": item.get("idea", ""),
        })
    log("Planner Agent", f"calendar ready with {len(calendar)} entries -> sending to Writer Agent")
    return calendar


# --------------------------------------------------------------------------
# Agent 3: Writer Agent - writes caption + hashtags + call-to-action
# --------------------------------------------------------------------------

_HOOKS = {
    "Friendly": ["Hey friends!", "Quick one for you:", "Ever wondered about this?", "Let's talk about it:"],
    "Professional": ["Key insight:", "Worth noting:", "A practical perspective:", "Here is what matters:"],
    "Funny": ["Plot twist:", "Be honest, we have all done this:", "Nobody warned us about this:", "Tiny confession:"],
    "Inspirational": ["Every big result starts small.", "Start where you are.", "Progress beats perfection.", "Your next step matters."],
    "Educational": ["Did you know?", "Quick lesson:", "Let's break it down:", "Learn this in 30 seconds:"],
}
_CTAS = ["Save this for later.", "Share it with a friend who needs it.",
         "Tell us what you think in the comments.", "Follow for more.", "Which tip will you try first?"]


def _tag(word):
    return "#" + re.sub(r"[^A-Za-z0-9]", "", word.title())


def _fallback_post(inp, entry, index):
    """Template writer, deliberately simple. It writes 5 hashtags on every
    platform; the Reviewer will trim them where the platform allows fewer."""
    tone = inp["tone"]
    hook = _HOOKS.get(tone, _HOOKS["Friendly"])[index % 4]
    cta = _CTAS[index % len(_CTAS)]
    bodies = [
        "{hook} {idea} Made for {audience} who want to get better at {topic}. {cta}",
        "{hook} Today's focus for {audience}: {idea} Small steps in {topic} add up. {cta}",
        "{idea} {hook} If you are into {topic}, this one is worth a minute of your time. {cta}",
        "{hook} Thinking about {topic}? {idea} We built this with {audience} in mind. {cta}",
        "{hook} {audience}, here is your {topic} update. {idea} {cta}",
    ]
    caption = bodies[index % len(bodies)].format(
        hook=hook, idea=entry["idea"], audience=inp["audience"], topic=inp["topic"], cta=cta)
    words = [w for w in re.split(r"\W+", inp["topic"]) if len(w) > 2][:2]
    tags = [_tag(w) for w in words] + [_tag(entry["theme"].split()[0]), "#Tips", "#Learn"]
    seen, tags_unique = set(), []
    for t in tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            tags_unique.append(t)
    return {"caption": caption, "hashtags": tags_unique[:5], "cta": cta}


def writer_agent(inp, calendar, llm, log, only_indices=None, issues_by_index=None):
    """Write posts for the whole calendar, or rewrite only `only_indices`
    using the Reviewer's feedback (`issues_by_index`)."""
    rules = PLATFORM_RULES[inp["platform"]]
    indices = list(range(len(calendar))) if only_indices is None else list(only_indices)
    action = "writing" if only_indices is None else "rewriting"
    log("Writer Agent", f"{action} {len(indices)} post(s) in a {inp['tone'].lower()} tone for {inp['platform']}")

    def with_llm():
        items = []
        for i in indices:
            e = calendar[i]
            item = {"index": i, "theme": e["theme"], "post_type": e["post_type"], "idea": e["idea"]}
            if issues_by_index and i in issues_by_index:
                item["fix_these_problems"] = issues_by_index[i]
            items.append(item)
        prompt = f"""You are a social media copywriter.
Platform: {inp['platform']} (max {rules['max_chars']} characters INCLUDING hashtags, max {rules['max_hashtags']} hashtags)
Topic: {inp['topic']}
Audience: {inp['audience']}
Tone: {inp['tone']}

Write one post for each item below. Rules: no false promises or made-up statistics;
add a clear call-to-action; make every post different.
Items: {json.dumps(items)}

Return ONLY JSON: a list of objects with keys "index" (same as input),
"caption" (text without hashtags), "hashtags" (list of strings starting with #),
"cta" (the call-to-action sentence used in the caption)."""
        result = llm.ask_json(prompt)
        by_index = {int(r["index"]): r for r in result}
        if set(by_index) != set(indices):
            raise ValueError("writer returned wrong items")
        return by_index

    def fallback():
        by_index = {}
        # when a single post is regenerated, vary the wording so it looks different
        shift = random.randint(1, 3) if (only_indices is not None and not issues_by_index) else 0
        for i in indices:
            by_index[i] = _fallback_post(inp, calendar[i], i + shift)
            if only_indices is not None:
                # repair so rewritten posts respect platform limits (loop converges in demo mode)
                by_index[i] = _repair_post(by_index[i], rules)
        return by_index

    by_index = _with_fallback(log, "Writer Agent", llm, with_llm, fallback)
    return by_index


def _repair_post(post, rules):
    """Simple automatic fixes used by the template writer."""
    post = dict(post)
    post["hashtags"] = post["hashtags"][: rules["max_hashtags"]]
    for word in RISKY_WORDS:
        post["caption"] = re.sub(word, "helpful", post["caption"], flags=re.I)
    return post


# --------------------------------------------------------------------------
# Agent 4: Reviewer Agent - checks every post against platform + safety rules
# --------------------------------------------------------------------------


def _full_text(post):
    return (post["caption"] + " " + " ".join(post["hashtags"])).strip()


def review_posts(inp, posts):
    """Return {index: [list of problems]} for posts that fail a check."""
    rules = PLATFORM_RULES[inp["platform"]]
    problems = {}

    def add(i, msg):
        problems.setdefault(i, []).append(msg)

    for i, post in enumerate(posts):
        text = _full_text(post)
        if not post["caption"].strip():
            add(i, "caption is empty")
        if len(text) > rules["max_chars"]:
            add(i, f"too long: {len(text)} characters, limit is {rules['max_chars']}")
        if len(post["hashtags"]) > rules["max_hashtags"]:
            add(i, f"too many hashtags: {len(post['hashtags'])}, limit is {rules['max_hashtags']}")
        for word in RISKY_WORDS:
            if re.search(word, text, re.I):
                add(i, f"contains risky/unverifiable claim wording: '{word}'")
        if "http" in text.lower() and "example" in text.lower():
            add(i, "contains a placeholder link")

    # duplicate-idea check: captions that are nearly identical
    for i in range(len(posts)):
        for j in range(i + 1, len(posts)):
            ratio = difflib.SequenceMatcher(None, posts[i]["caption"], posts[j]["caption"]).ratio()
            if ratio > 0.85:
                add(j, f"too similar to post {i + 1} (similarity {ratio:.0%})")
    return problems


def reviewer_loop(inp, calendar, posts, llm, log):
    """Review -> send failures back to the Writer -> review again (max 2 retries)."""
    initial_problems = review_posts(inp, posts)
    log("Reviewer Agent", f"checked {len(posts)} posts, {len(initial_problems)} need fixing")
    problems = initial_problems
    attempt = 0
    while problems and attempt < MAX_RETRIES:
        attempt += 1
        for i, msgs in problems.items():
            log("Reviewer Agent", f"post {i + 1} flagged: " + "; ".join(msgs))
        log("Reviewer Agent", f"sending {len(problems)} post(s) back to Writer Agent (retry {attempt}/{MAX_RETRIES})")
        fixed = writer_agent(inp, calendar, llm, log, only_indices=list(problems), issues_by_index=problems)
        for i, new in fixed.items():
            posts[i] = {"caption": new["caption"], "hashtags": list(new["hashtags"]), "cta": new.get("cta", "")}
        problems = review_posts(inp, posts)
        log("Reviewer Agent", f"re-checked: {len(problems)} post(s) still failing")
    status = "all posts passed review" if not problems else f"{len(problems)} post(s) still need human attention"
    log("Reviewer Agent", status + " -> sending to human for approval")
    return posts, problems, len(initial_problems)


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------


def validate_input(inp):
    errors = []
    if not inp.get("topic", "").strip():
        errors.append("Please enter a topic.")
    if not inp.get("audience", "").strip():
        errors.append("Please enter a target audience.")
    if inp.get("platform") not in PLATFORM_RULES:
        errors.append("Unsupported platform.")
    if not 1 <= inp.get("days", 0) <= 60:
        errors.append("Days must be between 1 and 60.")
    if inp.get("posts_per_week") not in _WEEKDAY_PATTERN:
        errors.append("Posts per week must be between 1 and 7.")
    return errors


def run_pipeline(inp, llm, log=None):
    """Run all four agents. Returns a dict with the final plan and statistics."""
    log = log or Logger()
    errors = validate_input(inp)
    if errors:
        return {"ok": False, "errors": errors, "log": log.entries}

    started = time.time()
    themes = research_agent(inp, llm, log)
    calendar = planner_agent(inp, themes, llm, log)
    if not calendar:
        return {"ok": False, "errors": ["No posting days fall inside the chosen range. "
                                        "Increase the number of days or posts per week."],
                "log": log.entries}

    written = writer_agent(inp, calendar, llm, log)
    posts = [
        {"caption": written[i]["caption"], "hashtags": list(written[i]["hashtags"]),
         "cta": written[i].get("cta", "")}
        for i in range(len(calendar))
    ]
    posts, remaining, initial_failures = reviewer_loop(inp, calendar, posts, llm, log)

    rows = []
    for i, (entry, post) in enumerate(zip(calendar, posts)):
        rows.append({
            **entry,
            "caption": post["caption"],
            "hashtags": " ".join(post["hashtags"]),
            "review": "needs attention: " + "; ".join(remaining[i]) if i in remaining else "passed",
        })
    elapsed = round(time.time() - started, 2)
    log("Pipeline", f"finished in {elapsed}s")
    return {
        "ok": True,
        "inputs": {**inp, "start_date": inp["start_date"].isoformat()},
        "themes": themes,
        "posts": rows,
        "initial_failures": initial_failures,
        "remaining_failures": len(remaining),
        "seconds": elapsed,
        "mode": llm.mode,
        "log": log.entries,
    }
