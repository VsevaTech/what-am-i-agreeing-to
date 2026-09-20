"""AI layer tests. No real Gemini calls are made; the SDK client is replaced by fakes."""

from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors as genai_errors

from app.config import Settings
from app.models.agreement import AgreementAnalysis, Status
from app.services.ai.base import AIResponseError, AITimeoutError, AIUnavailableError
from app.services.ai.factory import build_provider
from app.services.ai.gemini import GeminiProvider, parse_response
from app.services.analysis import AI_UNAVAILABLE_MESSAGE, run_analysis
from tests.conftest import FailingProvider, FakeProvider, simple_analysis


class FakeModels:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.kwargs = None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def fake_client(response=None, error=None):
    models = FakeModels(response, error)
    return SimpleNamespace(models=models)


def api_error(code: int, message: str) -> genai_errors.APIError:
    return genai_errors.APIError(code, {"error": {"message": message, "status": "ERR"}})


def test_missing_api_key_raises_unavailable():
    with pytest.raises(AIUnavailableError):
        build_provider(Settings(gemini_api_key=None, _env_file=None))
    with pytest.raises(AIUnavailableError):
        GeminiProvider(api_key="", model="some-model")


def test_factory_passes_model_from_settings():
    provider = build_provider(Settings(gemini_api_key="k", gemini_model="my-model", _env_file=None))
    assert isinstance(provider, GeminiProvider)
    assert provider.model == "my-model"


def test_valid_structured_response(simple_document):
    expected = simple_analysis()
    client = fake_client(response=SimpleNamespace(parsed=expected, text=None))
    provider = GeminiProvider(api_key="k", model="m", client=client)
    result = provider.analyze(simple_document)
    assert result == expected
    kwargs = client.models.kwargs
    assert kwargs["model"] == "m"
    assert "=== PAGE 1 ===" in kwargs["contents"]
    assert kwargs["config"].response_mime_type == "application/json"
    assert kwargs["config"].response_schema is AgreementAnalysis


def test_json_text_response_is_parsed(simple_document):
    text = simple_analysis().model_dump_json()
    client = fake_client(response=SimpleNamespace(parsed=None, text=text))
    provider = GeminiProvider(api_key="k", model="m", client=client)
    result = provider.analyze(simple_document)
    assert result.payment.status is Status.FOUND


def test_fenced_json_is_parsed():
    text = "```json\n" + simple_analysis().model_dump_json() + "\n```"
    result = parse_response(SimpleNamespace(parsed=None, text=text))
    assert result.cancellation.page == 4


def test_invalid_response_rejected(simple_document):
    client = fake_client(response=SimpleNamespace(parsed=None, text="# Summary\nLooks fine!"))
    provider = GeminiProvider(api_key="k", model="m", client=client)
    with pytest.raises(AIResponseError):
        provider.analyze(simple_document)


def test_schema_violating_json_rejected(simple_document):
    client = fake_client(
        response=SimpleNamespace(parsed=None, text='{"payment": {"status": "MAYBE"}}')
    )
    provider = GeminiProvider(api_key="k", model="m", client=client)
    with pytest.raises(AIResponseError):
        provider.analyze(simple_document)


def test_empty_response_rejected(simple_document):
    client = fake_client(response=SimpleNamespace(parsed=None, text=""))
    provider = GeminiProvider(api_key="k", model="m", client=client)
    with pytest.raises(AIResponseError):
        provider.analyze(simple_document)


def test_quota_exhausted_is_unavailable(simple_document):
    client = fake_client(error=api_error(429, "Resource has been exhausted"))
    provider = GeminiProvider(api_key="k", model="m", client=client)
    with pytest.raises(AIUnavailableError):
        provider.analyze(simple_document)


def test_server_error_is_unavailable(simple_document):
    client = fake_client(error=api_error(503, "Service unavailable"))
    provider = GeminiProvider(api_key="k", model="m", client=client)
    with pytest.raises(AIUnavailableError):
        provider.analyze(simple_document)


def test_timeout_is_timeout_error(simple_document):
    client = fake_client(error=httpx.ReadTimeout("timed out"))
    provider = GeminiProvider(api_key="k", model="m", client=client)
    with pytest.raises(AITimeoutError):
        provider.analyze(simple_document)


def test_builtin_timeout_is_timeout_error(simple_document):
    client = fake_client(error=TimeoutError())
    provider = GeminiProvider(api_key="k", model="m", client=client)
    with pytest.raises(AITimeoutError):
        provider.analyze(simple_document)


def test_connection_error_is_unavailable(simple_document):
    client = fake_client(error=httpx.ConnectError("no route"))
    provider = GeminiProvider(api_key="k", model="m", client=client)
    with pytest.raises(AIUnavailableError):
        provider.analyze(simple_document)


def test_run_analysis_without_provider(simple_document):
    result = run_analysis(simple_document, None)
    assert not result.ok
    assert result.ai_error == AI_UNAVAILABLE_MESSAGE


def test_run_analysis_swallows_provider_errors(simple_document):
    result = run_analysis(simple_document, FailingProvider("quota"))
    assert not result.ok
    assert result.analysis is None
    assert result.ai_error == AI_UNAVAILABLE_MESSAGE


def test_run_analysis_validates_evidence(simple_document):
    analysis = simple_analysis()
    analysis.commitment.evidence = "You are locked in for 24 months."
    result = run_analysis(simple_document, FakeProvider(result=analysis))
    assert result.ok
    assert result.analysis.commitment.status is Status.UNCLEAR
    assert result.analysis.payment.status is Status.FOUND
