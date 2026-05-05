"""Tests for Gemini classification response handling."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class FakePart:
    """Minimal Vertex Part stand-in for image classification tests."""

    @staticmethod
    def from_data(data: bytes, mime_type: str) -> tuple[bytes, str]:
        """Return a simple tuple so tests can inspect generated content."""
        return data, mime_type


class FakeGenerativeModel:
    """Minimal Vertex GenerativeModel stand-in with configurable response text."""

    response_text: str = "{}"
    generate_content_mock = Mock()

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def generate_content(self, prompt_or_parts: object) -> SimpleNamespace:
        """Return a fake Gemini response."""
        self.__class__.generate_content_mock(prompt_or_parts)
        return SimpleNamespace(text=self.__class__.response_text)


def import_classify_with_fake_vertex(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Import ai.classify with fake Vertex AI modules installed."""
    fake_vertexai = types.ModuleType("vertexai")
    fake_vertexai.init = Mock()

    fake_models = types.ModuleType("vertexai.generative_models")
    fake_models.GenerativeModel = FakeGenerativeModel
    fake_models.Part = FakePart

    monkeypatch.setitem(sys.modules, "vertexai", fake_vertexai)
    monkeypatch.setitem(sys.modules, "vertexai.generative_models", fake_models)
    sys.modules.pop("ai.classify", None)
    FakeGenerativeModel.generate_content_mock.reset_mock()
    return importlib.import_module("ai.classify")


def test_valid_classification(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid Gemini response is parsed into a ClassificationResult."""
    classify = import_classify_with_fake_vertex(monkeypatch)
    FakeGenerativeModel.response_text = """
    ```json
    {
      "title": "FastAPI Webhooks",
      "summary": "A practical note about receiving Telegram webhooks.",
      "tags": ["fastapi", "telegram", "backend"],
      "category": "Coding",
      "is_new_category": false,
      "confidence": 0.91
    }
    ```
    """

    result = classify.classify_text("Telegram webhook implementation notes", ["Coding", "Design"])

    assert result == {
        "title": "FastAPI Webhooks",
        "summary": "A practical note about receiving Telegram webhooks.",
        "tags": ["fastapi", "telegram", "backend"],
        "category": "Coding",
        "is_new_category": False,
        "confidence": 0.91,
        "needs_review": False,
    }
    FakeGenerativeModel.generate_content_mock.assert_called_once()


def test_json_parse_error_raises_classification_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid Gemini JSON is wrapped as a ClassificationError by classifier calls."""
    classify = import_classify_with_fake_vertex(monkeypatch)
    FakeGenerativeModel.response_text = "not-json"

    with pytest.raises(classify.ClassificationError):
        classify.classify_text("bad response example", ["Coding"])


def test_new_category_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    """New-category responses preserve is_new_category and empty-list prompt guidance."""
    classify = import_classify_with_fake_vertex(monkeypatch)
    FakeGenerativeModel.response_text = """
    {
      "title": "Meal Prep Ideas",
      "summary": "A cooking note about planning healthy meals.",
      "tags": ["meal prep", "nutrition", "recipes"],
      "category": "Food & Recipes",
      "is_new_category": true,
      "confidence": 0.88
    }
    """

    result = classify.classify_text("Simple meal prep ideas", [])
    prompt = FakeGenerativeModel.generate_content_mock.call_args.args[0]

    assert result["category"] == "Food & Recipes"
    assert result["is_new_category"] is True
    assert "No categories exist yet" in prompt


def test_low_confidence_sets_needs_review(monkeypatch: pytest.MonkeyPatch) -> None:
    """Confidence below 0.7 sets needs_review to True."""
    classify = import_classify_with_fake_vertex(monkeypatch)
    FakeGenerativeModel.response_text = """
    {
      "title": "Ambiguous Save",
      "summary": "The content is too vague to categorize confidently.",
      "tags": ["unclear", "misc", "review"],
      "category": "Other",
      "is_new_category": false,
      "confidence": 0.42
    }
    """

    result = classify.classify_text("maybe useful later", ["Other"])

    assert result["confidence"] == 0.42
    assert result["needs_review"] is True


def test_url_classification_uses_extracted_page_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """URL prompts include extracted page text so classification is not based only on the host."""
    classify = import_classify_with_fake_vertex(monkeypatch)
    FakeGenerativeModel.response_text = """
    {
      "title": "Bread Fermentation Notes",
      "summary": "An article about sourdough fermentation timing and temperature.",
      "tags": ["sourdough", "fermentation", "baking"],
      "category": "Food & Recipes",
      "is_new_category": true,
      "confidence": 0.93
    }
    """

    result = classify.classify_url(
        og_title="Generic Website Title",
        og_description="A generic homepage description.",
        url="https://example.com/article",
        existing_categories=["Social Media"],
        content_text="This article explains sourdough fermentation, starter activity, and dough temperature.",
        site_name="Example",
    )
    prompt = FakeGenerativeModel.generate_content_mock.call_args.args[0]

    assert result["category"] == "Food & Recipes"
    assert "Extracted page content" in prompt
    assert "sourdough fermentation" in prompt
    assert "Classify the substance" in prompt
