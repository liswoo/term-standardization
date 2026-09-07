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
