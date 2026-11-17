# AI Social Media Content Planner (Topic 87)
Course: Foundations of AI and Authentic Intelligence (25CS2306), Minor Project

A multi-agent system that turns a topic, audience, platform and schedule into a
content calendar with draft posts. A human reviews and approves everything.
Nothing is ever posted automatically.

## The four agents
| Agent | Job |
|---|---|
| Research Agent | Finds 6 content themes for the topic and audience |
| Planner Agent | Builds the calendar (dates computed in Python; post type and idea per slot) |
| Writer Agent | Writes caption, hashtags and call-to-action for each slot |
| Reviewer Agent | Checks length, hashtags, risky claims, duplicates; sends failures back to the Writer (max 2 retries) |

Flow: User input -> Research -> Planner -> Writer -> Reviewer -> (fix loop) -> Human approval -> SQLite / CSV

## Setup (10 minutes)
1. Install Python 3.10+ from python.org.
2. Open a terminal in this folder and run:
   ```
   pip install -r requirements.txt
   ```
3. Get a free Gemini API key at https://aistudio.google.com/apikey
4. Run the app:
   ```
   streamlit run app.py
   ```
5. Paste the key in the left sidebar, or set it before running:
   - Windows: `set GEMINI_API_KEY=your_key`
   - Mac/Linux: `export GEMINI_API_KEY=your_key`

No key? The app still works in **demo mode** with a built-in template generator
(clearly shown in the sidebar). If a live API call fails, the agent falls back to
the template generator and says so in the log, so your demo never crashes.

If the model name `gemini-2.5-flash` is not available for your key, change it in
the sidebar (or set `GEMINI_MODEL`) to the current Flash model listed in Google AI Studio.

## Files
- `app.py` - Streamlit user interface
- `agents.py` - the four agents + orchestrator (`run_pipeline`)
- `db.py` - SQLite storage (creates `planner.db` automatically)
- `test_cases.py` - 8 test cases, writes `results.csv`

## Testing (for the evaluation slide)
```
python test_cases.py
```
Run it WITH your API key for the final numbers. Copy the task success rate and
average latency into the slide. Also rate 5 generated plans from 1 to 5 yourselves
for "output quality".

## 3-minute demo script
1. Show the sidebar mode (Live: Gemini) and the "AI-generated draft" warning.
2. Enter: Topic "Healthy eating on a student budget", Audience "college students",
   Platform Instagram, Tone Friendly, 14 days, 3 posts per week. Click Generate.
3. Point at the live agent log: Research -> Planner -> Writer -> Reviewer.
4. Show the calendar table, then open one post and edit the caption.
5. Click "Regenerate this post" on one entry.
6. Switch platform to X (Twitter) and generate again: the Reviewer catches too many
   hashtags / long text and sends posts back to the Writer. Show this in the log.
7. Tick the approval box, click Save, download the CSV, open "Saved plans".

Keep a screen recording of a successful run as a backup in case Wi-Fi fails.
