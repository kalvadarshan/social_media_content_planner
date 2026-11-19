"""
app.py - Streamlit interface for the AI Social Media Content Planner.
Run with:  streamlit run app.py
"""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

import db
from agents import (LLM, PLATFORM_RULES, TONES, Logger, run_pipeline, writer_agent)

st.set_page_config(page_title="AI Social Media Content Planner", page_icon="📅", layout="wide")
db.init_db()

# ------------------------------------------------------------------ sidebar
st.sidebar.header("Settings")
try:
    secret_key = st.secrets.get("GEMINI_API_KEY", "")
except Exception:
    secret_key = ""

typed_key = st.sidebar.text_input("Gemini API key (optional)", type="password",
                                  help="Leave empty to use the saved key, or demo mode if none is set.")
api_key = typed_key or secret_key
model = st.sidebar.text_input("Gemini model", value="gemini-2.5-flash")
llm = LLM(api_key=api_key or None, model=model)
st.sidebar.info(f"Mode: **{llm.mode}**")
st.sidebar.caption("Course 25CS2306 | Foundations of AI and Authentic Intelligence")

# ------------------------------------------------------------------ header
st.title("📅 AI Social Media Content Planner")
st.warning("All content here is **AI-generated draft material**. Review, edit and approve it "
           "before posting. This tool never posts to social media by itself.")

tab_create, tab_saved = st.tabs(["Create plan", "Saved plans"])


# ------------------------------------------------------------------ helpers
def regenerate(i):
    """Callback: ask the Writer Agent to rewrite one post."""
    res = st.session_state["result"]
    inp = {**res["inputs"], "start_date": date.fromisoformat(res["inputs"]["start_date"])}
    calendar = [{k: p[k] for k in ("date", "day", "theme", "post_type", "idea")} for p in res["posts"]]
    log = Logger()
    new = writer_agent(inp, calendar, llm, log, only_indices=[i])[i]
    st.session_state[f"cap_{i}"] = new["caption"]
    st.session_state[f"tags_{i}"] = " ".join(new["hashtags"])


def current_posts(res):
    """Posts including any edits the human made in the text boxes."""
    out = []
    for i, p in enumerate(res["posts"]):
        q = dict(p)
        q["caption"] = st.session_state.get(f"cap_{i}", p["caption"])
        q["hashtags"] = st.session_state.get(f"tags_{i}", p["hashtags"])
        out.append(q)
    return out


# ------------------------------------------------------------------ create tab
with tab_create:
    with st.form("input_form"):
        c1, c2 = st.columns(2)
        topic = c1.text_input("Topic", placeholder="e.g. Healthy eating on a student budget")
        audience = c2.text_input("Target audience", placeholder="e.g. college students")
        c3, c4, c5 = st.columns(3)
        platform = c3.selectbox("Platform", list(PLATFORM_RULES))
        tone = c4.selectbox("Tone", TONES)
        start = c5.date_input("Start date", value=date.today() + timedelta(days=1))
        c6, c7 = st.columns(2)
        days = c6.slider("Plan length (days)", 1, 30, 14)
        per_week = c7.slider("Posts per week", 1, 7, 3)
        submitted = st.form_submit_button("Generate content plan", type="primary")

    if submitted:
        inp = {"topic": topic, "audience": audience, "platform": platform, "tone": tone,
               "days": days, "posts_per_week": per_week, "start_date": start}
        for key in [k for k in st.session_state if k.startswith(("cap_", "tags_"))]:
            del st.session_state[key]
        with st.status("Agents are working...", expanded=True) as status:
            area = st.empty()
            lines = []

            def show(line):
                lines.append(line)
                area.code("\n".join(lines), language=None)

            result = run_pipeline(inp, llm, Logger(on_event=show))
            if result["ok"]:
                status.update(label="Plan ready for review", state="complete")
            else:
                status.update(label="Could not generate a plan", state="error")
        if result["ok"]:
            st.session_state["result"] = result
        else:
            st.session_state.pop("result", None)
            for err in result["errors"]:
                st.error(err)

    res = st.session_state.get("result")
    if res:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Posts planned", len(res["posts"]))
        m2.metric("Fixed by Reviewer loop", res["initial_failures"] - res["remaining_failures"])
        m3.metric("Still need attention", res["remaining_failures"])
        m4.metric("Time (seconds)", res["seconds"])

        st.subheader("Content calendar")
        df = pd.DataFrame(current_posts(res))[["date", "day", "post_type", "theme", "idea", "review"]]
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.subheader("Draft posts (edit anything you like)")
        for i, p in enumerate(res["posts"]):
            flag = "✅" if p["review"] == "passed" else "⚠️"
            st.session_state.setdefault(f"cap_{i}", p["caption"])
            st.session_state.setdefault(f"tags_{i}", p["hashtags"])
            with st.expander(f"{flag} {p['date']} ({p['day']}) | {p['post_type']} | {p['theme']}"):
                st.text_area("Caption", key=f"cap_{i}", height=120)
                st.text_input("Hashtags", key=f"tags_{i}")
                if p["review"] != "passed":
                    st.warning(p["review"])
                st.button("Regenerate this post", key=f"regen_{i}", on_click=regenerate, args=(i,))

        with st.expander("Agent log (how the agents coordinated)"):
            st.code("\n".join(res["log"]), language=None)

        st.subheader("Human approval")
        approve = st.checkbox("I have reviewed these drafts and approve them")
        a1, a2 = st.columns(2)
        if a1.button("Save approved plan", disabled=not approve, type="primary"):
            plan_id = db.save_plan(res["inputs"], current_posts(res), status="approved")
            st.success(f"Saved as plan #{plan_id}. See the 'Saved plans' tab.")
        csv = pd.DataFrame(current_posts(res)).to_csv(index=False).encode("utf-8")
        a2.download_button("Download as CSV", csv, "content_plan.csv", "text/csv")

# ------------------------------------------------------------------ saved tab
with tab_saved:
    plans = db.list_plans()
    if not plans:
        st.info("No saved plans yet. Generate and approve one in the first tab.")
    else:
        st.dataframe(pd.DataFrame(plans), use_container_width=True, hide_index=True)
        choice = st.selectbox("Open a saved plan", [p["id"] for p in plans])
        plan = db.get_plan(choice)
        if plan:
            st.caption(f"{plan['topic']} | {plan['platform']} | {plan['tone']} | {plan['status']}")
            st.dataframe(pd.DataFrame(plan["posts"]), use_container_width=True, hide_index=True)
