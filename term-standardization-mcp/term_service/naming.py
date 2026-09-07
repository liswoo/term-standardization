import re
import unicodedata
from functools import lru_cache
from threading import RLock
from kiwipiepy import Kiwi
from .schemas import TermInput, ValidationResult, Violation

_lock = RLock()

def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text).strip()

def key(text: str) -> str:
    return re.sub(r"\s+", "", normalize(text)).casefold()

@lru_cache(maxsize=1)
def kiwi():
    return Kiwi(num_workers=1)

def morphology(text: str) -> dict:
    TermInput(term=text)
    with _lock:
        tokens = kiwi().tokenize(normalize(text))
    return {"input": text, "engine": "kiwipiepy", "morphemes": [
        {"form": t.form, "tag": t.tag, "start": t.start, "length": t.len} for t in tokens
    ]}

def validate(term: str, aliases: dict[str, list[str]] | None = None) -> ValidationResult:
    TermInput(term=term)
    name = normalize(term)
    # Only a parenthesized ASCII abbreviation is permitted alongside a Korean name.
    core = re.sub(r"\([A-Za-z][A-Za-z0-9 .-]*\)$", "", name).strip()
    tokens = morphology(core)["morphemes"] if core else []
    violations = []
    suggestions = []
    if len(re.sub(r"\s+", "", name)) < 2 or len(name) > 20:
        violations.append(Violation(code="NAME_LENGTH", reason="Non-space length must be >=2; total length must be <=20."))
    if not re.search(r"[가-힣]", core):
        violations.append(Violation(code="KOREAN_NOUN_REQUIRED", reason="A Korean noun name is required."))
    if not re.fullmatch(r"[가-힣\s]+", core) or core != name and not re.fullmatch(r"[가-힣\s]+\([A-Za-z][A-Za-z0-9 .-]*\)", name):
        violations.append(Violation(code="INVALID_CHARACTERS", reason="Only Korean nouns, spaces and a trailing parenthesized abbreviation are allowed."))
    if not re.search(r"[가-힣A-Za-z]", name):
        violations.append(Violation(code="NO_MEANINGFUL_NAME", reason="A name cannot consist solely of numbers or symbols."))
    if tokens:
        last = tokens[-1]
        if last["tag"].startswith("J") and last["form"] in {"을", "를", "이", "가", "은", "는"}:
            violations.append(Violation(code="TRAILING_PARTICLE", reason="A grammatical case/topic particle cannot terminate a term."))
            suggestions.append(core[:last["start"]].strip())
        elif last["tag"] not in {"NNG", "NNP", "NNB", "NP", "XSN"}:
            violations.append(Violation(code="NOUN_ENDING_REQUIRED", reason="The final morpheme must be nominal."))
    for candidate in (aliases or {}).get(key(name), []):
        suggestions.extend([candidate, f"{candidate}({name})"] if re.fullmatch("[A-Za-z]+", name) else [candidate])
    return ValidationResult(valid=not violations, normalized_term=name, violations=violations,
        suggestions=list(dict.fromkeys(s for s in suggestions if s and s != name and len(s) <= 20)), morphemes=tokens)
