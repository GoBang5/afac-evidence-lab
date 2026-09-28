"""Adapt an existing page extraction without importing answers or pseudo labels."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from agent.io_utils import write_json, write_jsonl
from agent.text import clean_text, numbers


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def adapt(source: Path, out: Path, chunk_chars=900, overlap=120):
    if chunk_chars <= 0 or not 0 <= overlap < chunk_chars:
        raise ValueError('Require chunk_chars > overlap >= 0')
    if out.exists():
        raise FileExistsError(f'Choose a new data directory: {out}')
    questions = json.loads((source / 'questions-a.json').read_text())
    documents = json.loads((source / 'documents.json').read_text())
    fields = ('qid', 'question', 'options', 'domain', 'split', 'type', 'answer_format', 'doc_ids')
    questions = [{k: row[k] for k in fields if k in row} for row in questions]
    if len({q['qid'] for q in questions}) != len(questions):
        raise ValueError('Duplicate question ids')
    wanted = {d for q in questions for d in q['doc_ids']}
    selected = [d for d in documents if d['doc_id'] in wanted]
    if wanted - {d['doc_id'] for d in selected}:
        raise ValueError('Missing referenced documents')
    candidates, metas = [], []
    for doc in selected:
        text, did = doc['text'], doc['doc_id']
        metas.append({'doc_id': did, 'domain': doc['domain'], 'source_title': doc['title']})
        markers = list(re.finditer(r'\[PDF_PAGE_(\d+)\]', text))
        sections = [(int(m.group(1)), m.end(), markers[i + 1].start() if i + 1 < len(markers) else len(text))
                    for i, m in enumerate(markers)] or [(None, 0, len(text))]
        for page, start, end in sections:
            for pos in range(start, end, chunk_chars - overlap):
                raw = text[pos:min(pos + chunk_chars, end)]
                quote = clean_text(raw)
                if not quote:
                    continue
                cid = hashlib.sha256(f'{did}:{page}:{pos}:{quote}'.encode()).hexdigest()[:24]
                candidates.append({
                    'candidate_id': cid, 'doc_id': did, 'page_id': page, 'text': quote,
                    'unit_type': 'text', 'modality': 'text', 'quality_tier': 'extracted',
                    'evidence_weight': 1.0, 'numbers': numbers(quote), 'reading_order': pos,
                    'source_name': doc['title'],
                    'locator': {'start': pos, 'end': min(pos + chunk_chars, end),
                                'page_numbering': 'physical_1_based' if page else 'not_paginated',
                                'quote_sha256': hashlib.sha256(quote.encode()).hexdigest(),
                                'raw_sha256': hashlib.sha256(raw.encode()).hexdigest()},
                })
                if pos + chunk_chars >= end:
                    break
    out.mkdir(parents=True)
    write_jsonl(out / 'questions.jsonl', questions)
    write_jsonl(out / 'docs.jsonl', metas)
    write_jsonl(out / 'selector.jsonl', candidates)
    manifest = {
        'source': str(source.resolve()), 'source_files': {n: digest(source / n) for n in ('documents.json', 'questions-a.json')},
        'scope': 'A-list referenced documents only; not the full B-list corpus',
        'questions': len(questions), 'documents': len(metas), 'candidates': len(candidates),
        'chunk_chars': chunk_chars, 'overlap': overlap,
        'answers_imported': False, 'parser': 'existing PyMuPDF/plain-text extraction, NOT MinerU',
        'outputs_sha256': {n: digest(out / n) for n in ('questions.jsonl', 'docs.jsonl', 'selector.jsonl')},
    }
    write_json(out / 'manifest.json', manifest)
    return manifest
