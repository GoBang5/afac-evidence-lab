"""Cache query-independent score features; preserve upstream rankings exactly.

cached_score_candidate is derived from agent/retrieval.py at upstream 042e0fd.
Only feature extraction is memoized; weights, scoring and tie order are unchanged.
"""
from __future__ import annotations

import math
from typing import Any
from agent.domain_rules import profile_for, extract_question_features, build_option_queries
from agent.retrieval import (CandidateIndex, build_local_idf, build_query_features,
                             diversify_by_doc, _doc_position_bonus)
from agent.schema import Candidate, Question, QuestionFeatures, ScoredEvidence
from agent.text import normalize_for_match, numbers, years, clauses


class CachedIndex(CandidateIndex):
    def __init__(self, candidates_by_doc, docs_by_id):
        super().__init__(candidates_by_doc, docs_by_id)
        ids = [c.candidate_id for cs in candidates_by_doc.values() for c in cs]
        if len(set(ids)) != len(ids) or any(not cid for cid in ids):
            raise ValueError("Candidate IDs must be nonempty and globally unique")
        self._static = {}
        self._idf = {}
        self._domain_terms = {}

    def static_for(self, cand, domain):
        key = (cand.candidate_id, domain)
        if key not in self._static:
            norm = self.norm_for(cand)
            terms = self._domain_terms.setdefault(domain, [
                (term, normalize_for_match(term)) for term in profile_for(domain).keywords])
            self._static[key] = {
                "numbers": set(cand.numbers) | set(numbers(cand.text)),
                "years": set(years(cand.text)), "clauses": set(clauses(cand.text)),
                "domain_hits": [term for term, normalized in terms if normalized and normalized in norm],
            }
        return self._static[key]

    def local_idf(self, doc_ids):
        key = tuple(doc_ids)
        if key not in self._idf:
            self._idf[key] = build_local_idf(self.get_candidates(doc_ids), self)
        return self._idf[key]


def cached_score_candidate(
    index: CandidateIndex,
    cand: Candidate,
    query: str,
    question: Question,
    features: QuestionFeatures,
    idf: dict[str, float],
    option_text: str,
    query_features: dict[str, Any] | None = None,
) -> tuple[float, dict[str, Any]]:
    query_features = query_features or build_query_features(query, option_text)
    q_counts = query_features["q_counts"]
    c_counts = index.token_counts_for(cand)
    token_score = 0.0
    matched_tokens: list[str] = []
    for token, q_count in q_counts.items():
        tf = c_counts.get(token)
        if tf:
            matched_tokens.append(token)
            token_score += (1.0 + math.log1p(tf)) * idf.get(token, 1.0) * min(q_count, 3)

    q_bigrams = query_features["q_bigrams"]
    c_bigrams = index.bigrams_for(cand)
    bigram_overlap = len(q_bigrams & c_bigrams)
    bigram_score = bigram_overlap / max(8, len(q_bigrams)) * 8.0

    q_numbers = query_features["q_numbers"]
    c_numbers = index.static_for(cand, question.domain)["numbers"]
    matched_numbers = sorted(q_numbers & c_numbers)
    number_score = 2.5 * len(matched_numbers)

    q_years = query_features["q_years"]
    c_years = index.static_for(cand, question.domain)["years"]
    matched_years = sorted(q_years & c_years)
    year_score = 1.5 * len(matched_years)

    q_clauses = query_features["q_clauses"]
    c_clauses = index.static_for(cand, question.domain)["clauses"]
    matched_clauses = sorted(q_clauses & c_clauses)
    clause_score = 3.0 * len(matched_clauses)

    cand_norm = index.norm_for(cand)
    option_norm = query_features["option_norm"]
    literal_score = 0.0
    if option_norm and len(option_norm) >= 8 and option_norm in cand_norm:
        literal_score += 16.0

    phrase_hits = []
    for phrase in query_features["option_phrases"]:
        phrase_norm = normalize_for_match(phrase)
        if phrase_norm in cand_norm:
            phrase_hits.append(phrase)
    phrase_score = 1.5 * len(phrase_hits)

    section_norm = normalize_for_match(cand.section_title)
    section_hits = [
        term for term in features.domain_terms
        if normalize_for_match(term) and normalize_for_match(term) in section_norm
    ]
    section_score = 1.2 * len(section_hits)

    domain_hits = index.static_for(cand, question.domain)["domain_hits"]
    domain_score = 0.35 * len(domain_hits)

    unit_bonus = 0.0
    if cand.unit_type == "heading":
        unit_bonus += 0.5
    if cand.unit_type == "table" or cand.modality == "table":
        unit_bonus += 1.2
    if cand.evidence_role == "primary":
        unit_bonus += 0.5

    quality_bonus = max(0.0, min(cand.evidence_weight, 1.0)) * 0.8
    position_bonus = _doc_position_bonus(question, option_text, cand)

    score = (
        token_score
        + bigram_score
        + number_score
        + year_score
        + clause_score
        + literal_score
        + phrase_score
        + section_score
        + domain_score
        + unit_bonus
        + quality_bonus
        + position_bonus
    )
    return score, {
        "token_score": round(token_score, 4),
        "bigram_score": round(bigram_score, 4),
        "number_score": round(number_score, 4),
        "year_score": round(year_score, 4),
        "clause_score": round(clause_score, 4),
        "literal_score": round(literal_score, 4),
        "phrase_score": round(phrase_score, 4),
        "section_score": round(section_score, 4),
        "domain_score": round(domain_score, 4),
        "unit_bonus": round(unit_bonus, 4),
        "quality_bonus": round(quality_bonus, 4),
        "position_bonus": round(position_bonus, 4),
        "matched_tokens": matched_tokens[:35],
        "matched_numbers": matched_numbers,
        "matched_years": matched_years,
        "matched_clauses": matched_clauses,
        "matched_option_phrases": phrase_hits[:25],
        "matched_domain_terms": domain_hits[:25],
    }


def retrieve(index, question, option_top_k=6, question_top_k=14, doc_top_k=16):
    features = extract_question_features(question)
    docs, missing = index.route_docs(question, doc_top_k)
    candidates = index.get_candidates(docs)
    idf = index.local_idf(docs)
    queries = build_option_queries(question, features)

    def rank(query, option, limit):
        option_text = question.options.get(option, "")
        query_features = build_query_features(query, option_text)
        scored = []
        for cand in candidates:
            score, details = cached_score_candidate(index, cand, query, question, features,
                                                     idf, option_text, query_features)
            if score > 0:
                scored.append(ScoredEvidence(cand, score, details, option))
        scored.sort(key=lambda item: item.score, reverse=True)
        return diversify_by_doc(scored, limit, len(docs))

    options = {label: rank(query, label, option_top_k) for label, query in sorted(queries.items())}
    query = "\n".join([question.question, " ".join(features.keyphrases), " ".join(features.domain_terms)])
    return options, rank(query, None, question_top_k), docs, missing
