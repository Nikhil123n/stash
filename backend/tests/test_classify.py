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


class FakeGenerationConfig(dict):
    """Dictionary-backed stand-in for Vertex GenerationConfig."""


class FakeGenerativeModel:
    """Minimal Vertex GenerativeModel stand-in with configurable response text."""

    response_text: str = "{}"
    response_texts: list[str] = []
    generate_content_mock = Mock()

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def generate_content(self, prompt_or_parts: object, **kwargs: object) -> SimpleNamespace:
        """Return a fake Gemini response."""
        self.__class__.generate_content_mock(prompt_or_parts, **kwargs)
        response_text = (
            self.__class__.response_texts.pop(0)
            if self.__class__.response_texts
            else self.__class__.response_text
        )
        return SimpleNamespace(text=response_text)


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
    FakeGenerativeModel.response_texts = []
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

    expected = {
        "title": "FastAPI Webhooks",
        "summary": "A practical note about receiving Telegram webhooks.",
        "tags": ["fastapi", "telegram", "backend"],
        "category": "Coding",
        "is_new_category": False,
        "confidence": 0.91,
        "needs_review": False,
    }
    assert {key: result[key] for key in expected} == expected
    assert result["ai_audit"]["prompt_version"] == classify.CLASSIFICATION_PROMPT_VERSION
    assert result["ai_audit"]["generation_config"]["temperature"] == 0
    assert result["ai_audit"]["generation_config"]["top_p"] == 1
    assert result["ai_audit"]["generation_config"]["candidate_count"] == 1
    assert result["ai_audit"]["generation_config"]["max_output_tokens"] == 1024
    assert result["ai_audit"]["generation_config"]["response_mime_type"] == "application/json"
    assert result["ai_audit"]["generation_config"]["response_schema_enforced"] is True
    FakeGenerativeModel.generate_content_mock.assert_called_once()
    generation_config = FakeGenerativeModel.generate_content_mock.call_args.kwargs["generation_config"]
    assert generation_config["response_mime_type"] == "application/json"
    assert "response_schema" in generation_config


def test_json_parse_error_raises_classification_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid Gemini JSON is wrapped as a ClassificationError by classifier calls."""
    classify = import_classify_with_fake_vertex(monkeypatch)
    FakeGenerativeModel.response_text = "not-json"

    with pytest.raises(classify.ClassificationError):
        classify.classify_text("bad response example", ["Coding"])
    assert FakeGenerativeModel.generate_content_mock.call_count == 3


def test_invalid_response_retries_until_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Classifier retries invalid model JSON before returning a valid later response."""
    classify = import_classify_with_fake_vertex(monkeypatch)
    FakeGenerativeModel.response_texts = [
        "not-json",
        """
        {
          "title": "Retry Success",
          "summary": "The second response is valid JSON.",
          "tags": ["retry", "json"],
          "category": "Coding",
          "is_new_category": false,
          "confidence": 0.8
        }
        """,
    ]

    result = classify.classify_text("retry example", ["Coding"])

    assert result["category"] == "Coding"
    assert result["ai_audit"]["retry_count"] == 1
    assert FakeGenerativeModel.generate_content_mock.call_count == 2


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


def test_video_url_classification_uses_video_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Video URL classification sends the actual video bytes to Gemini."""
    classify = import_classify_with_fake_vertex(monkeypatch)
    FakeGenerativeModel.response_text = """
    {
      "title": "Desk Setup Reel",
      "summary": "A short reel showing a compact productivity desk setup.",
      "tags": ["desk setup", "productivity", "workspace", "lighting"],
      "category": "Productivity",
      "is_new_category": false,
      "confidence": 0.95,
      "content_details": "Shows a laptop stand, monitor light, keyboard, and cable management."
    }
    """

    result = classify.classify_url(
        og_title="Instagram reel",
        og_description="Desk vibes",
        url="https://www.instagram.com/reel/example",
        existing_categories=["Productivity"],
        is_video=True,
        video_bytes=b"fake-video",
        video_mime_type="video/mp4",
    )
    prompt_or_parts = FakeGenerativeModel.generate_content_mock.call_args.args[0]

    assert result["category"] == "Productivity"
    assert result["content_details"].startswith("Shows a laptop stand")
    assert prompt_or_parts[0] == (b"fake-video", "video/mp4")
    assert "The video content is the source of truth" in prompt_or_parts[1]
