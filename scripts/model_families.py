#!/usr/bin/env python3
"""Model-family identity: which leaderboard rows are the same model.

llm-stats ranks every release independently, so one family can occupy several
of a country's ten slots ("Claude Opus 5" alongside "Claude Opus 4.8"). The
site should show each model once, at its newest version. Shared by the scraper
(which drops the superseded rows) and validate_models.py (which fails the run
if any survive).
"""
import re
from typing import Dict, List, Optional, Tuple

# Version tokens inside a model name: "5.6" in "GPT-5.6 Sol", "4" in
# "DeepSeek-V4-Pro-0813". A bare 4-digit token is an MMDD checkpoint stamp that
# llm-stats appends to dated re-releases of the same version.
VERSION_TOKEN_RE = re.compile(r"\d+(?:\.\d+)*")
CHECKPOINT_RE = re.compile(r"^\d{4}$")


def model_family_key(name: str) -> str:
    """Collapse a model name to its family, dropping version/checkpoint tokens.

    "Claude Opus 5" and "Claude Opus 4.8" both reduce to "claude opus". The
    alphabetic tier words (Opus / Sonnet / Fable, Flash, Pro, Max) are kept, so
    genuinely different tiers stay in separate families.
    """
    tokens = []
    for token in re.split(r"[\s\-_]+", name.lower()):
        if not token:
            continue
        # A standalone version ("5.6") or checkpoint stamp ("0813") carries no
        # family information.
        if VERSION_TOKEN_RE.fullmatch(token):
            continue
        # A version glued to its prefix: "v4", "k3", "qwen3.8", "glm5.3".
        stripped = re.sub(r"\d+(?:\.\d+)*$", "", token)
        if not stripped:
            continue
        tokens.append(stripped)
    return " ".join(tokens)


def model_version_key(name: str) -> Optional[Tuple[int, ...]]:
    """Sortable version for a model name, or None if it carries no version.

    The *first* numeric token is the version — a trailing 4-digit checkpoint
    stamp ("DeepSeek-V4-Flash-0731") is a re-release of that version, so it
    sorts as a trailing component rather than replacing it. Names with no
    version at all return None and are never treated as superseded.
    """
    numbers = VERSION_TOKEN_RE.findall(name)
    if not numbers:
        return None
    version = tuple(int(part) for part in numbers[0].split("."))
    checkpoint = 0
    for token in numbers[1:]:
        if CHECKPOINT_RE.match(token):
            checkpoint = int(token)
    # Pad so "5" and "5.6" compare on equal footing before the checkpoint.
    return version + (0,) * (4 - len(version)) + (checkpoint,)


def superseded_models(names: List[str]) -> Dict[int, str]:
    """Map index -> superseding model name, for every name that is an older
    version of another name in the list.

    A bare family name folds into its suffixed variants when the bare name is a
    single brand token that also appears on its own: "GPT-5.5" competes with
    "GPT-5.6 Sol" and "GPT-5.6 Terra". The single-token guard stops a deep
    variant chain from absorbing its own prefix, so "DeepSeek-V4-Flash" is not
    superseded by an experimental "DeepSeek-V4-Flash-Vision-Exp".

    Names tied on version are all kept — Sol and Terra are siblings, not
    successors. Only a strictly newer version supersedes, so the result never
    depends on the order the leaderboard happened to rank them in.
    """
    family_keys = [model_family_key(n) for n in names]
    brand_roots = {k for k in family_keys if len(k.split()) == 1}

    def group_for(key: str) -> str:
        head = key.split()[0] if key else key
        return head if head in brand_roots else key

    groups: Dict[str, List[int]] = {}
    for idx, key in enumerate(family_keys):
        groups.setdefault(group_for(key), []).append(idx)

    superseded: Dict[int, str] = {}
    for indexes in groups.values():
        versions = [model_version_key(names[i]) for i in indexes]
        known = [v for v in versions if v is not None]
        if len(known) < 2:
            continue
        newest = max(known)
        winner = next(names[i] for i, v in zip(indexes, versions) if v == newest)
        for i, version in zip(indexes, versions):
            if version is not None and version < newest:
                superseded[i] = winner
    return superseded
