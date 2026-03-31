from pydantic import BaseModel, ConfigDict, Field, field_validator


class _StructuredBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def _stringify(cls, value):
        if value is None:
            return ""
        return str(value).strip() if isinstance(value, str | bytes) else value


class QuestionAnswer(_StructuredBase):
    answer: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    question_issue: str = ""


class CoverLetter(_StructuredBase):
    paragraph_one: str = ""
    paragraph_two: str = ""


class ContactExtraction(_StructuredBase):
    name: str = ""
    email: str = ""
    phone: str = ""
