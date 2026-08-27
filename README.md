# Oracle HCM Readiness Extractor

Python tool that starts from the [HCM Cloud Applications Readiness](https://docs.oracle.com/en/cloud/saas/readiness/hcm.html) page, follows the nested tree under a Human Resources What's New URL, copies every topic into a Word document with a numbered index, and then writes a PowerPoint summary. **One Word file and one PowerPoint file are created for each URL.**

## What it does

1. Reads the **Human Resources** list on the HCM readiness landing page, for example:
   - Benefits What's New 26C
   - HCM Common What's New 26C
   - Help Desk What's New 26C
   - Human Resources What's New 26C
   - Work Life What's New 26C
   - Workforce Modeling & Prediction What's New 24B
2. You pass **one or more of those link names** (or their URLs).
3. For each selected link it loads Oracle's `toc.js` tree, including nested folders such as Global Human Resources → Document Records → feature pages.
4. It opens every topic page and copies headings, paragraphs, lists, tables, and screenshots.
5. It writes a Word document with:
   - a cover page
   - a full index that matches the original tree
   - numbered headings (`1`, `1.1`, `1.1.1`)
   - the full topic content
6. It writes a **client-ready PowerPoint briefing** of that same URL:
   - title and agenda
   - release snapshot
   - why it matters
   - themes
   - one slide per feature: what's changing, business value, what the client needs to do
   - recommended actions, discussion questions, and next steps

## Setup

```powershell
cd e:\Knowledge\GenAI\documentationextraction-summarization-tool
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Optional AI wording for the PowerPoint:

```powershell
copy .env.example .env
```

Add keys in this lookup order: `ANTHROPIC_API_KEY` (Claude), then `OPENAI_API_KEY`, then `GROQ_API_KEY` (Groq). The app uses the first that works. If none work, it still builds a briefing from the What's New text.

## Run the UI

```powershell
streamlit run app.py
```

1. The **Human Resources** list loads automatically.
2. Select one or more names, such as `Benefits What's New 26C` and `Human Resources What's New 26C`.
3. Click **Generate Word + PowerPoint**.
4. Download the files. They are also saved under `output/`.

## Run from the command line

List Human Resources books:

```powershell
python main.py discover
```

Generate files for one or more Human Resources links by name:

```powershell
python main.py generate --link "Benefits What's New 26C"
python main.py generate --link "Benefits What's New 26C" --link "Human Resources What's New 26C"
```

You can still pass full URLs if you prefer:

```powershell
python main.py generate --url "https://docs.oracle.com/en/cloud/saas/readiness/hcm/26c/hure-26c/index.html"
```

Generate files for every Human Resources book on the landing page:

```powershell
python main.py generate --from-catalog --no-ai
```

## Example URL

`https://docs.oracle.com/en/cloud/saas/readiness/hcm/26c/hure-26c/index.html`

That book currently includes nested sections such as Human Resources → Global Human Resources → Document Records / Employment / Journeys, plus further child feature pages.

## Notes

- The tool only reads public Oracle Help Center pages and waits briefly between requests.
- A large What's New book can take several minutes because every tree node is opened.
- The Word index is written as numbered text so it is visible without refreshing Word fields.
