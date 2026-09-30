"""LLM-13: transport hygiene for the chat assistant's calls to the LLM backend --
no Authorization header when no key is configured, backoff-retry on transient
failures only, and a clear, safe error when the key is simply missing."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from gridarena.llm.chat import ChatSession

_CONFIG_WITH_KEY = {
    "api_key": "k", "api_url": "http://fake", "model": "m",
    "verify_ssl": False, "temperature": 0.3,
    "max_tokens_with_tools": 2000, "max_tokens_interpretation": 800,
}
_CONFIG_NO_KEY = {**_CONFIG_WITH_KEY, "api_key": ""}


def _resp(status_code, json_data=None):
    m = MagicMock()
    m.status_code = status_code
    m.text = f"status {status_code}"
    m.json.return_value = json_data if json_data is not None else {"choices": []}
    return m


@pytest.mark.asyncio
@patch("gridarena.llm.chat.create_dispatcher", return_value={})
@patch("gridarena.llm.chat.get_llm_config", return_value=_CONFIG_WITH_KEY)
async def test_auth_header_present_when_key_configured(mock_config, mock_dispatcher):
    session = ChatSession()
    captured = {}

    async def fake_post(self, url, headers=None, json=None):
        captured["headers"] = headers
        return _resp(200, {"choices": [{"message": {"role": "assistant", "content": "hi"}}]})

    with patch.object(httpx.AsyncClient, "post", new=fake_post):
        await session._call_llm([{"role": "user", "content": "hi"}], use_tools=False)

    assert captured["headers"]["Authorization"] == "Bearer k"


@pytest.mark.asyncio
@patch("gridarena.llm.chat.create_dispatcher", return_value={})
@patch("gridarena.llm.chat.get_llm_config", return_value=_CONFIG_NO_KEY)
async def test_auth_header_omitted_when_key_empty(mock_config, mock_dispatcher):
    session = ChatSession()
    captured = {}

    async def fake_post(self, url, headers=None, json=None):
        captured["headers"] = headers
        return _resp(200, {"choices": [{"message": {"role": "assistant", "content": "hi"}}]})

    with patch.object(httpx.AsyncClient, "post", new=fake_post):
        await session._call_llm([{"role": "user", "content": "hi"}], use_tools=False)

    assert "Authorization" not in captured["headers"]


@pytest.mark.asyncio
@patch("gridarena.llm.chat.create_dispatcher", return_value={})
@patch("gridarena.llm.chat.get_llm_config", return_value=_CONFIG_WITH_KEY)
async def test_process_message_raises_clearly_when_key_missing(mock_config, mock_dispatcher):
    mock_config.return_value = _CONFIG_NO_KEY
    session = ChatSession()

    with pytest.raises(RuntimeError, match="LLM_API_KEY is not configured"):
        await session.process_message("hello")


@pytest.mark.asyncio
@patch("gridarena.llm.chat.create_dispatcher", return_value={})
@patch("gridarena.llm.chat.get_llm_config", return_value=_CONFIG_WITH_KEY)
@patch("gridarena.llm.chat.asyncio.sleep", new_callable=AsyncMock)
async def test_retries_on_503_then_succeeds(mock_sleep, mock_config, mock_dispatcher):
    session = ChatSession()
    responses = [_resp(503), _resp(503), _resp(200, {"choices": [{"message": {"content": "ok"}}]})]

    post_mock = AsyncMock(side_effect=responses)
    with patch.object(httpx.AsyncClient, "post", new=post_mock):
        data = await session._call_llm([{"role": "user", "content": "hi"}], use_tools=False)

    assert post_mock.await_count == 3
    assert mock_sleep.await_count == 2
    assert data["choices"][0]["message"]["content"] == "ok"


@pytest.mark.asyncio
@patch("gridarena.llm.chat.create_dispatcher", return_value={})
@patch("gridarena.llm.chat.get_llm_config", return_value=_CONFIG_WITH_KEY)
@patch("gridarena.llm.chat.asyncio.sleep", new_callable=AsyncMock)
async def test_retries_on_connect_error_then_succeeds(mock_sleep, mock_config, mock_dispatcher):
    session = ChatSession()
    post_mock = AsyncMock(side_effect=[
        httpx.ConnectError("boom"),
        _resp(200, {"choices": [{"message": {"content": "ok"}}]}),
    ])
    with patch.object(httpx.AsyncClient, "post", new=post_mock):
        data = await session._call_llm([{"role": "user", "content": "hi"}], use_tools=False)

    assert post_mock.await_count == 2
    assert data["choices"][0]["message"]["content"] == "ok"


@pytest.mark.asyncio
@patch("gridarena.llm.chat.create_dispatcher", return_value={})
@patch("gridarena.llm.chat.get_llm_config", return_value=_CONFIG_WITH_KEY)
@patch("gridarena.llm.chat.asyncio.sleep", new_callable=AsyncMock)
async def test_does_not_retry_a_4xx(mock_sleep, mock_config, mock_dispatcher):
    session = ChatSession()
    post_mock = AsyncMock(side_effect=[_resp(400)])

    with patch.object(httpx.AsyncClient, "post", new=post_mock):
        with pytest.raises(RuntimeError, match="400"):
            await session._call_llm([{"role": "user", "content": "hi"}], use_tools=False)

    assert post_mock.await_count == 1
    mock_sleep.assert_not_awaited()


@pytest.mark.asyncio
@patch("gridarena.llm.chat.create_dispatcher", return_value={})
@patch("gridarena.llm.chat.get_llm_config", return_value=_CONFIG_WITH_KEY)
@patch("gridarena.llm.chat.asyncio.sleep", new_callable=AsyncMock)
async def test_exhausts_retries_and_raises(mock_sleep, mock_config, mock_dispatcher):
    session = ChatSession()
    post_mock = AsyncMock(side_effect=[_resp(502), _resp(502), _resp(502)])

    with patch.object(httpx.AsyncClient, "post", new=post_mock):
        with pytest.raises(RuntimeError, match="502"):
            await session._call_llm([{"role": "user", "content": "hi"}], use_tools=False)

    assert post_mock.await_count == 3
