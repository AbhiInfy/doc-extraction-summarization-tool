from __future__ import annotations

import os
import hmac
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from src.catalog import discover_readiness_links, home_pillar, resolve_human_resources_links
from src.fusion_report import load_implemented_modules
from src.http_client import is_connection_drop
from src.pillars import PILLARS, get_pillar
from src.pipeline import process_urls

load_dotenv(override=True)

OUTPUT_DIR = Path(__file__).resolve().parent / "output"



def _password_gate() -> bool:
    """Show the dark authentication screen and return True after login."""
    expected_password = (os.getenv("APP_PASSWORD") or "").strip()

    if not expected_password:
        st.error("APP_PASSWORD is not configured. Please set it in the environment.")
        return False

    st.session_state.setdefault("authenticated", False)

    if st.session_state.authenticated:
        with st.sidebar:
            if st.button("Sign out", icon=":material/logout:"):
                st.session_state.authenticated = False
                st.rerun()
        return True

    st.markdown(
        """
        <style>
        /* ---------- Full authentication page ---------- */
        .stApp {
            background: #080a0f;
        }

        [data-testid="stHeader"] {
            background: transparent;
        }

        [data-testid="stToolbar"] {
            visibility: hidden;
        }

        .block-container {
            max-width: 1180px;
            padding-top: 5.5vh;
            padding-bottom: 5vh;
        }

        /* Keep the auth card centered and compact. */
        [data-testid="stVerticalBlockBorderWrapper"] {
            background: #0d1016;
            border: 1px solid #343944;
            border-radius: 22px;
            box-shadow:
                0 28px 80px rgba(0, 0, 0, 0.48),
                0 0 0 1px rgba(255, 255, 255, 0.015) inset;
            padding: 2.5rem 2.6rem 2.1rem 2.6rem;
        }

        .auth-icon {
            width: 72px;
            height: 72px;
            margin: 0 auto 1.7rem auto;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 17px;
            border: 1px solid #9c2434;
            background: linear-gradient(145deg, #6f1524, #3e0c15);
            color: #ffffff;
            box-shadow: 0 12px 30px rgba(94, 12, 25, 0.25);
        }

        .auth-title {
            margin: 0;
            text-align: center;
            color: #f5f6f8;
            font-size: clamp(2rem, 3.5vw, 2.55rem);
            line-height: 1.15;
            font-weight: 750;
            letter-spacing: -0.035em;
        }

        .auth-subtitle {
            margin: 0.8rem 0 2.35rem 0;
            text-align: center;
            color: #9da5b1;
            font-size: 1.03rem;
            line-height: 1.5;
        }

        [data-testid="stWidgetLabel"] p {
            color: #f0f2f5 !important;
            font-weight: 650 !important;
            font-size: 0.98rem !important;
        }

        /* Password field: dark input with an inline lock icon. */
        [data-testid="stTextInput"] input {
            min-height: 52px !important;
            box-sizing: border-box !important;
            padding-left: 50px !important;
            padding-right: 52px !important;
            background-color: #10131a !important;
            background-repeat: no-repeat !important;
            background-position: 17px 50% !important;
            background-size: 21px 21px !important;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='22' height='22' viewBox='0 0 24 24' fill='none' stroke='%23aeb6c2' stroke-width='1.9' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='4' y='10' width='16' height='11' rx='2'/%3E%3Cpath d='M8 10V7a4 4 0 0 1 8 0v3'/%3E%3C/svg%3E") !important;
            color: #f4f5f7 !important;
            border: 1px solid #454b57 !important;
            border-radius: 12px !important;
            font-size: 1rem !important;
        }

        [data-testid="stTextInput"] input:focus {
            border-color: #68717e !important;
            box-shadow: 0 0 0 1px #68717e !important;
        }

        [data-testid="stTextInput"] input::placeholder {
            color: #707988 !important;
        }

        /* Continue button: full width, compact red accent. */
        [data-testid="stButton"] button {
            width: 100% !important;
            min-height: 52px !important;
            border-radius: 12px !important;
            font-size: 1rem !important;
            font-weight: 700 !important;
        }

        [data-testid="stButton"] button[kind="primary"] {
            background: linear-gradient(90deg, #d7192f, #be1428) !important;
            border: 1px solid #ec3146 !important;
            color: #ffffff !important;
            box-shadow: 0 10px 24px rgba(215, 25, 47, 0.18) !important;
        }

        [data-testid="stButton"] button[kind="primary"]:hover {
            background: linear-gradient(90deg, #e31d35, #cb172b) !important;
            border-color: #f04a5b !important;
            color: #ffffff !important;
        }

        /* Error message stays inside the card without shifting the layout too much. */
        [data-testid="stAlert"] {
            margin-top: 0.75rem !important;
            margin-bottom: 0 !important;
        }

        .auth-footer {
            display: flex;
            align-items: center;
            gap: 16px;
            margin-top: 2rem;
            color: #707987;
            font-size: 0.84rem;
            justify-content: center;
            letter-spacing: 0.01em;
        }

        .auth-footer::before,
        .auth-footer::after {
            content: "";
            height: 1px;
            background: #343944;
            flex: 1;
        }

        @media (max-width: 700px) {
            .block-container {
                padding: 2.5vh 0.9rem 4vh 0.9rem;
            }

            [data-testid="stVerticalBlockBorderWrapper"] {
                padding: 2rem 1.25rem 1.6rem 1.25rem;
                border-radius: 18px;
            }

            .auth-title {
                font-size: 1.75rem;
            }

            .auth-subtitle {
                font-size: 0.95rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # A centered column gives the card the same compact proportions as the reference.
    left, center, right = st.columns([1, 4, 1])
    with center:
        with st.container(border=True):
            st.markdown(
                """
                <div class="auth-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24" width="38" height="38" fill="none"
                         stroke="currentColor" stroke-width="1.75"
                         stroke-linecap="round" stroke-linejoin="round">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                        <path d="M14 2v6h6"/>
                        <path d="M8 13h8"/>
                        <path d="M8 17h6"/>
                    </svg>
                </div>
                <h1 class="auth-title">Oracle Cloud Readiness Extractor</h1>
                <p class="auth-subtitle">Enter the password to access the application.</p>
                """,
                unsafe_allow_html=True,
            )

            password = st.text_input(
                "Password",
                type="password",
                placeholder="Enter password",
                label_visibility="visible",
            )

            submitted = st.button(
                "Continue  →",
                type="primary",
                width="stretch",
            )

            if submitted:
                if hmac.compare_digest(password, expected_password):
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Incorrect password.")

            st.markdown(
                '<div class="auth-footer">Authorized access only</div>',
                unsafe_allow_html=True,
            )

    return False



def main() -> None:
    st.set_page_config(page_title="Oracle Cloud Readiness Extractor", layout="wide")

    if not _password_gate():
        return

    st.session_state.setdefault("results", [])
    st.session_state.setdefault("generate_urls", [])
    st.session_state.setdefault("modules", [])
    st.session_state.setdefault("report_path", None)
    st.session_state.setdefault("report_error", "")
    st.session_state.setdefault("catalog", [])
    st.session_state.setdefault("catalog_error", "")
    st.session_state.setdefault("pillar_key", "HCM")

    st.title("Oracle Cloud Readiness Extractor")
    st.caption(
        "Generate Word and PowerPoint from implemented Fusion modules, "
        "or pick What's New books from the selected readiness catalog."
    )

    pillar = _selected_pillar()
    st.session_state.setdefault("landing_url", pillar.landing_url)

    env_user = (os.getenv("FUSION_USERNAME") or "").strip()
    default_user = "" if env_user.startswith("http") else env_user

    if not st.session_state.catalog and not st.session_state.catalog_error:
        with st.spinner(f"Loading the {pillar.key} readiness list..."):
            try:
                st.session_state.catalog = _load_catalog(st.session_state.landing_url)
                st.session_state.catalog_error = ""
            except Exception as exc:
                if is_connection_drop(exc):
                    st.session_state.catalog_error = (
                        f"The {pillar.key} readiness page closed the connection. "
                        "Wait a few seconds and click Retry catalog."
                    )
                else:
                    st.session_state.catalog_error = str(exc)

    if st.session_state.catalog_error:
        st.warning(st.session_state.catalog_error)
        if st.button("Retry catalog"):
            st.session_state.catalog_error = ""
            st.session_state.catalog = []
            st.rerun()

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
            ["Implemented modules", "Readiness catalog"]
        )
        with implemented_tab:
            _implemented_tab(default_user, pillar)
        with catalog_tab:
            _catalog_tab(pillar)

    if st.session_state.generate_urls:
        urls = list(st.session_state.generate_urls)
        st.session_state.generate_urls = []
        st.session_state.results = _run(urls, use_ai, include_images)

    _show_results()


def _selected_pillar():
    previous = st.session_state.get("active_pillar")
    pillar_key = st.selectbox(
        "Cloud application",
        options=list(PILLARS),
        format_func=lambda key: PILLARS[key].label,
        key="pillar_key",
        help="HCM, Finance, and SCM each use their own Fusion report and readiness catalog.",
    )
    pillar = get_pillar(pillar_key)
    if previous != pillar_key:
        st.session_state.active_pillar = pillar_key
        st.session_state.landing_url = pillar.landing_url
        st.session_state.catalog = []
        st.session_state.catalog_error = ""
        st.session_state.modules = []
        st.session_state.report_path = None
        st.session_state.report_error = ""
        if previous is not None:
            st.rerun()
    return pillar


def _implemented_tab(default_user: str, pillar) -> None:
    st.subheader("Implemented modules")
    st.caption(f"{pillar.label} report: `{pillar.report_path}`")
    if not st.session_state.modules:
        _load_or_prompt(default_user, pillar)
        if not st.session_state.modules:
            return

    modules = [
        item
        for item in st.session_state.modules
        if item.catalog_item or home_pillar(item.module_name) in {None, pillar.key}
    ]
    matched = [item for item in modules if item.catalog_item]
    unknown = [item.module_name for item in modules if not item.catalog_item]
    report_name = Path(st.session_state.report_path).name if st.session_state.report_path else pillar.report_file
    st.caption(f"Downloaded `{report_name}` from Fusion BI Publisher.")
    if st.button("Refresh report", icon=":material/refresh:"):
        st.session_state.modules = []
        st.session_state.report_path = None
        st.session_state.report_error = ""
        st.rerun()
    if unknown:
        st.warning("No What's New book was found for: " + ", ".join(unknown))
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


def _catalog_tab(pillar) -> None:
    st.subheader(f"{pillar.key} What's New books")
    st.caption("Books are loaded from this readiness landing page. You can edit only this URL.")
    with st.form("landing_url_form"):
        landing_url = st.text_input(
            "Readiness URL",
            value=st.session_state.landing_url,
            key=f"landing_url_input_{pillar.key}",
            help="Default follows the selected cloud application: HCM, Finance, or SCM.",
        )
        applied = st.form_submit_button("Load books", icon=":material/edit:")
    if applied:
        url = landing_url.strip() or pillar.landing_url
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
        st.error("No What's New books were found on the landing page.")
    selected = st.multiselect(
        "Select one or more links",
        options=titles,
        help="These are the books listed on the readiness URL above.",
    )
    if st.button("Generate Word + PowerPoint", type="primary"):
        if not selected:
            st.warning("Select at least one What's New book.")
            return
        try:
            items = resolve_human_resources_links(selected, catalog=st.session_state.catalog)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.session_state.generate_urls = [item.url for item in items]
        st.rerun()


def _load_catalog(landing_url: str):
    return discover_readiness_links(landing_url=landing_url, category=None)


def _load_or_prompt(default_user: str, pillar) -> None:
    env_password = (os.getenv("FUSION_PASSWORD") or "").strip()
    if default_user and env_password and not st.session_state.report_error:
        try:
            modules, report_path = load_implemented_modules(
                OUTPUT_DIR,
                username=default_user,
                password=env_password,
                pillar_key=pillar.key,
            )
        except Exception as exc:
            if is_connection_drop(exc):
                st.session_state.report_error = (
                    f"Fusion closed the connection while downloading the {pillar.key} report. "
                    "Wait a few seconds and click Retry."
                )
            else:
                st.session_state.report_error = str(exc)
        else:
            st.session_state.modules = modules
            st.session_state.report_path = str(report_path)
            st.session_state.report_error = ""
            return

    st.write(
        "The app opens the Module Implemented report on "
        "[ehzq-test](https://ehzq-test.fa.us2.oraclecloud.com) and downloads "
        f"`{pillar.report_file}`."
    )
    if st.session_state.report_error:
        st.error(st.session_state.report_error)
        if st.button("Retry"):
            st.session_state.report_error = ""
            st.rerun()
    with st.form("fusion_login"):
        username = st.text_input(
            "Fusion username",
            value=default_user,
            help="Fusion login user, such as Tech_consultant@us.gt.com. Do not paste the environment URL.",
        )
        password = st.text_input(
            "Fusion password",
            type="password",
            help="Leave blank to use FUSION_PASSWORD from .env.",
        )
        submitted = st.form_submit_button("Download Module Implemented report")
    if not submitted:
        return
    try:
        modules, report_path = load_implemented_modules(
            OUTPUT_DIR,
            username=username,
            password=password or env_password,
            pillar_key=pillar.key,
        )
    except Exception as exc:
        if is_connection_drop(exc):
            st.session_state.report_error = (
                f"Fusion closed the connection while downloading the {pillar.key} report. "
                "Wait a few seconds and click Retry."
            )
        else:
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
