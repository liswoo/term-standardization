"""Local administrator CLI. Catalog import is deliberately not an MCP tool."""
import argparse
import json
import re
import uuid
from pathlib import Path
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
    parser.add_argument("command",choices=["init-db","import-catalog","import-guideline","health","export-schemas"])
    parser.add_argument("file",nargs="?")
    args=parser.parse_args()
    if args.command=="init-db":
        db.initialize()
    elif args.command=="import-catalog":
        import_catalog(args.file)
    elif args.command=="import-guideline":
        import_guideline(args.file or Path(__file__).parent/"data/standard_guide.md")
    elif args.command=="health":
        from term_service.tools import terminology_health
        print(json.dumps(terminology_health(),ensure_ascii=False))
    else:
        from term_service import schemas
        output={name:cls.model_json_schema() for name,cls in vars(schemas).items() if isinstance(cls,type) and issubclass(cls,schemas.Schema) and cls is not schemas.Schema}
        Path(args.file or "schemas.json").write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
