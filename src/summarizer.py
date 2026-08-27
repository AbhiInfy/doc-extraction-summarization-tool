from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict

import requests

from .models import (
    CategorySummary,
    DocumentSummary,
    DocumentTree,
    FeatureSummary,
    ThemeSummary,
    TopicNode,
)

SKIP_TITLES = {
    "title and copyright information",
    "revision history",
    "overview",
    "feature summary",
}

QUALITY_COMPLETION = 4000
GROQ_FEATURE_COMPLETION = 1800
GROQ_DECK_COMPLETION = 2200
_GROQ_WINDOW = {"start": 0.0, "tokens": 0}
_SKIP_PROVIDERS: set[str] = set()

THEME_RULES = (
    ("Alerts & communications", r"\b(alerts?|notif\w*|communication)\b"),
    ("AI & simulation", r"\b(ai|agent|agents|generative|assistant|llm|simulat\w*)\b"),
    ("Certifications & documents", r"\b(certif\w*|attachments?|pending actions|document type)\b"),
    ("Redwood experience", r"\bredwood\b"),
    ("Enrollment experience", r"\b(enroll\w*|life event)\b"),
    ("Administrator productivity", r"\b(administrat\w*)\b"),
    ("Configuration and extensibility", r"\b(configur\w*|page properties|profile option|rules?)\b"),
)

PROFILE_RE = re.compile(r"\bORA_[A-Z0-9_]{6,}\b")
LOOKUP_RE = re.compile(r"\b(?:BEN|ORA_BEN)_[A-Z0-9_]+\b")


def summarize_document(tree: DocumentTree, use_ai: bool = True) -> DocumentSummary:
    categories = _category_summaries(tree)
    features = [
        feature
        for category in categories
        for feature in category.features
        if _is_client_feature(feature)
    ]
    briefing = _client_briefing(tree, categories, features)
    if not use_ai:
        briefing.ai_note = "PowerPoint used the extractive briefing (AI checkbox was off)."
        return briefing
    try:
        return _enrich_with_ai(tree, briefing)
    except Exception as exc:
        briefing.used_ai = False
        briefing.ai_note = f"PowerPoint used the extractive briefing (AI failed: {exc})."
        return briefing


def _category_summaries(tree: DocumentTree) -> list[CategorySummary]:
    categories: list[CategorySummary] = []
    for root in tree.roots:
        if root.children:
            _collect_categories(root, categories)
        elif root.url and _usable_title(root.title):
            categories.append(
                CategorySummary(title=root.title, features=[_feature_from_node(root, root.title)])
            )
    return categories


def _collect_categories(node: TopicNode, categories: list[CategorySummary]) -> None:
    child_features = [
        _feature_from_node(child, node.title)
        for child in node.children
        if child.url and not child.children and _usable_title(child.title)
    ]
    if child_features:
        categories.append(
            CategorySummary(
                title=f"{node.number} {node.title}".strip(),
                features=child_features,
            )
        )
    for child in node.children:
        if child.children:
            _collect_categories(child, categories)


def _feature_from_node(node: TopicNode, section: str) -> FeatureSummary:
    content = node.content
    text = content.plain_text() if content else ""
    overview = content.overview_text() if content else ""
    steps = content.section_text("steps to enable") if content else ""
    tips = content.section_text("tips and considerations") if content else ""
    benefit = _business_benefit(content, text) if content else _sentence_with(text, "business benefit")
    whats_new = _whats_new(overview or text)
    enablement = _action_from_source(steps, text)
    actions = _action_lines(steps or text)
    talking = _talking_points(benefit, tips, whats_new)
    profiles = sorted(set(PROFILE_RE.findall(text)))
    details = _detail_bullets(overview, steps, tips, text)
    return FeatureSummary(
        title=node.title,
        number=node.number,
        bullets=whats_new[:3],
        business_benefit=benefit,
        actions=actions[:3],
        whats_new=whats_new[:4],
        client_impact=benefit or (whats_new[0] if whats_new else ""),
        enablement=enablement,
        impact=_impact_from_source(text, enablement),
        talking_points=talking,
        theme=_classify_theme(node.title, text),
        section=section,
        details=details,
        profile_options=profiles,
        takeaway=_takeaway(profiles, enablement, tips),
    )


def _client_briefing(
    tree: DocumentTree,
    categories: list[CategorySummary],
    features: list[FeatureSummary],
) -> DocumentSummary:
    product, release = _product_release(tree.title)
    themes = _themes(features)
    auto = sum(1 for feature in features if feature.enablement.lower().startswith("auto"))
    opt_in = sum(1 for feature in features if "opt" in feature.enablement.lower() or "profile" in feature.enablement.lower())
    setup = len(features) - auto - opt_in
    snapshot = [
        (str(len(features)), "Client-facing features"),
        (str(len(themes) or 1), "Themes to discuss"),
        (str(opt_in), "Opt-in / profile option"),
        (str(setup), "Setup or decision needed"),
    ]
    why = _why_it_matters(product, features, themes)
    highlights = []
    for feature in features:
        line = feature.business_benefit or (feature.whats_new[0] if feature.whats_new else "")
        if line:
            highlights.append(f"{feature.title}: {_short(line, 70)}")
        if len(highlights) >= 6:
            break
    actions = _prioritized_actions(features)[:5]
    executive = [
        f"{product} {release} has {len(features)} client-facing changes.".strip(),
        f"Focus: {', '.join(theme.title for theme in themes[:3]) or 'product enhancements'}.",
        f"{auto} auto-enabled, {opt_in} opt-in, {setup} need a setup decision.",
        "Word file has the full detail. This deck is the short summary.",
    ]
    return DocumentSummary(
        title=tree.title,
        source_url=tree.source_url,
        executive_summary=executive,
        highlights=highlights,
        actions=actions,
        categories=categories,
        topic_count=sum(1 for node in tree.walk() if node.url),
        used_ai=False,
        product_name=product,
        release=release,
        audience_line="Short summary for HR, HRIS, and implementation stakeholders.",
        why_it_matters=why,
        snapshot=snapshot,
        themes=themes,
        discussion_points=_discussion_points(product, features),
        next_steps=_next_steps(product),
        features=features,
    )


def _enrich_with_ai(tree: DocumentTree, briefing: DocumentSummary) -> DocumentSummary:
    _SKIP_PROVIDERS.clear()
    nodes = _node_index(tree)
    errors: list[str] = []
    providers: list[str] = []
    updated = 0
    full_payload = [
        _feature_source(feature, nodes.get(_normalize(feature.title)))
        for feature in briefing.features
    ]

    data, error, provider = _complete_json(
        _feature_accuracy_prompt(briefing, full_payload),
        allow=("Claude", "OpenAI"),
        completion_hint=QUALITY_COMPLETION,
    )
    if isinstance(data, dict) and provider:
        updated += _apply_feature_updates(briefing, data.get("features"))
        providers.append(provider)
    else:
        remaining = list(briefing.features)
        while remaining:
            batch, payload = _next_full_batch(remaining, briefing, nodes)
            groq_data, groq_error, groq_provider = _complete_json(
                _feature_accuracy_prompt(briefing, payload),
                allow=("Groq",),
                completion_hint=GROQ_FEATURE_COMPLETION,
            )
            if groq_error:
                errors.append(groq_error)
                break
            if groq_provider:
                providers.append(groq_provider)
            updated += _apply_feature_updates(
                briefing, groq_data.get("features") if isinstance(groq_data, dict) else None
            )
            remaining = remaining[len(batch) :]

    preferred = providers[-1] if providers else ""
    deck_hint = QUALITY_COMPLETION if preferred in {"Claude", "OpenAI"} else GROQ_DECK_COMPLETION
    deck_applied = False
    if preferred or updated:
        rollup, rollup_error, rollup_provider = _complete_json(
            _deck_accuracy_prompt(briefing),
            allow=(preferred,) if preferred else ("Claude", "OpenAI", "Groq"),
            completion_hint=deck_hint,
        )
        if rollup_error:
            errors.append(rollup_error)
        elif isinstance(rollup, dict):
            _apply_deck_updates(briefing, rollup)
            deck_applied = True
            if rollup_provider:
                providers.append(rollup_provider)

    return _ai_result(briefing, providers, updated, deck_applied, errors)


def _ai_result(
    briefing: DocumentSummary,
    providers: list[str],
    updated: int,
    deck_applied: bool,
    errors: list[str],
) -> DocumentSummary:
    unique_errors = list(dict.fromkeys(errors))
    used_names = " / ".join(dict.fromkeys(providers))
    if updated or deck_applied:
        briefing.used_ai = True
        extra = ""
        real_issues = [
            _short_error(item)
            for item in unique_errors
            if _is_real_generation_issue(item)
        ]
        if real_issues:
            extra = f" Partial issues: {'; '.join(real_issues)}"
        briefing.ai_note = (
            f"PowerPoint used the {used_names or 'AI'} summary, grounded in the Oracle page text.{extra}"
        )
        return briefing
    detail = "; ".join(_short_error(item) for item in unique_errors) if unique_errors else "the model did not return usable JSON"
    briefing.ai_note = f"PowerPoint used the extractive briefing ({detail})."
    return briefing


def _next_full_batch(
    features: list[FeatureSummary],
    briefing: DocumentSummary,
    nodes: dict[str, TopicNode],
) -> tuple[list[FeatureSummary], list[dict]]:
    limit = _groq_token_limit()
    batch: list[FeatureSummary] = []
    payload: list[dict] = []
    for feature in features:
        source = _feature_source(feature, nodes.get(_normalize(feature.title)))
        trial = payload + [source]
        prompt = _feature_accuracy_prompt(briefing, trial)
        requested = _request_tokens(prompt, GROQ_FEATURE_COMPLETION)
        if batch and requested > limit - 200:
            break
        batch.append(feature)
        payload.append(source)
    return batch, payload


def _feature_accuracy_prompt(briefing: DocumentSummary, payload: list[dict]) -> str:
    return (
        "Write an accurate client-ready PowerPoint summary of these Oracle HCM What's New pages.\n"
        f"Product: {briefing.product_name} {briefing.release}\n"
        "Style: specific and speakable, like a feature briefing, not a documentation dump.\n\n"
        "Accuracy rules:\n"
        "- Use ONLY facts in each feature's source. Do not invent setup, lookups, or capabilities.\n"
        "- Keep each feature title EXACTLY as given.\n"
        "- Keep enablement EXACTLY as given.\n"
        "- Prefer concrete names, pages, profile options, and constraints from SOURCE.\n"
        "- Copy ORA_ and lookup codes exactly when they appear.\n\n"
        "Return JSON: {\"features\": [ "
        "{\"title\", "
        "\"whats_new\" (1 sentence of the actual change), "
        "\"details\" (4 how-it-works bullets from the source), "
        "\"business_benefit\" (who benefits and how), "
        "\"takeaway\" (profile options or setup constraint from the source), "
        "\"client_impact\" (who is affected), "
        "\"talking_points\" (1 spoken line a consultant would say), "
        "\"actions\" (1 client action) } ]}\n"
        "Do not change impact or enablement.\n\n"
        f"SOURCE:\n{json.dumps(payload, ensure_ascii=False)}"
    )


def _deck_accuracy_prompt(briefing: DocumentSummary) -> str:
    payload = {
        "title": briefing.title,
        "product": briefing.product_name,
        "release": briefing.release,
        "features": [
            {
                "title": feature.title,
                "theme": feature.theme,
                "enablement": feature.enablement,
                "impact": feature.impact,
                "profile_options": feature.profile_options,
                "whats_new": feature.whats_new,
                "details": feature.details,
                "takeaway": feature.takeaway,
                "business_benefit": feature.business_benefit,
            }
            for feature in briefing.features
        ],
    }
    return (
        "Create a 10-12 slide summarised PowerPoint like an Oracle What's New feature summary. "
        "Group features by theme. Include a Feature | Impact | Action table.\n"
        f"Product: {briefing.product_name} {briefing.release}\n"
        "Tone: specific, business-first, speakable in 5 minutes. Use real feature names and ORA_ codes.\n\n"
        "Accuracy rules:\n"
        "- Do not add features or capabilities that are not in SOURCE.\n"
        "- Theme feature names must match SOURCE titles exactly.\n"
        "- Keep enablement and impact as given.\n"
        "- Theme messages should say what actually changes, not generic labels.\n\n"
        "Return JSON with:\n"
        "- audience_line: one sentence for HR, HRIS, and implementation stakeholders\n"
        "- executive_summary: 4 bullets covering the release story\n"
        "- why_it_matters: 3 business outcomes grounded in SOURCE\n"
        "- themes: up to 5 of {title, message, features}\n"
        "- highlights: 5 takeaways using real feature names and setup facts\n"
        "- actions: 4 prioritized client actions\n"
        "- discussion_points: []\n"
        "- next_steps: 3 next steps\n\n"
        f"SOURCE:\n{json.dumps(payload, ensure_ascii=False)}"
    )


def _feature_source(feature: FeatureSummary, node: TopicNode | None) -> dict:
    content = node.content if node else None
    text = content.plain_text() if content else ""
    return {
        "title": feature.title,
        "number": feature.number,
        "section": feature.section,
        "theme": feature.theme,
        "enablement": feature.enablement,
        "impact": feature.impact,
        "profile_options": feature.profile_options,
        "lookups": sorted(set(LOOKUP_RE.findall(text))),
        "source": {
            "overview": content.overview_text() if content else "",
            "business_benefit": (content.section_text("business benefit") if content else "") or feature.business_benefit,
            "steps_to_enable": content.section_text("steps to enable") if content else "",
            "tips": content.section_text("tips and considerations") if content else "",
        },
    }


def _apply_feature_updates(briefing: DocumentSummary, items) -> int:
    if not isinstance(items, list):
        return 0
    updated = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        feature = _match_feature(str(item.get("title", "")), briefing.features)
        if not feature:
            continue
        whats_new = _as_list(item.get("whats_new"))
        if whats_new:
            feature.whats_new = [_short(line, 180) for line in whats_new[:2]]
            feature.bullets = feature.whats_new[:2]
        if item.get("business_benefit"):
            feature.business_benefit = _short(str(item["business_benefit"]), 180)
        if item.get("client_impact"):
            feature.client_impact = _short(str(item["client_impact"]), 140)
        talking = _as_list(item.get("talking_points"))
        if talking:
            feature.talking_points = [_short(line, 180) for line in talking[:2]]
        actions = _as_list(item.get("actions"))
        if actions:
            feature.actions = [_short(line, 160) for line in actions[:2]]
        details = _as_list(item.get("details") or item.get("whats_new"))
        if details:
            feature.details = [_short(line, 180) for line in details[:5]]
        if item.get("takeaway"):
            feature.takeaway = _short(str(item["takeaway"]), 220)
        updated += 1
    return updated


def _apply_deck_updates(briefing: DocumentSummary, data: dict) -> None:
    briefing.audience_line = _short(str(data.get("audience_line") or briefing.audience_line), 160)
    briefing.executive_summary = [_short(line, 160) for line in (_as_list(data.get("executive_summary")) or briefing.executive_summary)[:4]]
    briefing.why_it_matters = [_short(line, 160) for line in (_as_list(data.get("why_it_matters")) or briefing.why_it_matters)[:4]]
    briefing.highlights = [_short(line, 160) for line in (_as_list(data.get("highlights")) or briefing.highlights)[:6]]
    briefing.actions = [_short(line, 160) for line in (_as_list(data.get("actions")) or briefing.actions)[:5]]
    briefing.discussion_points = []
    briefing.next_steps = [_short(line, 140) for line in (_as_list(data.get("next_steps")) or briefing.next_steps)[:4]]
    known = {_normalize(feature.title): feature.title for feature in briefing.features}
    themes: list[ThemeSummary] = []
    for item in data.get("themes") or []:
        if not isinstance(item, dict):
            continue
        names = []
        for name in _as_list(item.get("features")):
            title = known.get(_normalize(name))
            if title and title not in names:
                names.append(title)
        if not names:
            continue
        themes.append(
            ThemeSummary(
                title=str(item.get("title", "Theme")),
                message=_short(str(item.get("message", "")), 140),
                features=names,
            )
        )
    if themes:
        briefing.themes = themes


def _match_feature(title: str, features: list[FeatureSummary]) -> FeatureSummary | None:
    key = _normalize(title)
    exact = [feature for feature in features if _normalize(feature.title) == key]
    if len(exact) == 1:
        return exact[0]
    partial = [
        feature
        for feature in features
        if key and (key in _normalize(feature.title) or _normalize(feature.title) in key)
    ]
    if len(partial) == 1:
        return partial[0]
    return None


def _node_index(tree: DocumentTree) -> dict[str, TopicNode]:
    index: dict[str, TopicNode] = {}
    for node in tree.walk():
        if node.url and _usable_title(node.title):
            index[_normalize(node.title)] = node
    return index


def _complete_json(
    prompt: str,
    allow: tuple[str, ...] | None = None,
    completion_hint: int = GROQ_FEATURE_COMPLETION,
) -> tuple[dict | None, str, str]:
    errors: list[str] = []
    callers = [
        ("Claude", _call_claude),
        ("OpenAI", _call_openai),
        ("Groq", lambda text: _call_groq(text, completion_hint)),
    ]
    if allow:
        callers = [item for item in callers if item[0] in allow]
    for name, caller in callers:
        if name in _SKIP_PROVIDERS:
            continue
        if not _provider_configured(name):
            _SKIP_PROVIDERS.add(name)
            errors.append(f"{name}: no API key")
            continue
        try:
            data = caller(prompt)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            if _is_permanent_provider_error(str(exc)):
                _SKIP_PROVIDERS.add(name)
            continue
        if data is not None:
            return data, "", name
        errors.append(f"{name}: empty response")
    return None, "; ".join(dict.fromkeys(errors)), ""


def _provider_configured(name: str) -> bool:
    if name == "Claude":
        return bool(os.getenv("ANTHROPIC_API_KEY"))
    if name == "OpenAI":
        return bool(os.getenv("OPENAI_API_KEY"))
    if name == "Groq":
        return bool(_groq_api_key())
    if name == "Grok":
        return bool(_xai_api_key())
    return False


def _call_claude(prompt: str) -> dict | None:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 8000,
            "messages": [{"role": "user", "content": prompt + "\n\nReturn only valid JSON."}],
        },
        timeout=120,
    )
    if not response.ok:
        raise RuntimeError(_api_error_message(response))
    payload = response.json()
    text = "".join(
        block.get("text", "")
        for block in payload.get("content", [])
        if isinstance(block, dict) and block.get("type") == "text"
    )
    return _parse_json(text)


def _call_openai(prompt: str) -> dict | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    return _call_openai_compatible(
        prompt,
        api_key=api_key,
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    )


def _call_groq(prompt: str, completion_hint: int = GROQ_FEATURE_COMPLETION) -> dict | None:
    api_key = _groq_api_key()
    if not api_key:
        return None
    preferred = _normalize_groq_model(os.getenv("GROQ_MODEL") or "openai/gpt-oss-20b")
    completion = _groq_completion_budget(prompt, completion_hint)
    _pace_groq(_request_tokens(prompt, completion))
    try:
        return _call_openai_compatible(
            prompt,
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
            model=preferred,
            groq=True,
            completion_tokens=completion,
        )
    except Exception as exc:
        message = str(exc).lower()
        if "rate_limit" in message or "tokens per minute" in message or "tpm" in message or "too large" in message or "413" in message:
            _pace_groq(_request_tokens(prompt, completion), force_wait=True)
            return _call_openai_compatible(
                prompt,
                api_key=api_key,
                base_url="https://api.groq.com/openai/v1",
                model=preferred,
                groq=True,
                completion_tokens=completion,
            )
        fallback = "qwen/qwen3.6-27b" if preferred != "qwen/qwen3.6-27b" else "openai/gpt-oss-20b"
        return _call_openai_compatible(
            prompt,
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
            model=fallback,
            groq=True,
            completion_tokens=completion,
        )


def _call_grok(prompt: str) -> dict | None:
    api_key = _xai_api_key()
    if not api_key:
        return None
    return _call_openai_compatible(
        prompt,
        api_key=api_key,
        base_url=os.getenv("XAI_BASE_URL") or "https://api.x.ai/v1",
        model=os.getenv("GROK_MODEL") or os.getenv("XAI_MODEL") or "grok-3-mini",
    )


def _call_openai_compatible(
    prompt: str,
    api_key: str,
    base_url: str | None,
    model: str,
    groq: bool = False,
    completion_tokens: int | None = None,
) -> dict:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    max_tokens = completion_tokens or (GROQ_FEATURE_COMPLETION if groq else 4000)
    messages = [
        {
            "role": "system",
            "content": (
                "You write accurate client-ready Oracle HCM PowerPoint briefings. "
                "Use only the provided source. Return one valid JSON object only. "
                "Do not write markdown or explanation."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if groq:
        kwargs["reasoning_effort"] = "low"
        kwargs["reasoning_format"] = "hidden"
        kwargs["messages"] = [
            {
                "role": "system",
                "content": "Return one valid JSON object only. Use only the source. No markdown.",
            },
            {"role": "user", "content": prompt},
        ]
    else:
        kwargs["temperature"] = 0
    try:
        response = client.chat.completions.create(**kwargs)
    except Exception:
        kwargs.pop("response_format", None)
        kwargs.pop("reasoning_format", None)
        kwargs.pop("reasoning_effort", None)
        if not groq:
            kwargs["temperature"] = 0
        response = client.chat.completions.create(**kwargs)
    return _parse_json(_message_text(response.choices[0].message))


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text or "") + 2) // 3)


def _request_tokens(prompt: str, completion_tokens: int) -> int:
    return _estimate_tokens(prompt) + completion_tokens + 80


def _groq_token_limit() -> int:
    raw = (os.getenv("GROQ_TOKEN_LIMIT") or "8000").strip()
    try:
        return max(1000, int(raw))
    except ValueError:
        return 8000


def _groq_completion_budget(prompt: str, desired: int) -> int:
    room = _groq_token_limit() - _estimate_tokens(prompt) - 200
    return max(400, min(desired, room))


def _pace_groq(requested: int, force_wait: bool = False) -> None:
    now = time.monotonic()
    elapsed = now - _GROQ_WINDOW["start"]
    limit = _groq_token_limit()
    if _GROQ_WINDOW["start"] and elapsed >= 60:
        _GROQ_WINDOW["start"] = now
        _GROQ_WINDOW["tokens"] = 0
        elapsed = 0
    if force_wait or (_GROQ_WINDOW["tokens"] and _GROQ_WINDOW["tokens"] + requested > limit - 200):
        wait = max(0, 60 - elapsed)
        if wait:
            time.sleep(wait)
        _GROQ_WINDOW["start"] = time.monotonic()
        _GROQ_WINDOW["tokens"] = 0
    elif not _GROQ_WINDOW["start"]:
        _GROQ_WINDOW["start"] = now
    _GROQ_WINDOW["tokens"] += requested


def _is_permanent_provider_error(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        token in lowered
        for token in (
            "credit balance",
            "no api key",
            "invalid api key",
            "authentication",
            "unauthorized",
        )
    )


def _is_real_generation_issue(text: str) -> bool:
    lowered = str(text or "").lower()
    if _is_permanent_provider_error(lowered):
        return False
    if "no api key" in lowered:
        return False
    return bool(lowered)


def _short_error(text: str) -> str:
    value = str(text or "")
    lowered = value.lower()
    if "credit balance" in lowered:
        return "Claude: credit balance too low"
    if "no api key" in lowered or "no OPENAI" in value:
        return "OpenAI: no API key"
    if "too large" in lowered or "rate_limit_exceeded" in lowered or "tpm" in lowered:
        return "Groq: request exceeded the 8000-token free limit"
    if "unterminated" in lowered or "expecting value" in lowered:
        return "Groq: invalid JSON from the model"
    return value.split("\n", 1)[0][:180]


def _groq_api_key() -> str:
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if key:
        return key
    grok = (os.getenv("GROK_API_KEY") or "").strip()
    return grok if grok.startswith("gsk_") else ""


def _xai_api_key() -> str:
    key = (os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY") or "").strip()
    if key.startswith("gsk_"):
        return ""
    return key


def _normalize_groq_model(model: str) -> str:
    value = (model or "").strip()
    if value.startswith("groq/"):
        value = value[5:]
    aliases = {
        "llama-3.1-8b-versatile": "openai/gpt-oss-20b",
        "llama-3.1-8b-instant": "openai/gpt-oss-20b",
        "llama-3.3-70b-versatile": "openai/gpt-oss-120b",
    }
    return aliases.get(value, value)


def _api_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
        message = ""
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "")
        elif isinstance(error, str):
            message = error
        if message:
            return message
    except Exception:
        pass
    return f"{response.status_code} {response.reason}"


def _chunks(items: list, size: int) -> list[list]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _clip(text: str, limit: int) -> str:
    return _short(text or "", limit)


def _themes(features: list[FeatureSummary]) -> list[ThemeSummary]:
    grouped: dict[str, list[FeatureSummary]] = defaultdict(list)
    for feature in features:
        grouped[feature.theme or "Product enhancements"].append(feature)
    messages = {
        "Alerts & communications": "Life-event based enrollment confirmation alerts",
        "AI & simulation": "Benefits Analyst Agent and life-event simulation",
        "Certifications & documents": "Attachments, previews, and uploads outside the enrollment window",
        "Redwood experience": "Plan configuration pages and page property rules",
        "Enrollment experience": "Enrollment communications and testing",
        "Administrator productivity": "Tools that let admins test and resolve work faster",
        "Configuration and extensibility": "Setup choices that control what users see after go-live",
        "Product enhancements": "Functional improvements to review for process impact",
    }
    themes = []
    for title, items in grouped.items():
        themes.append(
            ThemeSummary(
                title=title,
                message=messages.get(title, messages["Product enhancements"]),
                features=[item.title for item in items],
            )
        )
    themes.sort(key=lambda item: len(item.features), reverse=True)
    return themes


def _why_it_matters(product: str, features: list[FeatureSummary], themes: list[ThemeSummary]) -> list[str]:
    points = [
        f"{product} changes affect employees, admins, and go-live setup.",
    ]
    if any(theme.title == "Redwood experience" for theme in themes):
        points.append("Redwood pages need training and change-management time.")
    if any(theme.title == "AI & simulation" for theme in themes):
        points.append("AI agents and simulation need agreed scope and an owner.")
    if any("certif" in feature.title.lower() or "document" in feature.title.lower() for feature in features):
        points.append("Document and certification updates cut life-event follow-up.")
    points.append("Confirm auto-enabled items and schedule any opt-in work.")
    return points[:3]


def _discussion_points(product: str, features: list[FeatureSummary]) -> list[str]:
    return [
        f"Which {product} features should be in scope for this client update?",
        "Which items are auto-enabled and need only communication, versus opt-in work?",
        "Who owns Benefits/HR configuration, testing, and employee messaging?",
        "Are there policy, security, or union constraints on AI or document handling?",
        "What is the target date to confirm setup, UAT, and change-management materials?",
    ]


def _next_steps(product: str) -> list[str]:
    return [
        f"Agree which {product} items to adopt this cycle.",
        "Assign owners for opt-in and setup items.",
        "Use the Word file for detailed enablement steps.",
    ]


def _prioritized_actions(features: list[FeatureSummary]) -> list[str]:
    actions = []
    for feature in features:
        if feature.enablement.lower().startswith("auto"):
            actions.append(f"{feature.title}: confirm auto-enablement and add to the client comms plan.")
        elif feature.actions:
            actions.append(f"{feature.title}: { _short(feature.actions[0], 120)}")
        else:
            actions.append(f"{feature.title}: review enablement and decide adopt or defer.")
        if len(actions) >= 5:
            break
    return actions


def _whats_new(text: str) -> list[str]:
    bullets = []
    for raw in text.splitlines():
        line = raw.strip(" -*\t")
        if 20 < len(line) < 220 and not line.lower().startswith(("business benefit", "note:", "previous", "next")):
            bullets.append(line)
        if len(bullets) >= 4:
            return bullets
    return _lead_sentences(text, limit=3)


def _business_benefit(content, text: str) -> str:
    from_heading = content.section_text("business benefit") if content else ""
    if from_heading:
        return _short(re.sub(r"(?i)^business benefit:\s*", "", from_heading), 280)
    labeled = _sentence_with(text, "business benefit")
    if labeled:
        return _short(re.sub(r"(?i)^business benefit:\s*", "", labeled), 280)
    return _short(_lead_sentences(text, limit=1)[0], 280) if _lead_sentences(text, limit=1) else ""


def _enablement(steps: str, full_text: str) -> str:
    return _action_from_source(steps, full_text)


def _action_from_source(steps: str, full_text: str) -> str:
    blob = f"{steps}\n{full_text}".lower()
    if any(token in blob for token in ("no steps to enable", "automatically available", "nothing to do", "enabled by default", "no setup required")):
        return "Potential Setup"
    if any(token in blob for token in ("profile option", "opt in", "opt-in", "you must", "setup required", "visual builder")):
        return "Setup Required"
    if steps.strip():
        return "Setup Required"
    return "Potential Setup"


def _impact_from_source(text: str, enablement: str) -> str:
    blob = text.lower()
    if re.search(r"\bsmall[- ]scale\b", blob):
        return "Small scale"
    if re.search(r"\bimpact\b.{0,40}\bnone\b", blob) or re.search(r"\bnone\b.{0,20}\bimpact\b", blob):
        return "None"
    if enablement == "Setup Required":
        return "None"
    return "Small scale"


def _impact_from_enablement(enablement: str) -> str:
    return _impact_from_source("", enablement)


def _detail_bullets(overview: str, steps: str, tips: str, text: str) -> list[str]:
    bullets = _whats_new(overview or text)
    if len(bullets) < 3:
        bullets.extend(_whats_new(tips))
    if len(bullets) < 3:
        bullets.extend(_action_lines(steps))
    seen: set[str] = set()
    unique = []
    for line in bullets:
        key = _normalize(line)
        if key in seen:
            continue
        seen.add(key)
        unique.append(_short(line, 80))
        if len(unique) == 3:
            break
    return unique


def _takeaway(profiles: list[str], enablement: str, tips: str) -> str:
    if profiles:
        return "Profile options: " + " + ".join(profiles[:3])
    if tips.strip():
        return _short(tips, 140)
    return enablement


def _talking_points(benefit: str, tips: str, whats_new: list[str]) -> list[str]:
    points = []
    if benefit:
        points.append(_short(benefit, 160))
    for raw in tips.splitlines():
        line = raw.strip(" -*\t")
        if len(line) > 30:
            points.append(_short(line, 160))
        if len(points) >= 3:
            break
    for item in whats_new:
        if item not in points:
            points.append(_short(item, 160))
        if len(points) >= 3:
            break
    return points[:3]


def _classify_theme(title: str, text: str) -> str:
    title_l = title.lower()
    for theme, pattern in THEME_RULES:
        if re.search(pattern, title_l):
            return theme
    blob = f"{title} {text}".lower()
    for theme, pattern in THEME_RULES:
        if re.search(pattern, blob):
            return theme
    return "Product enhancements"


def _product_release(title: str) -> tuple[str, str]:
    match = re.search(r"\b(\d{2}[A-Da-d])\b", title)
    release = match.group(1).upper() if match else ""
    product = re.sub(r"Oracle Fusion Cloud\s*", "", title, flags=re.I)
    product = re.sub(r"What's New.*", "", product, flags=re.I)
    if release:
        product = product.replace(release, "")
    product = product.strip(" -–")
    return product or "HCM", release


def _is_client_feature(feature: FeatureSummary) -> bool:
    return _usable_title(feature.title) and bool(feature.whats_new or feature.business_benefit or feature.actions)


def _usable_title(title: str) -> bool:
    return title.strip().lower() not in SKIP_TITLES


def _lead_sentences(text: str, limit: int = 3) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    useful = []
    for part in re.split(r"(?<=[.!?])\s+", cleaned):
        if len(part) < 40 or part.lower().startswith(("previous", "next", "javascript")):
            continue
        useful.append(part.strip())
        if len(useful) >= limit:
            break
    return useful


def _sentence_with(text: str, needle: str) -> str:
    index = text.lower().find(needle)
    if index < 0:
        return ""
    return _short(re.split(r"(?<=[.!?])\s+", text[index:], maxsplit=1)[0], 280)


def _action_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.strip(" -*\t")
        if len(line) > 20:
            lines.append(line)
        if len(lines) >= 4:
            break
    return lines


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _message_text(message) -> str:
    content = (getattr(message, "content", None) or "").strip()
    if content:
        return content
    dump = message.model_dump() if hasattr(message, "model_dump") else {}
    for key in ("reasoning", "reasoning_content"):
        value = str(dump.get(key) or "").strip()
        if "{" in value:
            return value
    return ""


def _parse_json(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("empty model response")
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw).removesuffix("```").strip()
    candidates = [raw]
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if match:
        candidates.append(match.group(0))
    start = raw.find("{")
    if start >= 0:
        candidates.append(_repair_json(raw[start:]))
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception as exc:
            last_error = exc
            continue
        if isinstance(parsed, dict):
            return parsed
        last_error = ValueError("Model response was not a JSON object")
    raise last_error or ValueError("empty model response")


def _repair_json(raw: str) -> str:
    text = raw.strip()
    if text.count('"') % 2 == 1:
        text += '"'
    text += "]" * max(text.count("[") - text.count("]"), 0)
    text += "}" * max(text.count("{") - text.count("}"), 0)
    return text


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())


def _short(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"
