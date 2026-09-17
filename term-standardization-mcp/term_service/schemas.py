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

class WordSuggestion(Schema):
    # existing_word_match declared first, before ambiguous/name, so the model must
    # commit to "does an existing word already cover this meaning" before it can
    # write either a clarifying question or a brand-new word proposal - same
    # forced-intermediate-field trick as DefinitionSuggestion.ambiguous and
    # GuidelineJudgment.matched_forbidden_word. Meaning-first word search
    # (search_words()) is fuzzy, so this stops the model from BOTH claiming a
    # reuse-worthy match AND coining a new word in the same answer.
    existing_word_match: str = Field(default="", description=
        "The exact name of an existing standard word from candidate_existing_words "
        "that already means the same thing as usage_description, or empty string "
        "if none of them do - do not guess a word that isn't in that list.")
    match_reason: str = Field(default="", description="Only set when existing_word_match is non-empty: one short Korean sentence why it matches.")
    ambiguous: bool = Field(default=False, description=
        "Only relevant when existing_word_match is empty: true only if usage_description "
        "itself supports two or more genuinely distinct concepts that would need different "
        "words - not merely because a fully specific name requires domain detail.")
    question: str = Field(default="", description="Only set when ambiguous=true: a short Korean question naming the fork.")
    options: list[str] = Field(default_factory=list, max_length=4,
        description="Only set when ambiguous=true: 2-4 short Korean labels, each a candidate meaning.")
    name: str = Field(default="", description="Only set when existing_word_match is empty and ambiguous=false: a new Korean standard-word name (a single concept, not a full term).")
    english_abbr: str = Field(default="", description="Only set alongside name: the new word's English abbreviation, uppercase letters/digits/underscores only, 3-5 letters.")
    is_format_word: bool = Field(default=False, description="Only set alongside name: true if this word by itself already implies a data format/domain (a 분류어 like 코드/명/수), false otherwise.")
    definition: str = Field(default="", description="Only set alongside name: a confident one-sentence Korean definition of the new word.")
    rationale: str = Field(default="", description="One short Korean sentence: why this match, this question, or this new word.")

class WordSuggestionResult(WordSuggestion):
    method: str
    model: str | None = None
    error_code: str | None = None
    # Only populated (by code, never by the model - see suggest_word()) when
    # existing_word_match is set: the matched word's own english_name/domain_classification,
    # so a reuse decision can be made from the full record instead of just a bare name. Not
    # on WordSuggestion itself so the LLM's structured-output contract for the new-word case
    # is untouched - a freshly coined word never has these assigned at this stage anyway.
    english_name: str = ""
    domain_classification: str = ""

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

class WordRegistrationInput(Schema):
    word_name: str = Field(min_length=1, max_length=20)
    definition: str = Field(min_length=5, max_length=4000)
    english_abbr: str = Field(min_length=1, max_length=20)
    is_format_word: bool = False
    domain_classification: str = Field(default="", max_length=100)
    requester: str = Field(min_length=1, max_length=200)
    conversation_id: str = Field(min_length=1, max_length=200)

class DomainRequestInput(Schema):
    """Direct-form (non-chatbot) domain application - see term_service/domain_registration.py."""
    code: str = Field(min_length=1, max_length=50)
    domain_group: str = Field(min_length=1, max_length=100)
    physical_name: str = Field(default="", max_length=200)
    data_type: str = Field(min_length=1, max_length=50)
    data_length: int | None = Field(default=None, ge=0, le=100000)
    decimal_length: int | None = Field(default=None, ge=0, le=100)
    min_value: str = Field(default="", max_length=200)
    max_value: str = Field(default="", max_length=200)
    display_format: str = Field(default="", max_length=100)
    source_classification: str = Field(default="", max_length=100)
    valid_values: str = Field(default="", max_length=2000)
    default_value: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=2000)
    is_personal_info: bool = False
    personal_info_type: str = Field(default="", max_length=100)
    protection_level: str = Field(default="", max_length=100)
    is_encrypted: bool = False
    encryption_method: str = Field(default="", max_length=100)
    mapping_table: str = Field(default="", max_length=100)
    mapping_column: str = Field(default="", max_length=100)
    request_reason: str = Field(default="", max_length=2000)
    requester: str = Field(min_length=1, max_length=200)
    conversation_id: str = Field(min_length=1, max_length=200)
