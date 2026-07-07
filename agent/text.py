"""Text normalization and lexical features for Chinese financial documents."""

from __future__ import annotations

import html
import re
from collections import Counter

PUNCT_RE = re.compile(r"[\s\t\r\n\f\v，。、“”‘’：:；;（）()【】\[\]《》<>？?！!,.·/\\|+\-=*_#`~^$@]+")
WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%/-]*|[\u4e00-\u9fff]{2,}")
NUMBER_RE = re.compile(r"(?<![\dA-Za-z])[-+]?\d+(?:,\d{3})*(?:\.\d+)?%?")
YEAR_RE = re.compile(r"(?:19|20)\d{2}")
CLAUSE_RE = re.compile(r"第[一二三四五六七八九十百千万零〇两\d]+[条章节款项]")


def clean_text(text: str) -> str:
    text = html.unescape(text or "").replace("\ufeff", "")
    text = re.sub(r"[ \t\r\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_for_match(text: str) -> str:
    return PUNCT_RE.sub("", (text or "").lower())


def numbers(text: str, limit: int = 120) -> list[str]:
    return NUMBER_RE.findall(text or "")[:limit]


def years(text: str) -> list[str]:
    return sorted(set(YEAR_RE.findall(text or "")))


def clauses(text: str) -> list[str]:
    return sorted(set(CLAUSE_RE.findall(text or "")))


def char_ngrams(text: str, n: int) -> set[str]:
    norm = normalize_for_match(text)
    if len(norm) < n:
        return {norm} if norm else set()
    return {norm[i : i + n] for i in range(len(norm) - n + 1)}


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in WORD_RE.finditer(text or ""):
        token = match.group(0).lower()
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            if len(token) <= 8:
                tokens.append(token)
            for n in (2, 3, 4):
                if len(token) >= n:
                    tokens.extend(token[i : i + n] for i in range(len(token) - n + 1))
        else:
            tokens.append(token)
    tokens.extend(num.lower() for num in numbers(text))
    return [tok for tok in tokens if tok and len(tok) >= 2]


def token_counts(text: str) -> Counter[str]:
    return Counter(tokenize(text))


def keyphrases(text: str, limit: int = 60) -> list[str]:
    phrases: list[str] = []
    for match in WORD_RE.finditer(text or ""):
        token = match.group(0).strip()
        if len(token) >= 3:
            phrases.append(token)
    phrases.extend(numbers(text))
    phrases.extend(clauses(text))
    seen: set[str] = set()
    out: list[str] = []
    for phrase in phrases:
        key = normalize_for_match(phrase)
        if key and key not in seen:
            seen.add(key)
            out.append(phrase)
        if len(out) >= limit:
            break
    return out

