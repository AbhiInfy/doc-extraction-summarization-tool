from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .crawler import crawl_tree, load_document_tree
from .docx_builder import build_docx, safe_filename
from .http_client import HttpClient
from .models import GenerationResult
from .pptx_builder import build_pptx
from .summarizer import summarize_document

ProgressCallback = Callable[[str, str, int, int], None]


def process_url(
    url: str,
    output_dir: Path,
    use_ai: bool = True,
    include_images: bool = True,
    progress: ProgressCallback | None = None,
    client: HttpClient | None = None,
) -> GenerationResult:
    client = client or HttpClient()
    normalized = url.strip()
    if normalized.rstrip("/").endswith(("hcm.html", "/hcm")):
        raise ValueError(
            "That URL is the HCM landing page. Choose one or more Human Resources "
            "What's New links from it, for example "
            "https://docs.oracle.com/en/cloud/saas/readiness/hcm/26c/hure-26c/index.html"
        )
    if progress:
        progress("Loading table of contents", url, 0, 0)
    tree = load_document_tree(url, client)

    def crawl_progress(title: str, current: int, total: int) -> None:
        if progress:
            progress(title, url, current, total)

    errors = crawl_tree(tree, client, progress=crawl_progress, include_images=include_images)
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = _unique_slug(tree.title, output_dir)
    docx_path = output_dir / f"{slug}.docx"
    pptx_path = output_dir / f"{slug}.pptx"

    if progress:
        progress("Writing Word document", url, 0, 0)
    build_docx(tree, docx_path, client)

    if progress:
        progress("Writing PowerPoint summary", url, 0, 0)
    summary = summarize_document(tree, use_ai=use_ai)
    build_pptx(summary, pptx_path)

    return GenerationResult(
        source_url=url,
        title=tree.title,
        topic_count=sum(1 for node in tree.walk() if node.url),
        docx_path=docx_path,
        pptx_path=pptx_path,
        used_ai=summary.used_ai,
        errors=errors,
    )


def process_urls(
    urls: list[str],
    output_dir: Path,
    use_ai: bool = True,
    include_images: bool = True,
    progress: ProgressCallback | None = None,
) -> list[GenerationResult]:
    client = HttpClient()
    results: list[GenerationResult] = []
    for url in urls:
        results.append(
            process_url(
                url=url.strip(),
                output_dir=output_dir,
                use_ai=use_ai,
                include_images=include_images,
                progress=progress,
                client=client,
            )
        )
    return results


def _unique_slug(title: str, output_dir: Path) -> str:
    base = safe_filename(title)
    candidate = base
    suffix = 2
    while (output_dir / f"{candidate}.docx").exists() or (output_dir / f"{candidate}.pptx").exists():
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate
