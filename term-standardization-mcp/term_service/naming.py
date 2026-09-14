import re
import unicodedata
from functools import lru_cache
from threading import RLock
from kiwipiepy import Kiwi
from .schemas import TermInput, ValidationResult, Violation

_lock = RLock()

# Grammatical case/topic particles that attach directly to a noun with no space
# (e.g. "값을", "용어는") and can never be part of the term itself. Shared by
# validate() (post-hoc violation) and strip_trailing_particle() (pre-hoc cleanup).
TRAILING_PARTICLES = {"을", "를", "이", "가", "은", "는"}

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

def segment_words(term_name: str, word_lookup: dict) -> tuple[list, bool]:
    """Greedy longest-match segmentation of term_name against known standard_words.

    Returns (matched_word_rows_in_order, full_match) where full_match is True
    only if every character of the normalized name was consumed by a known
    word with nothing left over (no gaps). A partial result (full_match=False)
    still reports whichever words WERE recognized - grounding for an LLM
    fallback (abbreviation.py) or a signal that a genuinely new word is needed
    (conversation.py's word-registration entry point).

    word_lookup maps normalized_name -> a row dict for that standard_words entry.
    """
    text = key(term_name)
    max_len = max((len(w) for w in word_lookup), default=0)
    i, n, matched, full = 0, len(text), [], True
    while i < n:
        found = 0
        for length in range(min(max_len, n - i), 0, -1):
            candidate = word_lookup.get(text[i:i + length])
            if candidate:
                matched.append(candidate)
                found = length
                break
        if found:
            i += found
        else:
            full = False
            i += 1
    return matched, full and bool(matched)

def strip_trailing_particle(text: str) -> str:
    """Drop a single trailing case/topic particle attached to a noun (e.g. '값을' -> '값').
    This is extraction cleanup for raw user phrasing ("값을 신규 용어로 등록해줘"), not
    naming-rule enforcement: the particle is grammatically part of the request sentence,
    never the term the user actually wants, so it should never reach term_name in the
    first place. validate()'s TRAILING_PARTICLE violation stays as a downstream safety
    net for whatever slips past this (e.g. a term re-typed later in the flow).
    """
    name = normalize(text)
    if not name:
        return name
    tokens = morphology(name)["morphemes"]
    if tokens:
        last = tokens[-1]
        if last["tag"].startswith("J") and last["form"] in TRAILING_PARTICLES:
            trimmed = name[:last["start"]].strip()
            if trimmed:
                return trimmed
    return name

def validate(term: str, aliases: dict[str, list[str]] | None = None) -> ValidationResult:
    TermInput(term=term)
    name = normalize(term)
    # Only a parenthesized ASCII abbreviation is permitted alongside a Korean name.
    core = re.sub(r"\([A-Za-z][A-Za-z0-9 .-]*\)$", "", name).strip()
    tokens = morphology(core)["morphemes"] if core else []
    violations = []
    suggestions = []
    # Reasons are written in Korean (not just the code) so the reply-rendering LLM
    # can quote them verbatim instead of translating/paraphrasing an English string
    # on the fly - a small model asked to improvise that translation was prone to
    # substituting a plausible-sounding but wrong rule (e.g. explaining a length
    # violation as if it were the noun-ending rule instead).
    if len(re.sub(r"\s+", "", name)) < 2 or len(name) > 20:
        violations.append(Violation(code="NAME_LENGTH", reason="공백을 제외한 글자 수는 2자 이상, 전체 글자 수는 20자 이하여야 합니다."))
    if not re.search(r"[가-힣]", core):
        violations.append(Violation(code="KOREAN_NOUN_REQUIRED", reason="한글 명사로 작성해야 합니다."))
    if not re.fullmatch(r"[가-힣\s]+", core) or core != name and not re.fullmatch(r"[가-힣\s]+\([A-Za-z][A-Za-z0-9 .-]*\)", name):
        violations.append(Violation(code="INVALID_CHARACTERS", reason="한글 명사, 공백, 그리고 뒤에 붙는 영문 약어 괄호 표기 외에는 사용할 수 없습니다."))
    if not re.search(r"[가-힣A-Za-z]", name):
        violations.append(Violation(code="NO_MEANINGFUL_NAME", reason="숫자나 기호만으로는 용어명을 구성할 수 없습니다."))
    if tokens:
        last = tokens[-1]
        if last["tag"].startswith("J") and last["form"] in TRAILING_PARTICLES:
            violations.append(Violation(code="TRAILING_PARTICLE", reason="조사(을/를/이/가/은/는)로 끝날 수 없습니다."))
            suggestions.append(core[:last["start"]].strip())
        elif last["tag"] not in {"NNG", "NNP", "NNB", "NP", "XSN"}:
            violations.append(Violation(code="NOUN_ENDING_REQUIRED", reason="마지막 형태소가 명사형이어야 합니다."))
    for candidate in (aliases or {}).get(key(name), []):
        suggestions.extend([candidate, f"{candidate}({name})"] if re.fullmatch("[A-Za-z]+", name) else [candidate])
    return ValidationResult(valid=not violations, normalized_term=name, violations=violations,
        suggestions=list(dict.fromkeys(s for s in suggestions if s and s != name and len(s) <= 20)), morphemes=tokens)
