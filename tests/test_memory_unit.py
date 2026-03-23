from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcps.servers.memory import forget, list_memories, recall, remember


def make_mock_response(return_value):
    """Create a mock httpx.Response (synchronous json/raise_for_status)."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=return_value)
    return mock_response


def make_mock_client(method: str, return_value):
    """Helper to create a mock httpx.AsyncClient context manager."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_response = make_mock_response(return_value)
    setattr(mock_client, method, AsyncMock(return_value=mock_response))
    return mock_client


@pytest.mark.unit
@pytest.mark.asyncio
class TestRemember:
    async def test_remember_stores_memory(self):
        api_response = {"results": [{"event": "ADD", "memory": "We finished Breaking Bad S5", "id": "mem_123"}]}
        mock_client = make_mock_client("post", api_response)
        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = mock_client
            result = await remember("We finished Breaking Bad S5")

        assert "mem_123" in result
        assert "Stored:" in result
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["json"]["user_id"] == "household"
        assert call_kwargs.kwargs["json"]["messages"][0]["content"] == "We finished Breaking Bad S5"

    async def test_remember_with_custom_user_id(self):
        api_response = {"results": [{"event": "ADD", "memory": "Denis prefers 4K", "id": "mem_456"}]}
        mock_client = make_mock_client("post", api_response)
        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = mock_client
            result = await remember("Denis prefers 4K", user_id="denis")

        assert "mem_456" in result
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["json"]["user_id"] == "denis"

    async def test_remember_empty_results(self):
        api_response = {"results": []}
        mock_client = make_mock_client("post", api_response)
        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = mock_client
            result = await remember("Some fact")

        assert "no details" in result.lower()

    async def test_remember_handles_api_error(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = mock_client
            result = await remember("Some fact")

        assert "unavailable" in result.lower()


@pytest.mark.unit
@pytest.mark.asyncio
class TestRecall:
    async def test_recall_searches_memories(self):
        api_response = {"results": [{"memory": "We watched Breaking Bad S1-S5", "score": 0.95, "id": "mem_789"}]}
        mock_client = make_mock_client("post", api_response)
        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = mock_client
            result = await recall("Breaking Bad")

        assert "Breaking Bad" in result
        assert "Found:" in result
        call_kwargs = mock_client.post.call_args
        assert "/memories/search" in call_kwargs.args[0]
        assert call_kwargs.kwargs["json"]["query"] == "Breaking Bad"
        assert call_kwargs.kwargs["json"]["user_id"] == "household"

    async def test_recall_empty_results(self):
        api_response = {"results": []}
        mock_client = make_mock_client("post", api_response)
        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = mock_client
            result = await recall("something obscure")

        assert "nothing found" in result.lower()

    async def test_recall_handles_api_error(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("Timeout"))
        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = mock_client
            result = await recall("anything")

        assert "unavailable" in result.lower()


@pytest.mark.unit
@pytest.mark.asyncio
class TestListMemories:
    async def test_list_memories_returns_all(self):
        api_response = {
            "results": [
                {"memory": "TV supports 4K HDR", "id": "mem_001"},
                {"memory": "We enjoy sci-fi series", "id": "mem_002"},
            ]
        }
        mock_client = make_mock_client("get", api_response)
        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = mock_client
            result = await list_memories()

        assert "4K" in result
        assert "sci-fi" in result
        assert "Memories (2):" in result
        call_kwargs = mock_client.get.call_args
        assert "/memories" in call_kwargs.args[0]
        assert call_kwargs.kwargs["params"]["user_id"] == "household"

    async def test_list_memories_empty(self):
        api_response = {"results": []}
        mock_client = make_mock_client("get", api_response)
        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = mock_client
            result = await list_memories()

        assert "no memories" in result.lower()

    async def test_list_memories_handles_api_error(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("Service unavailable"))
        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = mock_client
            result = await list_memories()

        assert "unavailable" in result.lower()


@pytest.mark.unit
@pytest.mark.asyncio
class TestForget:
    async def test_forget_deletes_memory(self):
        api_response = {"deleted": True}
        mock_client = make_mock_client("delete", api_response)
        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = mock_client
            result = await forget("mem_123")

        assert "forgotten" in result.lower()
        assert "mem_123" in result
        call_kwargs = mock_client.delete.call_args
        assert "mem_123" in call_kwargs.args[0]

    async def test_forget_handles_api_error(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.delete = AsyncMock(side_effect=Exception("Not found"))
        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = mock_client
            result = await forget("mem_999")

        assert "unavailable" in result.lower()
