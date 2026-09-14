"""Local administrator CLI. Catalog import is deliberately not an MCP tool."""
import argparse
import json
import re
import uuid
from pathlib import Path
from openpyxl import load_workbook
from term_service import db
from term_service.config import EMBEDDING_MODEL
from term_service.embeddings import embed
from term_service.naming import key, morphology

def import_catalog(path):
    data=json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not data.get("source") or not isinstance(data.get("terms",[]),list):
        raise ValueError("Expected source and terms array")
    terms=[]
    for row in data.get("terms",[]):
        if not all(isinstance(row.get(x),str) and row[x].strip() for x in ["name","definition","domain"]):
            raise ValueError("Each term requires name, definition, domain")
        if len(row["name"])>200 or len(row["definition"])>4000:
            raise ValueError("Catalog field too long")
        synonyms=row.get("synonyms",[])
        if not isinstance(synonyms,list) or any(not isinstance(s,str) for s in synonyms):
            raise ValueError("synonyms must be strings")
        vector=embed(row["name"]+" : "+row["definition"])
        nouns=[t["form"] for t in morphology(row["name"])["morphemes"] if t["tag"].startswith("N")]
        english_abbr=row.get("english_abbr") or None
        terms.append((str(uuid.uuid5(uuid.NAMESPACE_URL,data["source"]+"/"+key(row["name"]))),row["name"],key(row["name"]),
            row["definition"],row["domain"],synonyms,[key(s) for s in synonyms],nouns,data["source"],vector,EMBEDDING_MODEL,english_abbr))
    with db.connect() as conn:
        for domain in data.get("domains",[]):
            conn.execute("INSERT INTO domains(code,description,source) VALUES(%s,%s,%s) ON CONFLICT(code) DO UPDATE SET description=excluded.description,source=excluded.source",
                (domain["code"],domain.get("description",""),data["source"]))
        for alias in data.get("abbreviations",[]):
            conn.execute("INSERT INTO abbreviation_aliases(abbreviation,names,source) VALUES(%s,%s,%s) ON CONFLICT(abbreviation) DO UPDATE SET names=excluded.names,source=excluded.source",
                (key(alias["abbreviation"]),alias["names"],data["source"]))
        for row in terms:
            conn.execute("""INSERT INTO standard_terms(id,name,normalized_name,definition,domain,synonyms,normalized_synonyms,noun_tokens,source,embedding,embedding_model,english_abbr)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(normalized_name) DO UPDATE SET name=excluded.name,definition=excluded.definition,domain=excluded.domain,
                synonyms=excluded.synonyms,normalized_synonyms=excluded.normalized_synonyms,noun_tokens=excluded.noun_tokens,
                source=excluded.source,embedding=excluded.embedding,embedding_model=excluded.embedding_model,
                english_abbr=COALESCE(excluded.english_abbr,standard_terms.english_abbr),updated_at=now()""",row)
    print(json.dumps({"imported_terms":len(terms),"source":data["source"]},ensure_ascii=False))

def _cell(v):
    return "" if v in (None, "-") else str(v).strip()

def _split_list(v):
    text = _cell(v)
    return [s.strip() for s in text.split(",") if s.strip()] if text else []

def _int_or_none(v):
    return int(v) if isinstance(v, (int, float)) else None

def _revision_status(v):
    return "DEPRECATED" if _cell(v) == "폐기" else "ACTIVE"

def read_standard_catalog_xlsx(path):
    """Adapter over the government 공공데이터 공통표준 xlsx (data.go.kr): normalizes
    its three sheets (공통표준단어/공통표준도메인/공통표준용어) into plain dict
    lists so import_standard_catalog() never has to know the source was Excel -
    a future API-based sync only needs to produce this same {domains,words,terms}
    shape, not touch the import logic itself.
    """
    wb = load_workbook(path, read_only=True, data_only=True)
    domains, words, terms = {}, {}, {}
    for row in wb["공통표준도메인"].iter_rows(min_row=2, values_only=True):
        code = _cell(row[3]) if row else ""
        if not code:
            continue
        domains[code] = {"code": code, "description": _cell(row[4]),
            "domain_group": _cell(row[1]), "domain_classification": _cell(row[2]),
            "data_type": _cell(row[5]) or None, "data_length": _int_or_none(row[6]), "decimal_length": _int_or_none(row[7]),
            "storage_format": _cell(row[8]) or None, "display_format": _cell(row[9]) or None, "unit": _cell(row[10]) or None,
            "status": _revision_status(row[13])}
    for row in wb["공통표준단어"].iter_rows(min_row=2, values_only=True):
        name = _cell(row[1]) if row else ""
        if not name:
            continue
        words[key(name)] = {"name": name, "english_abbr": _cell(row[2]), "english_name": _cell(row[3]),
            "definition": _cell(row[4]), "is_format_word": _cell(row[5]) == "Y", "domain_classification": _cell(row[6]),
            "synonyms": _split_list(row[7]), "forbidden_words": _split_list(row[8]), "status": _revision_status(row[10])}
    for row in wb["공통표준용어"].iter_rows(min_row=2, values_only=True):
        name = _cell(row[1]) if row else ""
        if not name:
            continue
        terms[key(name)] = {"name": name, "definition": _cell(row[2]), "english_abbr": _cell(row[3]) or None,
            "domain": _cell(row[4]), "synonyms": _split_list(row[10]), "status": _revision_status(row[12])}
    return {"domains": list(domains.values()), "words": list(words.values()), "terms": list(terms.values())}

def import_standard_catalog(path):
    """Sync the government 공공데이터 공통표준 xlsx into domains/standard_words/
    standard_terms. Re-runnable as new revisions are released: 폐기 rows are
    upserted with status=DEPRECATED rather than deleted or skipped, so a term
    already registered against a domain the standard later retires keeps a
    valid FK and the deprecation itself stays visible instead of vanishing.
    A term whose name+definition text is byte-identical to what is already
    stored is updated everywhere except embedding/embedding_model/updated_at -
    a routine re-sync of an otherwise-unchanged catalog must not recompute
    13,000+ embeddings, and must not bump updated_at on rows nothing changed
    about, since db.catalog_fingerprint() hashes every row's (id,updated_at)
    and an unwarranted bump there would invalidate every in-flight
    registration_preparation across the whole system on the next prepare()/
    submit() check, not just ones touching the changed term.
    """
    data = read_standard_catalog_xlsx(path)
    source = "GOV_COMMON_STANDARD_2025_11"
    with db.connect() as conn:
        for d in data["domains"]:
            conn.execute("""INSERT INTO domains(code,description,source,domain_group,domain_classification,
                data_type,data_length,decimal_length,storage_format,display_format,unit,status)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(code) DO UPDATE SET description=excluded.description,source=excluded.source,
                domain_group=excluded.domain_group,domain_classification=excluded.domain_classification,
                data_type=excluded.data_type,data_length=excluded.data_length,decimal_length=excluded.decimal_length,
                storage_format=excluded.storage_format,display_format=excluded.display_format,unit=excluded.unit,
                status=excluded.status""",
                (d["code"],d["description"],source,d["domain_group"],d["domain_classification"],d["data_type"],
                 d["data_length"],d["decimal_length"],d["storage_format"],d["display_format"],d["unit"],d["status"]))
        known_domains = {r["code"] for r in conn.execute("SELECT code FROM domains").fetchall()}
        # Same incremental-embedding rule as terms below: a word whose name+definition
        # is unchanged (or whose embedding is already backfilled) skips re-embedding -
        # meaning-first word search (search_words()) needs these vectors, but a routine
        # re-sync of 3,000+ words must not recompute them all every time.
        existing_words = {r["normalized_name"]:(r["definition"],r["embedding"] is not None) for r in
            conn.execute("SELECT normalized_name,definition,embedding FROM standard_words").fetchall()}
        for w in data["words"]:
            nkey=key(w["name"])
            prev_definition,has_embedding=existing_words.get(nkey,(None,False))
            if prev_definition==w["definition"] and has_embedding:
                conn.execute("""UPDATE standard_words SET name=%s,english_abbr=%s,english_name=%s,
                    is_format_word=%s,domain_classification=%s,synonyms=%s,normalized_synonyms=%s,
                    forbidden_words=%s,status=%s,source=%s WHERE normalized_name=%s""",
                    (w["name"],w["english_abbr"],w["english_name"],w["is_format_word"],w["domain_classification"],
                     w["synonyms"],[key(s) for s in w["synonyms"]],w["forbidden_words"],w["status"],source,nkey))
                continue
            vector=embed(w["name"]+" : "+w["definition"]) if w["definition"] else embed(w["name"])
            conn.execute("""INSERT INTO standard_words(id,name,normalized_name,english_abbr,english_name,definition,
                is_format_word,domain_classification,synonyms,normalized_synonyms,forbidden_words,status,source,
                embedding,embedding_model)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(normalized_name) DO UPDATE SET name=excluded.name,english_abbr=excluded.english_abbr,
                english_name=excluded.english_name,definition=excluded.definition,is_format_word=excluded.is_format_word,
                domain_classification=excluded.domain_classification,synonyms=excluded.synonyms,
                normalized_synonyms=excluded.normalized_synonyms,forbidden_words=excluded.forbidden_words,
                status=excluded.status,source=excluded.source,embedding=excluded.embedding,
                embedding_model=excluded.embedding_model,updated_at=now()""",
                (str(uuid.uuid5(uuid.NAMESPACE_URL,source+"/word/"+nkey)),w["name"],nkey,
                 w["english_abbr"],w["english_name"],w["definition"],w["is_format_word"],w["domain_classification"],
                 w["synonyms"],[key(s) for s in w["synonyms"]],w["forbidden_words"],w["status"],source,
                 vector,EMBEDDING_MODEL))
        existing = {r["normalized_name"]:r["definition"] for r in
            conn.execute("SELECT normalized_name,definition FROM standard_terms").fetchall()}
        embedded=skipped_unchanged=0
        skipped_unknown_domain=[]
        for t in data["terms"]:
            nkey=key(t["name"])
            if t["domain"] not in known_domains:
                skipped_unknown_domain.append(t["name"])
                continue
            nouns=[m["form"] for m in morphology(t["name"])["morphemes"] if m["tag"].startswith("N")]
            normalized_synonyms=[key(s) for s in t["synonyms"]]
            if existing.get(nkey)==t["definition"]:
                conn.execute("""UPDATE standard_terms SET name=%s,domain=%s,synonyms=%s,normalized_synonyms=%s,
                    noun_tokens=%s,source=%s,english_abbr=COALESCE(%s,english_abbr),status=%s
                    WHERE normalized_name=%s""",
                    (t["name"],t["domain"],t["synonyms"],normalized_synonyms,nouns,source,t["english_abbr"],t["status"],nkey))
                skipped_unchanged+=1
                continue
            vector=embed(t["name"]+" : "+t["definition"])
            embedded+=1
            conn.execute("""INSERT INTO standard_terms(id,name,normalized_name,definition,domain,synonyms,
                normalized_synonyms,noun_tokens,source,embedding,embedding_model,english_abbr,status)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(normalized_name) DO UPDATE SET name=excluded.name,definition=excluded.definition,
                domain=excluded.domain,synonyms=excluded.synonyms,normalized_synonyms=excluded.normalized_synonyms,
                noun_tokens=excluded.noun_tokens,source=excluded.source,embedding=excluded.embedding,
                embedding_model=excluded.embedding_model,english_abbr=COALESCE(excluded.english_abbr,standard_terms.english_abbr),
                status=excluded.status,updated_at=now()""",
                (str(uuid.uuid5(uuid.NAMESPACE_URL,source+"/term/"+nkey)),t["name"],nkey,t["definition"],t["domain"],
                 t["synonyms"],normalized_synonyms,nouns,source,vector,EMBEDDING_MODEL,t["english_abbr"],t["status"]))
    print(json.dumps({"domains_imported":len(data["domains"]),"words_imported":len(data["words"]),
        "terms_total":len(data["terms"]),"terms_embedded":embedded,"terms_unchanged_skipped":skipped_unchanged,
        "terms_skipped_unknown_domain":len(skipped_unknown_domain),
        "sample_skipped_unknown_domain":skipped_unknown_domain[:10]},ensure_ascii=False))

def import_guideline(path):
    """Split standard_guide.md into per-section chunks and embed each one.
    Re-running re-embeds everything and upserts by section title, then deletes
    any stored section whose title is no longer present in the file - a full
    sync, not an accumulate-only import, so a renamed/removed heading (like
    "2. ..." becoming "2. ... (자동 검증 항목)") never leaves a stale duplicate
    chunk that a RAG lookup could still retrieve and judge against.
    """
    path=Path(path)
    text=path.read_text(encoding="utf-8-sig")
    source="SYNTHETIC_SCENARIO_V1_NOT_OFFICIAL"
    # Split on H2 ("## ") headings; the H1 title and the leading blockquote
    # disclaimer become part of the first chunk's context.
    parts=re.split(r"(?m)^##\s+",text)
    chunks=[]
    intro=parts[0].strip()
    if intro:
        chunks.append(("0. 개요",intro))
    for part in parts[1:]:
        title,_,body=part.partition("\n")
        chunks.append((title.strip(),body.strip()))
    if not chunks:
        raise ValueError("No sections found in guideline document")
    with db.connect() as conn:
        for section,content in chunks:
            vector=embed(section+" : "+content)
            conn.execute("""INSERT INTO guideline_chunks(id,section,content,embedding,embedding_model,source)
                VALUES(%s,%s,%s,%s,%s,%s)
                ON CONFLICT(section) DO UPDATE SET content=excluded.content,embedding=excluded.embedding,
                embedding_model=excluded.embedding_model,source=excluded.source,updated_at=now()""",
                (str(uuid.uuid5(uuid.NAMESPACE_URL,source+"/guideline/"+section)),section,content,vector,EMBEDDING_MODEL,source))
        current_sections=[c[0] for c in chunks]
        removed=conn.execute("DELETE FROM guideline_chunks WHERE NOT (section=ANY(%s)) RETURNING section",
            (current_sections,)).fetchall()
    print(json.dumps({"imported_sections":len(chunks),"sections":current_sections,
        "removed_stale_sections":[r["section"] for r in removed]},ensure_ascii=False))

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=["init-db","import-catalog","import-standard-catalog","import-guideline","health","export-schemas"])
    parser.add_argument("file",nargs="?")
    args=parser.parse_args()
    if args.command=="init-db":
        db.initialize()
    elif args.command=="import-catalog":
        import_catalog(args.file)
    elif args.command=="import-standard-catalog":
        import_standard_catalog(args.file)
    elif args.command=="import-guideline":
        import_guideline(args.file or Path(__file__).parent/"data/standard_guide.md")
    elif args.command=="health":
        from term_service.tools import terminology_health
        print(json.dumps(terminology_health(),ensure_ascii=False))
    else:
        from term_service import schemas
        output={name:cls.model_json_schema() for name,cls in vars(schemas).items() if isinstance(cls,type) and issubclass(cls,schemas.Schema) and cls is not schemas.Schema}
        Path(args.file or "schemas.json").write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
