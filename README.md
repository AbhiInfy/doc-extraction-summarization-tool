# Oracle Cloud Readiness Extractor

Python tool for Oracle Cloud **HCM**, **Finance (ERP)**, and **SCM**. It starts from the selected readiness landing page, follows the nested tree under a What's New book, copies every topic into a Word document with a numbered index, and then writes a PowerPoint summary. **One Word file and one PowerPoint file are created for each URL.**

The Word file is always the full extracted document. The PowerPoint is a short client briefing. AI, if enabled, rewrites PPT wording only.

## What it does

1. You choose a cloud application in the UI: **HCM**, **Finance**, or **SCM**. That choice picks both the Fusion Module Implemented report and the Oracle readiness catalog:
   - HCM → `/Custom/Module Implemented Report.xdo` and [hcm.html](https://docs.oracle.com/en/cloud/saas/readiness/hcm.html)
   - Finance → `/Custom/Module Implemented Report Finance.xdo` and [erp.html](https://docs.oracle.com/en/cloud/saas/readiness/erp.html)
   - SCM → `/Custom/Module Implemented Report SCM.xdo` and [scm.html](https://docs.oracle.com/en/cloud/saas/readiness/scm.html)
2. **Implemented modules** downloads that report from Fusion BI Publisher and maps each `MODULE_NAME` to a What's New book.
3. **Readiness catalog** lists the books on the selected landing page. You can edit only that landing URL.
4. You generate Word + PowerPoint for the matched modules or for books you pick from the catalog.
5. For each selected link it loads Oracle's `toc.js` tree, including nested folders such as Global Human Resources → Document Records → feature pages.
6. It opens every topic page and copies headings, paragraphs, lists, tables, and optional screenshots.
7. It writes a Word document with:
   - a cover page
   - a full index that matches the original tree
   - numbered headings (`1`, `1.1`, `1.1.1`)
   - the full topic content
   - screenshots only if that option is on
8. It writes a **client-ready PowerPoint briefing** of that same URL:
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

Fusion report download uses `FUSION_BASE_URL`, `FUSION_USERNAME`, and `FUSION_PASSWORD`. Optional report-path overrides:

```
FUSION_BIP_REPORT_PATH=/Custom/Module Implemented Report.xdo
FUSION_BIP_REPORT_PATH_FINANCE=/Custom/Module Implemented Report Finance.xdo
FUSION_BIP_REPORT_PATH_SCM=/Custom/Module Implemented Report SCM.xdo
```

Groq's free tier allows 8000 tokens per request. The app keeps the full Oracle source and splits Groq calls to fit that cap. After a Groq Dev Tier upgrade, you can raise `GROQ_TOKEN_LIMIT` in `.env`. With Claude credits or an OpenAI key, the same full-source briefing runs in one pass.

## Run the UI

```powershell
streamlit run app.py
```

1. Choose **HCM**, **Finance**, or **SCM** from the **Cloud application** dropdown. That selection switches the Fusion report and the readiness catalog.
2. **Implemented modules** downloads the matching Module Implemented report and maps `MODULE_NAME` to What's New books.
3. **Readiness catalog** lists the books from that landing page. You can edit only this main URL.
4. Optionally turn on **Use AI for a client-ready PPT**. This changes PPT wording only.
5. Optionally turn off **Include screenshots in the Word document**. Screenshots never go into the PowerPoint.
6. Generate Word + PowerPoint for all matched modules, or pick books from the catalog.
7. Download the files. They are also saved under `output/`.

## Run from the command line

List What's New books (add `--pillar Finance` or `--pillar SCM` when needed):

```powershell
python main.py discover
python main.py discover --pillar Finance
python main.py discover --pillar SCM
```

Generate files for one or more What's New books by name:

```powershell
python main.py generate --link "Benefits What's New 26C"
python main.py generate --pillar Finance --link "Financials What's New 26D"
python main.py generate --pillar SCM --link "Inventory Management What's New 26D"
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

Generate files for every What's New book on the selected landing page:

```powershell
python main.py generate --from-catalog --no-ai
python main.py generate --pillar Finance --from-catalog --no-ai
```

## Example URL

`https://docs.oracle.com/en/cloud/saas/readiness/hcm/26c/hure-26c/index.html`

That book currently includes nested sections such as Human Resources → Global Human Resources → Document Records / Employment / Journeys, plus further child feature pages.

## Notes

- The tool only reads public Oracle Help Center pages and waits briefly between requests.
- A large What's New book can take several minutes because every tree node is opened. Screenshots and Groq's free-tier rate limit add more time.
- The Word index is written as numbered text so it is visible without refreshing Word fields.
