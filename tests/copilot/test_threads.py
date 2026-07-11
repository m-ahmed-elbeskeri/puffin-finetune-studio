"""ThreadStore round-trip tests."""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.asyncio


async def test_create_list_get(store):
    thr = await store.create_thread(title="Hello", model="claude-sonnet-4-6")
    assert thr.title == "Hello"
    fetched = await store.get_thread(thr.id)
    assert fetched is not None
    assert fetched.id == thr.id
    listed = await store.list_threads()
    assert any(t.id == thr.id for t in listed)


async def test_append_and_replay(store):
    thr = await store.create_thread(title="t", model="claude-sonnet-4-6")
    await store.append_message(thr.id, role="user", content=[
        {"type": "text", "text": "hi"}])
    await store.append_message(thr.id, role="assistant", content=[
        {"type": "text", "text": "hello back"}])

    msgs = await store.list_messages(thr.id)
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert msgs[0].idx == 0
    assert msgs[1].role == "assistant"
    assert msgs[1].idx == 1

    api = await store.to_anthropic_messages(thr.id)
    assert api == [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "hello back"}]},
    ]


async def test_rename_delete(store):
    thr = await store.create_thread(title="orig", model="m")
    await store.rename_thread(thr.id, "renamed")
    fetched = await store.get_thread(thr.id)
    assert fetched.title == "renamed"

    await store.delete_thread(thr.id)
    assert await store.get_thread(thr.id) is None
    listed = await store.list_threads()
    assert not any(t.id == thr.id for t in listed)


async def test_set_model(store):
    thr = await store.create_thread(title="t", model="m1")
    await store.set_model(thr.id, "m2")
    fetched = await store.get_thread(thr.id)
    assert fetched.model == "m2"


async def test_truncate_messages(store):
    thr = await store.create_thread(title="t", model="m")
    for i, text in enumerate(["a", "b", "c", "d"]):
        role = "user" if i % 2 == 0 else "assistant"
        await store.append_message(
            thr.id, role=role, content=[{"type": "text", "text": text}])

    deleted = await store.truncate_messages(thr.id, 2)
    assert deleted == 2
    msgs = await store.list_messages(thr.id)
    assert [m.content[0]["text"] for m in msgs] == ["a", "b"]

    # New appends continue from the truncated tail without idx collisions.
    m = await store.append_message(
        thr.id, role="user", content=[{"type": "text", "text": "e"}])
    assert m.idx == 2


async def test_complex_content_roundtrips(store):
    """tool_use + tool_result blocks should survive the JSON round-trip."""
    thr = await store.create_thread(title="t", model="m")
    content = [
        {"type": "text", "text": "Let me check status."},
        {"type": "tool_use", "id": "tu_1", "name": "project_status",
         "input": {}},
    ]
    await store.append_message(thr.id, role="assistant", content=content)
    msgs = await store.list_messages(thr.id)
    assert msgs[0].content == content
