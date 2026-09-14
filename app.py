from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from src.catalog import (
    HCM_LANDING_URL,
    discover_human_resources_links,
    discover_readiness_links,
    resolve_human_resources_links,
)
from src.fusion_report import DEFAULT_REPORT_FILE, load_implemented_modules
from src.pipeline import process_urls

load_dotenv()

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def main() -> None:
    st.set_page_config(page_title="HCM Readiness Extractor", layout="wide")
    st.title("Oracle HCM Readiness Extractor")
    st.caption(
        "Generate Word and PowerPoint from implemented Fusion modules, "
        "or pick What's New books from the "
        f"[HCM readiness page]({HCM_LANDING_URL})."
    )

    st.session_state.setdefault("results", [])
    st.session_state.setdefault("generate_urls", [])
    st.session_state.setdefault("modules", [])
    st.session_state.setdefault("report_path", None)
    st.session_state.setdefault("report_error", "")
    st.session_state.setdefault("catalog", [])
    st.session_state.setdefault("landing_url", HCM_LANDING_URL)

    env_user = (os.getenv("FUSION_USERNAME") or "").strip()
    default_user = "" if env_user.startswith("http") else env_user

    if not st.session_state.catalog:
        with st.spinner("Loading the Human Resources list..."):
            st.session_state.catalog = _load_catalog(st.session_state.landing_url)

    left, right = st.columns([1.35, 1])
    with right:
        st.subheader("Generate documents")
        st.write("Each selected What's New book produces its own Word file and PowerPoint file.")
        use_ai = st.checkbox(
            "Use AI for a client-ready PPT",
            value=False,
            help="Tries keys in this order: ANTHROPIC_API_KEY, then OPENAI_API_KEY, then GROQ_API_KEY. Uses the first that works. Without a working key, the tool still builds a briefing from the page text.",
        )
        st.caption("Writes a short, precise PPT summary. The Word file stays the full document.")
        include_images = st.checkbox("Include screenshots in the Word document", value=True)
        st.caption("Adds screenshots to the Word file only. It does not change the PowerPoint.")

    with left:
        implemented_tab, catalog_tab = st.tabs(
            ["Implemented modules", "HCM readiness catalog"]
        )
        with implemented_tab:
            _implemented_tab(default_user)
        with catalog_tab:
            _catalog_tab()

    if st.session_state.generate_urls:
        urls = list(st.session_state.generate_urls)
        st.session_state.generate_urls = []
        st.session_state.results = _run(urls, use_ai, include_images)

    _show_results()


def _implemented_tab(default_user: str) -> None:
    st.subheader("Implemented modules")
    if not st.session_state.modules:
        _load_or_prompt(default_user)
        if not st.session_state.modules:
            return

    modules = st.session_state.modules
    matched = [item for item in modules if item.catalog_item]
    unmatched = [item.module_name for item in modules if not item.catalog_item]
    report_name = Path(st.session_state.report_path).name if st.session_state.report_path else DEFAULT_REPORT_FILE
    st.caption(f"Downloaded `{report_name}` from Fusion BI Publisher.")
    if st.button("Refresh report", icon=":material/refresh:"):
        st.session_state.modules = []
        st.session_state.report_path = None
        st.rerun()
    if unmatched:
        st.warning("No What's New book was found for: " + ", ".join(unmatched))
    if not matched:
        st.error("None of the MODULE_NAME values matched a readiness book.")
        return
    for item in matched:
        book = item.catalog_item
        st.link_button(
            f"{item.module_name} · {book.title}",
            book.url,
            icon=":material/open_in_new:",
        )
    if st.button("Generate Word + PowerPoint for all modules", type="primary"):
        st.session_state.generate_urls = [item.catalog_item.url for item in matched]
        st.rerun()


def _catalog_tab() -> None:
    st.subheader("Human Resources")
    st.caption("Books are loaded from this readiness landing page. You can edit only this URL.")
    with st.form("landing_url_form"):
        landing_url = st.text_input(
            "HCM readiness URL",
            value=st.session_state.landing_url,
            help="Default is the Oracle HCM Cloud Applications Readiness page.",
        )
        applied = st.form_submit_button("Load books", icon=":material/edit:")
    if applied:
        url = landing_url.strip() or HCM_LANDING_URL
        try:
            catalog = _load_catalog(url)
        except Exception as exc:
            st.error(f"Could not load books from that URL: {exc}")
            return
        if not catalog:
            st.error("No What's New books were found at that URL.")
            return
        st.session_state.landing_url = url
        st.session_state.catalog = catalog
        st.rerun()

    st.caption(f"Current list: {st.session_state.landing_url}")
    titles = [item.title for item in st.session_state.catalog]
    if not titles:
        st.error("No Human Resources links were found on the landing page.")
    selected = st.multiselect(
        "Select one or more links",
        options=titles,
        help="These are the books listed on the readiness URL above.",
    )
    if st.button("Generate Word + PowerPoint", type="primary"):
        if not selected:
            st.warning("Select at least one Human Resources link.")
            return
        try:
            items = resolve_human_resources_links(selected, catalog=st.session_state.catalog)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.session_state.generate_urls = [item.url for item in items]
        st.rerun()


def _load_catalog(landing_url: str):
    items = discover_human_resources_links(landing_url=landing_url)
    if items:
        return items
    return discover_readiness_links(landing_url=landing_url, category=None)


def _load_or_prompt(default_user: str) -> None:
    env_password = (os.getenv("FUSION_PASSWORD") or "").strip()
    if default_user and env_password and not st.session_state.report_error:
        try:
            modules, report_path = load_implemented_modules(
                OUTPUT_DIR,
                username=default_user,
                password=env_password,
            )
        except Exception as exc:
            st.session_state.report_error = str(exc)
        else:
            st.session_state.modules = modules
            st.session_state.report_path = str(report_path)
            st.session_state.report_error = ""
            return

    st.write(
        "The app can also open the Module Implemented report on "
        "[ehzq-test](https://ehzq-test.fa.us2.oraclecloud.com) and download "
        f"`{DEFAULT_REPORT_FILE}`."
    )
    if st.session_state.report_error:
        st.error(st.session_state.report_error)
    with st.form("fusion_login"):
        username = st.text_input(
            "Fusion username",
            value=default_user,
            help="Use the Fusion login user, such as john.doe. Do not use the environment URL.",
        )
        password = st.text_input("Fusion password", type="password")
        submitted = st.form_submit_button("Download Module Implemented report")
    if not submitted:
        return
    try:
        modules, report_path = load_implemented_modules(
            OUTPUT_DIR,
            username=username,
            password=password or env_password,
        )
    except Exception as exc:
        st.session_state.report_error = str(exc)
        st.rerun()
    else:
        st.session_state.modules = modules
        st.session_state.report_path = str(report_path)
        st.session_state.report_error = ""
        st.rerun()


def _show_results() -> None:
    if not st.session_state.results:
        return
    st.subheader("Generated files")
    for result in st.session_state.results:
        st.markdown(f"**{result.title}**")
        st.caption(f"{result.topic_count} topics  ·  {result.source_url}")
        if result.ai_note:
            if result.used_ai:
                st.success(result.ai_note)
            else:
                st.info(result.ai_note)
        if result.errors:
            st.warning(f"{len(result.errors)} topic(s) could not be downloaded.")
        doc_col, ppt_col = st.columns(2)
        with doc_col:
            st.download_button(
                label=f"Download Word: {result.docx_path.name}",
                data=result.docx_path.read_bytes(),
                file_name=result.docx_path.name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"doc-{result.docx_path.name}",
            )
        with ppt_col:
            st.download_button(
                label=f"Download PPT: {result.pptx_path.name}",
                data=result.pptx_path.read_bytes(),
                file_name=result.pptx_path.name,
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                key=f"ppt-{result.pptx_path.name}",
            )


def _run(urls: list[str], use_ai: bool, include_images: bool):
    status = st.empty()
    bar = st.progress(0)

    def progress(title: str, url: str, current: int, total: int) -> None:
        status.write(title)
        if total:
            bar.progress(min(current / total, 1.0), text=f"{current}/{total} topics")

    results = process_urls(
        urls,
        output_dir=OUTPUT_DIR,
        use_ai=use_ai,
        include_images=include_images,
        progress=progress,
    )
    bar.progress(1.0, text="Done")
    status.write("Generation complete.")
    return results


if __name__ == "__main__":
    main()
