from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
import unicodedata

class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class TermInput(Schema):
    term: str = Field(min_length=1, max_length=200)

class SearchInput(TermInput):
    definition: str = Field(default="", max_length=4000)
    limit: int = Field(default=10, ge=1, le=30)

class Violation(Schema):
    code: str
    reason: str

class ValidationResult(Schema):
    valid: bool
    normalized_term: str
    violations: list[Violation]
    suggestions: list[str]
    morphemes: list[dict]

class Candidate(Schema):
    term_id: str
    name: str
    definition: str
    domain: str
    source: str = ""
    synonyms: list[str] = Field(default_factory=list)
    similarity: float | None = None
    evidence_type: str = ""
    english_abbr: str | None = None

class SearchResult(Schema):
    match_type: Literal["EXACT_MATCH", "SYNONYM_MATCH", "SEMANTIC_SIMILAR", "NEW_TERM", "UNDETERMINED"]
    query_term: str
    exact_matches: list[Candidate] = Field(default_factory=list)
    synonym_matches: list[Candidate] = Field(default_factory=list)
    semantic_matches: list[Candidate] = Field(default_factory=list)
    lexical_matches: list[Candidate] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    search_complete: bool = True
    corpus_count: int = 0
    warnings: list[str] = Field(default_factory=list)

class DefinitionJudgment(Schema):
    relation: Literal["SAME_MEANING", "RELATED_BUT_DISTINCT", "DISTINCT", "UNCERTAIN"]
    confidence: float = Field(ge=0, le=1)
    reason: str
    differences: list[str]

class ComparisonResult(DefinitionJudgment):
    existing_term_id: str
    recommended_action: Literal["USE_EXISTING", "CREATE_NEW", "REVIEW_REQUIRED"]
    method: str
    model: str | None = None
    definition_similarity: float | None = None
    error_code: str | None = None

class GuidelineChunk(Schema):
    section: str
    content: str
    similarity: float

class GuidelineJudgment(Schema):
    # Forces the intermediate step into the output itself (structured-output fields
    # are filled in declaration order) instead of letting the model jump straight to
    # a vibes-based compliant verdict - a small model kept reasoning "the word feels
    # broad" into a violation even when told in prose to check exact equality only.
    matched_forbidden_word: str = Field(default="",
        description="The single word from the excerpts' forbidden-word list that the "
        "candidate term's ENTIRE string is character-for-character identical to, or "
        "empty string if the candidate does not exactly equal any such word.")
    compliant: bool
    violated_section: str = ""
    reason: str
    suggested_term: str = ""

class GuidelineCheckResult(GuidelineJudgment):
    method: str
    model: str | None = None
    evidence: list[GuidelineChunk] = Field(default_factory=list)
    error_code: str | None = None

class AbbreviationSuggestion(Schema):
    abbreviation: str
    rationale: str

class AbbreviationResult(Schema):
    abbreviation: str
    rationale: str
    method: str
    model: str | None = None
    error_code: str | None = None

class DefinitionSuggestion(Schema):
    # ambiguous declared first so the model must commit to that judgment before
    # it can write either a confident definition or a clarifying question -
    # the same forced-intermediate-field trick used for GuidelineJudgment,
    # since asking a small model to "only ask a question when genuinely
    # ambiguous, otherwise write a confident definition" in prose alone is
    # exactly the kind of instruction it tends to blur together.
    ambiguous: bool = Field(description=
        "true only if term_name has two or more genuinely distinct plausible "
        "real-world meanings that would need different definitions - not merely "
        "because a fully specific definition requires domain knowledge.")
    question: str = Field(default="", description="Only set when ambiguous=true: a short Korean question naming the fork.")
    options: list[str] = Field(default_factory=list, max_length=4,
        description="Only set when ambiguous=true: 2-4 short Korean labels, each a candidate meaning.")
    definition: str = Field(default="", description="Only set when ambiguous=false: a confident one-to-two sentence Korean definition.")
    rationale: str = Field(default="", description="One short Korean sentence: why this definition or why this is ambiguous.")

class DefinitionSuggestionResult(DefinitionSuggestion):
    method: str
    model: str | None = None
    error_code: str | None = None

class RegistrationInput(Schema):
    term_name: str = Field(min_length=2, max_length=20)
    definition: str = Field(min_length=5, max_length=4000)
    domain: str = Field(min_length=1, max_length=100)
    synonyms: list[str] = Field(default_factory=list, max_length=30)
    requester: str = Field(min_length=1, max_length=200)
    conversation_id: str = Field(min_length=1, max_length=200)

    @field_validator("synonyms")
    @classmethod
    def clean_synonyms(cls, values):
        cleaned = list(dict.fromkeys(unicodedata.normalize("NFC", x.strip()) for x in values))
        if any(not x or len(x) > 100 for x in cleaned):
            raise ValueError("Each synonym must contain 1 to 100 characters")
        return cleaned
