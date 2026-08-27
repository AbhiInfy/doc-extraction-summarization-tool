# Oracle HCM Readiness Extractor

Python tool that starts from the [HCM Cloud Applications Readiness](https://docs.oracle.com/en/cloud/saas/readiness/hcm.html) page, follows the nested tree under a Human Resources What's New URL, copies every topic into a Word document with a numbered index, and then writes a PowerPoint summary. **One Word file and one PowerPoint file are created for each URL.**

The Word file is always the full extracted document. The PowerPoint is a short client briefing. AI, if enabled, rewrites PPT wording only.

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
4. It opens every topic page and copies headings, paragraphs, lists, tables, and optional screenshots.
5. It writes a Word document with:
   - a cover page
   - a full index that matches the original tree
   - numbered headings (`1`, `1.1`, `1.1.1`)
   - the full topic content
   - screenshots only if that option is on
6. It writes a **client-ready PowerPoint briefing** of that same URL:
   - title
   - overview of themes
   - Feature | Impact | Action table
   - theme slides (how it works, setup, `ORA_*` profile options)
   - enablement
   - next steps

## Setup

```powershell
cd e:\Knowledge\GenAI\doc-extraction-summarization-tool
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Optional AI wording for the PowerPoint (not the Word file):

```powershell
copy .env.example .env
```

Add keys in this lookup order. The app uses the first that works:

1. `ANTHROPIC_API_KEY` (Claude)
2. `OPENAI_API_KEY`
3. `GROQ_API_KEY` (Groq at console.groq.com; keys start with `gsk_`)

If none work, the PPT is still built from the What's New text (extractive briefing). Keep `.env` local; do not commit it.

Groq's free tier allows 8000 tokens per request. The app keeps the full Oracle source and splits Groq calls to fit that cap. After a Groq Dev Tier upgrade, you can raise `GROQ_TOKEN_LIMIT` in `.env`. With Claude credits or an OpenAI key, the same full-source briefing runs in one pass.

## Run the UI

```powershell
streamlit run app.py
```

1. The **Human Resources** list loads automatically.
2. Select one or more names, such as `Benefits What's New 26C` and `Human Resources What's New 26C`.
3. Optionally turn on **Use AI for a client-ready PPT**. This changes PPT wording only.
4. Optionally turn off **Include screenshots in the Word document**. Screenshots never go into the PowerPoint.
5. Click **Generate Word + PowerPoint**.
6. Download the files. They are also saved under `output/`.

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

Skip AI PPT wording or Word screenshots:

```powershell
python main.py generate --link "Benefits What's New 26C" --no-ai
python main.py generate --link "Benefits What's New 26C" --no-images
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
- A large What's New book can take several minutes because every tree node is opened. Screenshots and Groq's free-tier rate limit add more time.
- The Word index is written as numbered text so it is visible without refreshing Word fields.
