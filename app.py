from __future__ import annotations

from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from src.catalog import (
    HCM_LANDING_URL,
    discover_human_resources_links,
    resolve_human_resources_links,
)
from src.pipeline import process_urls

load_dotenv()

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def main() -> None:
    st.set_page_config(page_title="HCM Readiness Extractor", layout="wide")
    st.title("Oracle HCM Readiness Extractor")
    st.caption(
        "Pick one or more links from the Human Resources list on the HCM readiness page. "
        "The tool walks every nested topic under each selected link and writes "
        "one Word document plus one PowerPoint summary per link."
    )

    if "catalog" not in st.session_state:
        st.session_state.catalog = []
    if "results" not in st.session_state:
        st.session_state.results = []

    if not st.session_state.catalog:
        with st.spinner("Loading the Human Resources list..."):
            st.session_state.catalog = discover_human_resources_links()

    left, right = st.columns([1.25, 1])
    with left:
        st.subheader("Human Resources")
        st.caption(f"Links from {HCM_LANDING_URL}")
        if st.button("Refresh list"):
            st.session_state.catalog = discover_human_resources_links()

        titles = [item.title for item in st.session_state.catalog]
        if not titles:
            st.error("No Human Resources links were found on the landing page.")
        selected = st.multiselect(
            "Select one or more links",
            options=titles,
            help="These are the same links shown under Human Resources on the Oracle page.",
        )
        extra = st.text_area(
            "Or type link names / URLs (one per line)",
            placeholder="Benefits What's New 26C\nHuman Resources What's New 26C",
            height=100,
        )

    with right:
        st.subheader("Generate documents")
        st.write(
            "Each selected Human Resources link produces its own Word file "
            "and PowerPoint file."
        )
        use_ai = st.checkbox(
            "Use AI for a client-ready PPT",
            value=False,
            help="Tries keys in this order: ANTHROPIC_API_KEY, then OPENAI_API_KEY, then GROQ_API_KEY. Uses the first that works. Without a working key, the tool still builds a briefing from the page text.",
        )
        st.caption("Writes a short, precise PPT summary. The Word file stays the full document.")
        include_images = st.checkbox("Include screenshots in the Word document", value=True)
        st.caption("Adds screenshots to the Word file only. It does not change the PowerPoint.")
        run = st.button("Generate Word + PowerPoint", type="primary")

    selections = list(selected) + [line.strip() for line in extra.splitlines() if line.strip()]
    if run:
        if not selections:
            st.warning("Select or type at least one Human Resources link.")
        else:
            try:
                items = resolve_human_resources_links(selections, catalog=st.session_state.catalog)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state.results = _run(
                    [item.url for item in items],
                    use_ai,
                    include_images,
                )

    if st.session_state.results:
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
