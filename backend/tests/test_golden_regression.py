"""Golden classification fixtures for LLM consistency regression checks."""

from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

FIXTURE_PATH = Path(__file__).with_name("golden_classification_fixtures.json")


class FakePart:
    """Minimal multimodal Part stand-in."""

    @staticmethod
    def from_data(data: bytes, mime_type: str) -> tuple[bytes, str]:
        """Return an inspectable media tuple."""
        return data, mime_type


class FakeGenerationConfig(dict):
    """Dictionary-backed stand-in for Vertex GenerationConfig."""


class FakeGenerativeModel:
    """Fake Gemini model returning a fixture-specific JSON response."""

    response_text = "{}"
    generate_content_mock = Mock()

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def generate_content(self, prompt_or_parts: object, **kwargs: object) -> SimpleNamespace:
        """Return the configured fixture response."""
        self.__class__.generate_content_mock(prompt_or_parts, **kwargs)
        return SimpleNamespace(text=self.__class__.response_text)


def import_classify_with_fake_vertex(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Import ai.classify with fake Vertex AI modules installed."""
    fake_vertexai = types.ModuleType("vertexai")
    fake_vertexai.init = Mock()

    fake_models = types.ModuleType("vertexai.generative_models")
    fake_models.GenerativeModel = FakeGenerativeModel
    fake_models.GenerationConfig = FakeGenerationConfig
    fake_models.Part = FakePart

    monkeypatch.setitem(sys.modules, "vertexai", fake_vertexai)
    monkeypatch.setitem(sys.modules, "vertexai.generative_models", fake_models)
    sys.modules.pop("ai.classify", None)
    sys.modules.pop("ai.consistency", None)
    FakeGenerativeModel.generate_content_mock.reset_mock()
    return importlib.import_module("ai.classify")


def golden_fixtures() -> list[dict[str, Any]]:
    """Load golden classification fixtures."""
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _fixture_response(fixture: dict[str, Any]) -> str:
    """Build a deterministic fake Gemini response from the fixture expectation."""
    expected = fixture["expected"]
    confidence = round((expected["confidence_min"] + expected["confidence_max"]) / 2, 2)
    return json.dumps(
        {
            "title": fixture["id"].replace("_", " ").title(),
            "summary": f"Golden regression fixture for {fixture['input_type']}.",
            "tags": expected["tags"],
            "category": expected["category"],
            "is_new_category": False,
            "confidence": confidence,
            "content_details": "Golden fixture detail.",
        }
    )


def _classify_fixture(classify: types.ModuleType, fixture: dict[str, Any]) -> dict[str, Any]:
    """Route a fixture through the matching public classifier."""
    input_type = fixture["input_type"]
    existing_categories = fixture["existing_categories"]
    if input_type == "text":
        return classify.classify_text(fixture["content"], existing_categories)
    if input_type == "image":
        return classify.classify_image(
            b"fake-image",
            fixture["caption"],
            existing_categories,
        )
    if input_type == "screenshot":
        return classify.classify_image(
            b"fake-screenshot",
            fixture["caption"],
            existing_categories,
            source_type="screenshot",
            extraction_source="screenshot_bytes",
        )
    if input_type in {"instagram_url", "linkedin_url"}:
        return classify.classify_url(
            og_title=fixture["title"],
            og_description=fixture["description"],
            url=fixture["url"],
            existing_categories=existing_categories,
            source_type=input_type,
            content_text=fixture["content_text"],
        )
    if input_type == "video_transcript":
        return classify.classify_from_transcript(fixture["transcript"], existing_categories)
    raise AssertionError(f"Unsupported fixture input_type: {input_type}")


@pytest.mark.parametrize("fixture", golden_fixtures(), ids=lambda fixture: fixture["id"])
def test_golden_classification_fixture(monkeypatch: pytest.MonkeyPatch, fixture: dict[str, Any]) -> None:
    """Fixture classifications must stay within expected category/tag/confidence bounds."""
    classify = import_classify_with_fake_vertex(monkeypatch)
    FakeGenerativeModel.response_text = _fixture_response(fixture)

    result = _classify_fixture(classify, fixture)
    expected = fixture["expected"]

    assert result["category"] == expected["category"]
    assert set(expected["tags"]).issubset(set(result["tags"]))
    assert expected["confidence_min"] <= result["confidence"] <= expected["confidence_max"]
    assert result["ai_audit"]["input_modality"] == expected["input_modality"]
    assert result["ai_audit"]["prompt_hash"]
    assert result["ai_audit"]["generation_config"]["temperature"] == 0
    assert result["ai_audit"]["generation_config"]["response_schema_enforced"] is True
