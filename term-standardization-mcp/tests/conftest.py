"""Tests use a separate terms_test database. Production data is never truncated."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg
import pytest
from term_service import db

@pytest.fixture(scope="session",autouse=True)
def test_database():
    production=db.DATABASE_URL
    with psycopg.connect(production,autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname='terms_test'").fetchone():
            conn.execute("CREATE DATABASE terms_test")
    db.DATABASE_URL=production.rsplit("/",1)[0]+"/terms_test"
    db.initialize()
    yield
    db.DATABASE_URL=production

@pytest.fixture(autouse=True)
def clean_test_database(test_database):
    assert db.DATABASE_URL.endswith("/terms_test")
    with db.connect() as conn:
        conn.execute("TRUNCATE registration_requests,registration_preparations,word_registration_requests,word_registration_preparations,comparison_cache,conversation_state,standard_terms,standard_words,domains,abbreviation_aliases,guideline_chunks CASCADE")

@pytest.fixture
def catalog(tmp_path):
    import json
    from manage import import_catalog
    data={"source":"TEST_FIXTURE_NOT_PRODUCTION","domains":[{"code":"수N7","description":"테스트 숫자 도메인"},{"code":"명V100","description":"테스트 문자열"}],
        "abbreviations":[{"abbreviation":"BMI","names":["체질량지수"]}],
        "terms":[
          {"name":"일일섭취칼로리","definition":"한 사람이 하루 동안 음식으로 실제 섭취한 에너지의 총량","domain":"수N7","synonyms":["하루섭취열량"]},
          {"name":"일일권장열량","definition":"건강 유지를 위해 한 사람이 하루에 섭취하도록 권장되는 에너지 기준량","domain":"수N7","synonyms":["하루권장열량"]},
          {"name":"체질량지수","definition":"체중을 키의 제곱으로 나눈 신체 비만도 지표","domain":"수N7","synonyms":["BMI"]},
          {"name":"음식명","definition":"섭취한 음식의 이름","domain":"명V100","synonyms":[]}]}
    path=tmp_path/"catalog.json"
    path.write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8")
    import_catalog(path)
    with db.connect() as conn:
        return {r["name"]:str(r["id"]) for r in conn.execute("SELECT id,name FROM standard_terms").fetchall()}
