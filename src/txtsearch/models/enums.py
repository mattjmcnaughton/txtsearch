from enum import StrEnum


class SourceType(StrEnum):
    FILE = "file"
    WEB = "web"
    GENERATED = "generated"


class SearchStrategy(StrEnum):
    SEMANTIC = "semantic"
    LEXICAL = "lexical"
    LITERAL = "literal"
    AGENTIC = "agentic"
