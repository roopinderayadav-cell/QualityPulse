# QualityPulse – Quality Audit demo (Ops Suite)

Part of the Ops Suite: OpsPulse (performance) · OpsMate (knowledge) · QualityPulse (quality).
ALL people, PNRs and audits in this demo are SYNTHETIC.

## What it does
- QA admin builds an audit form per process: sections, parameters, weights, FATAL flags, pass mark (versioned).
- Auditor audits a transaction: Yes / No / N/A on every parameter + a free comment box on EVERY parameter
  (required when No, optional praise/tips when Yes) + overall feedback. Live score while auditing.
- System scores it: score = points earned ÷ applicable points × 100; N/A never counts against the agent;
  any fatal parameter answered No = Fail.
- Agent is notified (Inbox) with the full detail: every parameter, answer, points and QA comment.
- Agent acknowledges or disputes (choose parameters + reason). Discussion thread for everyone involved.
- QA admin / team lead upholds or overturns; overturn recalculates the score; every version is kept.
- Unanswered after 48 hours = Overdue. Quality dashboard + Excel export.

## Demo script (switch person in the sidebar)
1. Neha (QA admin) – Quality dashboard, Form builder, Disputes (PNR 9HD3KW is waiting for a decision).
2. Sneha (agent) – fatal-error audit Q7MZP4, already overdue: acknowledge or dispute.
3. Rahul (agent) – 6XK2LQ: full story Fail → dispute → overturned → Pass, plus a fresh 100% audit.
4. Arjun (auditor) – New audit: answer the parameters, add comments, submit; the agent gets it instantly.
QA admin can press "Reset demo data" to start again.

## Deploy (Streamlit Community Cloud)
1. New PRIVATE GitHub repository, e.g. qualitypulse.
2. Add file → Upload files → select ALL files in this folder → Commit.
3. Optional colours: Add file → Create new file → name `.streamlit/config.toml` → paste config.toml → Commit.
4. share.streamlit.io → Create app → this repo, branch main, main file `app.py` → Deploy.
5. Optional Secrets: APP_ACCESS_CODE = "your-own-code"

Note: Streamlit Community Cloud may reset the demo database when the app restarts (the sample data
rebuilds itself). Real customer use needs the Supabase database planned for the full platform.

## Tests
pip install pytest  →  pytest -q
