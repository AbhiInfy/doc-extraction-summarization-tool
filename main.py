from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from src.catalog import discover_readiness_links, resolve_human_resources_links
from src.pillars import PILLARS, get_pillar
from src.pipeline import process_urls


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description=(
            "Extract Oracle Cloud readiness trees into a Word document and a "
            "PowerPoint summary. Supports HCM, Finance, and SCM. One DOC and one PPT per URL."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)
    pillar_help = "Cloud application: HCM, Finance, or SCM. Sets the default readiness landing page."

    discover = sub.add_parser("discover", help="List What's New books from the selected readiness page")
    discover.add_argument("--pillar", default="HCM", choices=list(PILLARS), help=pillar_help)
    discover.add_argument("--landing", default=None, help="Override the readiness landing URL")

    generate = sub.add_parser(
        "generate",
        help="Crawl selected What's New books and write DOC + PPT files",
    )
    generate.add_argument("--pillar", default="HCM", choices=list(PILLARS), help=pillar_help)
    generate.add_argument(
        "--link",
        action="append",
        default=[],
        help='What\'s New book name, e.g. "Financials What\'s New 26D". Repeat for multiple.',
    )
    generate.add_argument("--url", action="append", default=[], help="What's New URL. Repeat for multiple.")
    generate.add_argument("--from-catalog", action="store_true", help="Use every What's New book on the landing page")
    generate.add_argument("--landing", default=None, help="Override the readiness landing URL")
    generate.add_argument("--output", default="output", help="Output folder")
    generate.add_argument("--no-ai", action="store_true", help="Skip Claude/OpenAI/Groq and use extractive PPT bullets")
    generate.add_argument("--no-images", action="store_true", help="Do not embed screenshots in Word")

    args = parser.parse_args()
    landing = args.landing or get_pillar(args.pillar).landing_url
    if args.command == "discover":
        _discover(landing, args.pillar)
        return
    catalog = discover_readiness_links(landing_url=landing, category=None)
    selections = list(args.link) + list(args.url)
    if args.from_catalog:
        urls = [item.url for item in catalog]
    elif selections:
        try:
            urls = [item.url for item in resolve_human_resources_links(selections, catalog=catalog)]
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    else:
        urls = []
    urls = _unique(urls)
    if not urls:
        raise SystemExit(
            'Provide --link "Financials What\'s New 26D", --url, or --from-catalog.'
        )
    results = process_urls(
        urls,
        output_dir=Path(args.output),
        use_ai=not args.no_ai,
        include_images=not args.no_images,
        progress=_cli_progress,
    )
    for result in results:
        print(f"\n{result.title}")
        print(f"  Topics: {result.topic_count}")
        print(f"  Word:   {result.docx_path}")
        print(f"  PPT:    {result.pptx_path}")
        if result.errors:
            print(f"  Warnings: {len(result.errors)} topic(s) failed")


def _discover(landing: str, pillar: str) -> None:
    items = discover_readiness_links(landing_url=landing, category=None)
    if not items:
        raise SystemExit("No What's New books found.")
    print(f"{pillar} books from {landing}\n")
    for index, item in enumerate(items, start=1):
        print(f"{index}. {item.title}")
        print(f"   {item.url}")


def _cli_progress(title: str, url: str, current: int, total: int) -> None:
    if total:
        print(f"[{current}/{total}] {title}")
    else:
        print(title)


def _unique(urls: list[str]) -> list[str]:
    seen = []
    for url in urls:
        url = url.strip()
        if url and url not in seen:
            seen.append(url)
    return seen


if __name__ == "__main__":
    main()
