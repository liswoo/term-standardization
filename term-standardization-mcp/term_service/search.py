from collections import Counter
from uuid import UUID
from . import db
from .config import EMBEDDING_MODEL, SEMANTIC_THRESHOLD
from .embeddings import embed
from .naming import key, morphology, validate
from .schemas import Candidate, SearchInput, SearchResult

FIELDS = "id::text AS term_id,name,definition,domain,synonyms,source,english_abbr"
WORD_FIELDS = "name,english_abbr,english_name,definition,is_format_word,domain_classification,synonyms"

def validate_name(term):
    with db.connect() as conn:
        rows = conn.execute("SELECT abbreviation,names FROM abbreviation_aliases WHERE abbreviation=%s", (key(term),)).fetchall()
        synonyms = conn.execute("SELECT name FROM standard_terms WHERE %s=ANY(normalized_synonyms) AND status='ACTIVE'", (key(term),)).fetchall()
    aliases = {r["abbreviation"]: r["names"] for r in rows}
    aliases.setdefault(key(term), []).extend(r["name"] for r in synonyms)
    return validate(term, aliases)

def get_term(term_id):
    UUID(term_id)
    with db.connect() as conn:
        row = conn.execute(f"SELECT {FIELDS} FROM standard_terms WHERE id=%s", (term_id,)).fetchone()
    if not row:
        raise ValueError("TERM_NOT_FOUND")
    return row

def relational(term, limit=10):
    args = SearchInput(term=term, limit=limit)
    q = key(args.term)
    nouns = [t["form"] for t in morphology(args.term)["morphemes"] if t["tag"].startswith("N")]
    with db.connect() as conn:
        # DEPRECATED terms are kept for history/FK integrity (see manage.py's
        # import_standard_catalog) but must never surface as a match for a NEW
        # registration - a retired standard is not "already covered".
        exact = conn.execute(f"SELECT {FIELDS} FROM standard_terms WHERE normalized_name=%s AND status='ACTIVE' ORDER BY id LIMIT %s", (q, limit)).fetchall()
        synonyms = conn.execute(f"SELECT {FIELDS} FROM standard_terms WHERE %s=ANY(normalized_synonyms) AND normalized_name<>%s AND status='ACTIVE' ORDER BY id LIMIT %s", (q,q,limit)).fetchall()
        # Trigram and morphological-token retrieval replace naive substring inclusion.
        lexical = conn.execute(f"""SELECT {FIELDS}, similarity(normalized_name,%s) AS similarity
            FROM standard_terms WHERE (similarity(normalized_name,%s)>=0.3 OR noun_tokens && %s::text[])
            AND normalized_name<>%s AND NOT (%s=ANY(normalized_synonyms)) AND status='ACTIVE'
            ORDER BY similarity DESC,id LIMIT %s""", (q,q,nouns,q,q,limit)).fetchall()
    return {"exact_matches": exact, "synonym_matches": synonyms, "lexical_matches": lexical}

def vector_search(term, definition="", limit=10):
    args = SearchInput(term=term, definition=definition, limit=limit)
    with db.connect() as conn:
        count = conn.execute("SELECT count(*) AS count FROM standard_terms WHERE status='ACTIVE'").fetchone()["count"]
        if not count:
            return []
    vector = embed(args.term + (" : " + args.definition if args.definition else ""), query=True)
    with db.connect() as conn:
        return conn.execute(f"""SELECT {FIELDS},1-(embedding <=> %s) AS similarity
            FROM standard_terms WHERE embedding_model=%s AND status='ACTIVE' AND 1-(embedding <=> %s)>=%s
            ORDER BY embedding <=> %s,id LIMIT %s""",
            (vector,EMBEDDING_MODEL,vector,SEMANTIC_THRESHOLD,vector,limit)).fetchall()

def search_words(meaning_query, limit=10):
    """Meaning-first word search: given a description of a concept/use case (not a
    name), find existing standard_words whose own name+definition is semantically
    close. This is the entry point for "is there already an official word for what
    I mean" - a different problem from segment_words() in naming.py, which matches
    a term's exact substrings against known word names during decomposition. That
    one has to be exact (1의미1단어 - a word IS its name); this one has to be fuzzy,
    the same way standard_terms search is, since the query is a meaning, not a name.
    """
    limit = min(max(limit, 1), 30)
    with db.connect() as conn:
        count = conn.execute("SELECT count(*) AS count FROM standard_words WHERE status='ACTIVE' AND embedding IS NOT NULL").fetchone()["count"]
        if not count:
            return []
    vector = embed(meaning_query, query=True)
    with db.connect() as conn:
        return conn.execute(f"""SELECT {WORD_FIELDS},1-(embedding <=> %s) AS similarity
            FROM standard_words WHERE embedding_model=%s AND status='ACTIVE' AND 1-(embedding <=> %s)>=%s
            ORDER BY embedding <=> %s LIMIT %s""",
            (vector,EMBEDDING_MODEL,vector,SEMANTIC_THRESHOLD,vector,limit)).fetchall()

def search_terms_by_meaning(meaning_query, limit=10):
    """Meaning-first term search: given a free-text description of a concept (not a
    candidate term name), find existing standard_terms whose own name+definition is
    semantically close. Mirrors search_words() but for standard_terms - this is the
    entry point for "does a standard term already exist for what I mean" (find_term),
    distinct from vector_search()'s job (candidate-name-shaped similarity during
    registration, constrained by SearchInput's 200-char name-shaped limit which a
    free-text meaning description would blow past).
    """
    limit = min(max(limit, 1), 30)
    with db.connect() as conn:
        count = conn.execute("SELECT count(*) AS count FROM standard_terms WHERE status='ACTIVE'").fetchone()["count"]
        if not count:
            return []
    vector = embed(meaning_query, query=True)
    with db.connect() as conn:
        return conn.execute(f"""SELECT {FIELDS},1-(embedding <=> %s) AS similarity
            FROM standard_terms WHERE embedding_model=%s AND status='ACTIVE' AND 1-(embedding <=> %s)>=%s
            ORDER BY embedding <=> %s LIMIT %s""",
            (vector,EMBEDDING_MODEL,vector,SEMANTIC_THRESHOLD,vector,limit)).fetchall()

def search(term, definition="", limit=10):
    SearchInput(term=term, definition=definition, limit=limit)
    rdb = relational(term, limit)
    with db.connect() as conn:
        count = conn.execute("SELECT count(*) AS count FROM standard_terms WHERE status='ACTIVE'").fetchone()["count"]
        mismatch = conn.execute("SELECT count(*) AS count FROM standard_terms WHERE embedding_model<>%s AND status='ACTIVE'", (EMBEDDING_MODEL,)).fetchone()["count"]
        synthetic = conn.execute("SELECT count(*) AS count FROM standard_terms WHERE source LIKE 'SYNTHETIC_%%' AND status='ACTIVE'").fetchone()["count"]
    warnings = ["EMPTY_REFERENCE_CATALOG"] if count == 0 else []
    if synthetic:
        warnings.append("SYNTHETIC_SCENARIO_DATA_NOT_OFFICIAL")
    complete = not mismatch
    if mismatch:
        warnings.append("EMBEDDING_REINDEX_REQUIRED")
    try:
        semantic = vector_search(term, definition, limit)
    except Exception:
        # Never silently convert unavailable vector search into NEW_TERM.
        semantic, complete = [], False
        warnings.append("VECTOR_SEARCH_UNAVAILABLE")
    groups = {}
    for group, rows in {**rdb, "semantic_matches": semantic}.items():
        groups[group] = [Candidate(**r, evidence_type=group) for r in rows]
    if groups["exact_matches"]:
        match = "EXACT_MATCH"
    elif groups["synonym_matches"]:
        match = "SYNONYM_MATCH"
    elif not complete or not count:
        match = "UNDETERMINED"
    elif groups["semantic_matches"]:
        match = "SEMANTIC_SIMILAR"
    else:
        match = "NEW_TERM"
    combined = {}
    for group in ["exact_matches","synonym_matches","semantic_matches","lexical_matches"]:
        for candidate in groups[group]:
            combined.setdefault(candidate.term_id,candidate)
    return SearchResult(match_type=match, query_term=term, **groups, candidates=list(combined.values()),
        search_complete=complete, corpus_count=count, warnings=warnings)

def domain_usage(candidate_term, similar_term_ids):
    SearchInput(term=candidate_term)
    if len(similar_term_ids)>30:
        raise ValueError("At most 30 comparison term IDs are allowed")
    ids = list(dict.fromkeys(str(UUID(x)) for x in similar_term_ids))
    if not ids:
        ids = [c.term_id for c in search(candidate_term).candidates][:30]
    with db.connect() as conn:
        rows = conn.execute(f"SELECT {FIELDS} FROM standard_terms WHERE id=ANY(%s::uuid[]) AND status='ACTIVE' ORDER BY id", (ids,)).fetchall()
        descriptions = {r["code"]: r["description"] for r in conn.execute("SELECT code,description FROM domains WHERE status='ACTIVE'").fetchall()}
    found = {r["term_id"] for r in rows}
    missing = [x for x in ids if x not in found]
    for r in rows:
        r["domain_description"] = descriptions.get(r["domain"])
    counts = Counter(r["domain"] for r in rows)
    # Domain codes (e.g. "수N7") are not self-explanatory; carry the human-readable
    # description alongside each code so callers never have to show a bare code.
    distribution = [{"domain": name,"domain_description":descriptions.get(name),"count":count,"ratio":count/len(rows)}
        for name,count in sorted(counts.items(),key=lambda item:(-item[1],item[0]))]
    tied = len(distribution)>1 and distribution[0]["count"]==distribution[1]["count"]
    recommended = distribution[0]["domain"] if distribution and not tied else None
    return {"candidate_term":candidate_term,"recommended_domain":recommended,
        "recommended_domain_description":descriptions.get(recommended) if recommended else None,
        "confidence":distribution[0]["ratio"] if recommended else 0,
        "confidence_kind":"observed_usage_share_not_probability","sample_size":len(rows),
        "distribution":distribution,"evidence":rows,"missing_term_ids":missing,
        "known_domains":[{"code":c,"description":d} for c,d in sorted(descriptions.items())],
        "warnings":(["NO_COMPARISON_EVIDENCE"] if not rows else []) + (["TIED_DISTRIBUTION"] if tied else [])}
