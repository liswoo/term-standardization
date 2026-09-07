"""Local administrator CLI. Catalog import is deliberately not an MCP tool."""
import argparse
import json
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
        terms.append((str(uuid.uuid5(uuid.NAMESPACE_URL,data["source"]+"/"+key(row["name"]))),row["name"],key(row["name"]),
            row["definition"],row["domain"],synonyms,[key(s) for s in synonyms],nouns,data["source"],vector,EMBEDDING_MODEL))
    with db.connect() as conn:
        for domain in data.get("domains",[]):
            conn.execute("INSERT INTO domains(code,description,source) VALUES(%s,%s,%s) ON CONFLICT(code) DO UPDATE SET description=excluded.description,source=excluded.source",
                (domain["code"],domain.get("description",""),data["source"]))
        for alias in data.get("abbreviations",[]):
            conn.execute("INSERT INTO abbreviation_aliases(abbreviation,names,source) VALUES(%s,%s,%s) ON CONFLICT(abbreviation) DO UPDATE SET names=excluded.names,source=excluded.source",
                (key(alias["abbreviation"]),alias["names"],data["source"]))
        for row in terms:
            conn.execute("""INSERT INTO standard_terms(id,name,normalized_name,definition,domain,synonyms,normalized_synonyms,noun_tokens,source,embedding,embedding_model)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(normalized_name) DO UPDATE SET name=excluded.name,definition=excluded.definition,domain=excluded.domain,
                synonyms=excluded.synonyms,normalized_synonyms=excluded.normalized_synonyms,noun_tokens=excluded.noun_tokens,
                source=excluded.source,embedding=excluded.embedding,embedding_model=excluded.embedding_model,updated_at=now()""",row)
    print(json.dumps({"imported_terms":len(terms),"source":data["source"]},ensure_ascii=False))

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=["init-db","import-catalog","health","export-schemas"])
    parser.add_argument("file",nargs="?")
    args=parser.parse_args()
    if args.command=="init-db":
        db.initialize()
    elif args.command=="import-catalog":
        import_catalog(args.file)
    elif args.command=="health":
        from term_service.tools import terminology_health
        print(json.dumps(terminology_health(),ensure_ascii=False))
    else:
        from term_service import schemas
        output={name:cls.model_json_schema() for name,cls in vars(schemas).items() if isinstance(cls,type) and issubclass(cls,schemas.Schema) and cls is not schemas.Schema}
        Path(args.file or "schemas.json").write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
