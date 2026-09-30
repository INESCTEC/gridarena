"""LLM-9: only the tool schemas relevant to the matched agents should be sent to
the model, with a fallback to the full set when nothing matched (or a previous
round called an unknown tool name)."""

from unittest.mock import AsyncMock, patch

import pytest

from gridarena.llm.chat import ChatSession
from gridarena.llm.tools import ALL_TOOLS, tools_for_agents


def test_tools_for_agents_returns_only_the_named_agents_tools():
    names = {t["function"]["name"] for t in tools_for_agents(["PhaseAgent"])}
    assert names == {
        "get_training_phase_data", "get_phase_identification_data",
        "submit_phase_guesses", "get_phase_score",
    }
    assert "get_historical_series_data" not in names


def test_tools_for_agents_unknown_agent_name_yields_nothing():
    assert tools_for_agents(["NoSuchAgent"]) == []


def test_tools_for_agents_is_a_strict_subset_of_all_tools():
    subset = tools_for_agents(["PhaseAgent"])
    assert len(subset) < len(ALL_TOOLS)
    assert all(t in ALL_TOOLS for t in subset)


_CONFIG = {
    "api_key": "k", "api_url": "http://fake", "model": "m",
    "verify_ssl": False, "temperature": 0.3,
    "max_tokens_with_tools": 2000, "max_tokens_interpretation": 800,
}


@pytest.mark.asyncio
@patch("gridarena.llm.chat.create_dispatcher", return_value={})
@patch("gridarena.llm.chat.get_llm_config", return_value=_CONFIG)
async def test_matched_message_sends_only_relevant_tools(mock_config, mock_dispatcher):
    session = ChatSession()
    seen_tools = []

    async def mock_call_llm(messages, use_tools, tools=None):
        seen_tools.append(tools)
        return {"choices": [{"message": {"role": "assistant", "content": "Phase info."}}]}

    with patch("gridarena.llm.chat.get_relevant_docs", return_value=""), \
         patch.object(session, "_call_llm", side_effect=mock_call_llm):
        await session.process_message("tell me about phase identification")

    assert len(seen_tools) == 1
    names = {t["function"]["name"] for t in seen_tools[0]}
    assert names == {
        "get_training_phase_data", "get_phase_identification_data",
        "submit_phase_guesses", "get_phase_score",
    }


@pytest.mark.asyncio
@patch("gridarena.llm.chat.create_dispatcher", return_value={})
@patch("gridarena.llm.chat.get_llm_config", return_value=_CONFIG)
async def test_unmatched_message_sends_the_full_tool_set(mock_config, mock_dispatcher):
    session = ChatSession()
    seen_tools = []

    async def mock_call_llm(messages, use_tools, tools=None):
        seen_tools.append(tools)
        return {"choices": [{"message": {"role": "assistant", "content": "Hi there."}}]}

    with patch("gridarena.llm.chat.get_relevant_docs", return_value=""), \
         patch.object(session, "_call_llm", side_effect=mock_call_llm):
        await session.process_message("what's the weather like today")

    assert len(seen_tools) == 1
    assert seen_tools[0] == ALL_TOOLS


@pytest.mark.asyncio
@patch("gridarena.llm.chat.create_dispatcher", return_value={})
@patch("gridarena.llm.chat.get_llm_config", return_value=_CONFIG)
async def test_unknown_tool_error_widens_the_next_round_to_the_full_set(mock_config, mock_dispatcher):
    """If the model calls a tool name outside the narrowed set it was offered
    (e.g. it remembers a tool from earlier history that this round didn't
    advertise), the next round must fall back to the full set instead of
    repeating the same narrow, unworkable offer."""
    session = ChatSession()
    seen_tools = []

    def _tool_call_response(name):
        return {
            "choices": [{
                "message": {
                    "role": "assistant", "content": None,
                    "tool_calls": [{"id": "call_1", "function": {"name": name, "arguments": "{}"}}],
                }
            }]
        }

    call_count = 0

    async def mock_call_llm(messages, use_tools, tools=None):
        nonlocal call_count
        call_count += 1
        seen_tools.append(tools)
        if call_count == 1:
            return _tool_call_response("get_grid_data")  # not a PhaseAgent tool
        return {"choices": [{"message": {"role": "assistant", "content": "done"}}]}

    with patch("gridarena.llm.chat.get_relevant_docs", return_value=""), \
         patch.object(session, "_call_llm", side_effect=mock_call_llm):
        # run_tool is NOT mocked here -- get_grid_data isn't in TOOL_TO_AGENT_CLASS
        # under a PhaseAgent-only offer, so dispatcher.run_tool itself reports the
        # structured unknown_tool error (it doesn't actually check the offered set,
        # it checks TOOL_TO_AGENT_CLASS -- so use a name that's truly unregistered).
        with patch("gridarena.llm.chat.run_tool", new_callable=AsyncMock,
                    return_value={"agent": "Unknown", "function": "get_grid_data",
                                  "output": {"error": {"type": "unknown_tool", "detail": "x"}}}):
            await session.process_message("tell me about phase identification")

    assert len(seen_tools) == 2
    round1_names = {t["function"]["name"] for t in seen_tools[0]}
    assert "get_grid_data" not in round1_names  # narrowed to PhaseAgent tools only
    assert seen_tools[1] == ALL_TOOLS  # widened after the unknown_tool error
