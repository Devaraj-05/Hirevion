"""AI answers that are cut to size instead of refused. The extraction schemas cap every text and
list, so the prompt and the validator agree; but a model that writes a 600-character quote or 41
achievements should lose the overflow, not the whole resume."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator


class Trimmed(BaseModel):
    """A model whose strings and lists longer than their `max_length` are cut to it before
    they are validated."""

    @model_validator(mode="before")
    @classmethod
    def _cut_to_size(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        cut = dict(data)
        for name, field in cls.model_fields.items():
            value = cut.get(name)
            if not isinstance(value, (str, list)):
                continue
            limit = next(
                (m.max_length for m in field.metadata if getattr(m, "max_length", None)), None
            )
            if limit is not None:
                cut[name] = value[:limit]
        return cut
