# -*- coding: utf-8 -*-
import asyncio
import json
from typing import Any

import pytest

import handoff_store
import handoff_service
import main


class _Request:
    def __init__(self, token: str) -> None:
        self.headers = {"Authorization": f"Bearer {token}"}
        self.disconnected = False

    async def is_disconnected(self) -> bool:
        return self.disconnected


def _request(user_id: str, session_id: str) -> _Request:
    token = main.create_token(
        sub=user_id,
        role=main.Role.CUSTOMER_USER.value,
        tenant_id="mitako",
        extra={"session_id": session_id},
    )
    return _Request(token)


def _chat_request(user_id: str, session_id: str, content: str) -> main.ChatRequest:
    return main.ChatRequest(
        user_id=user_id,
        session_id=session_id,
        content=content,
        history=[],
        stream_reply=True,
    )


async def _collect(response: Any) -> list[dict[str, Any]]:
    events = []
    async for event in response.body_iterator:
        events.append(event)
    return events


def _event_data(events: list[dict[str, Any]], event_name: str) -> list[dict[str, Any]]:
    return [
        json.loads(event["data"])
        for event in events
        if event.get("event") == event_name
    ]


@pytest.fixture(autouse=True)
def _isolated_handoff_store(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(handoff_store, "_DB_DIR", str(tmp_path))
    monkeypatch.setattr(handoff_store, "_DB_PATH", str(tmp_path / "handoff.db"))
    monkeypatch.setattr(handoff_store, "_db_ready", False)
    active = getattr(main, "_active_chat_turns", None)
    if isinstance(active, dict):
        active.clear()
    locks = getattr(main, "_chat_turn_locks", None)
    if hasattr(locks, "clear"):
        locks.clear()
    yield
    active = getattr(main, "_active_chat_turns", None)
    if isinstance(active, dict):
        active.clear()
    locks = getattr(main, "_chat_turn_locks", None)
    if hasattr(locks, "clear"):
        locks.clear()


def test_disconnect_cancels_and_awaits_agent_task(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def blocked_ainvoke(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        monkeypatch.setattr(main.agent_app, "ainvoke", blocked_ainvoke)
        request = _request("disconnect-user", "disconnect-session")
        response = await main.chat_stream(
            _chat_request("disconnect-user", "disconnect-session", "这轮不要了"),
            request,
        )
        collector = asyncio.create_task(_collect(response))

        await asyncio.wait_for(started.wait(), timeout=0.3)
        request.disconnected = True
        events = await asyncio.wait_for(collector, timeout=0.5)
        await asyncio.wait_for(cancelled.wait(), timeout=0.2)

        assert not [item for item in _event_data(events, "done") if item.get("status") == "completed"]
        assert handoff_store.recent_chat_history("disconnect-session") == []
        assert getattr(main, "_active_chat_turns", None) == {}

    asyncio.run(run())


def test_timeout_emits_failed_terminal_without_success_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        cancelled = asyncio.Event()
        assistant_messages: list[str] = []
        cards: list[dict[str, Any]] = []
        handoff_offers: list[dict[str, Any]] = []
        real_append = handoff_store.append_message

        async def blocked_ainvoke(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        def tracked_append(session_id: str, role: str, content: str, **kwargs: Any) -> dict[str, Any]:
            if role == "assistant":
                assistant_messages.append(content)
            return real_append(session_id, role, content, **kwargs)

        monkeypatch.setattr(main, "CHAT_TURN_TIMEOUT_SECONDS", 0.03, raising=False)
        monkeypatch.setattr(main.agent_app, "ainvoke", blocked_ainvoke)
        monkeypatch.setattr(main.handoff_store, "append_message", tracked_append)
        monkeypatch.setattr(main, "_select_primary_customer_card", lambda result: cards.append(result))
        monkeypatch.setattr(
            main.handoff_store,
            "create_handoff_offer",
            lambda *args, **kwargs: handoff_offers.append({"created": True}),
        )

        response = await main.chat_stream(
            _chat_request("timeout-user", "timeout-session", "请帮我处理"),
            _request("timeout-user", "timeout-session"),
        )
        events = await asyncio.wait_for(_collect(response), timeout=0.5)
        await asyncio.wait_for(cancelled.wait(), timeout=0.2)

        assert _event_data(events, "terminal") == [
            {"status": "failed", "reason_code": "chat_timeout"}
        ]
        assert not [item for item in _event_data(events, "done") if item.get("status") == "completed"]
        assert assistant_messages == []
        assert cards == []
        assert handoff_offers == []
        assert handoff_store.recent_chat_history("timeout-session") == []
        assert getattr(main, "_active_chat_turns", None) == {}

    asyncio.run(run())


def test_same_session_new_turn_cancels_old_turn_and_keeps_other_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        first_started = asyncio.Event()
        first_cancelled = asyncio.Event()
        invocation = 0

        handoff_store.ensure_chat_session("single-session", "single-user", tenant_id="mitako")
        handoff_store.append_message(
            "single-session",
            "user",
            "更早一轮",
            meta={"kind": "ai_chat"},
        )

        async def fake_ainvoke(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            nonlocal invocation
            invocation += 1
            if invocation == 1:
                first_started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    first_cancelled.set()
                    raise
            return {**state, "reply_draft": "请继续补充需要核对的信息。"}

        monkeypatch.setattr(main.agent_app, "ainvoke", fake_ainvoke)
        first_response = await main.chat_stream(
            _chat_request("single-user", "single-session", "第一轮阻塞"),
            _request("single-user", "single-session"),
        )
        first_collector = asyncio.create_task(_collect(first_response))
        await asyncio.wait_for(first_started.wait(), timeout=0.3)

        second_response = await main.chat_stream(
            _chat_request("single-user", "single-session", "第二轮继续"),
            _request("single-user", "single-session"),
        )
        second_events = await asyncio.wait_for(_collect(second_response), timeout=0.5)
        first_result = await asyncio.gather(first_collector, return_exceptions=True)
        first_events = first_result[0] if isinstance(first_result[0], list) else []
        await asyncio.wait_for(first_cancelled.wait(), timeout=0.2)

        history = handoff_store.recent_chat_history("single-session", limit=20)
        user_texts = [item["content"] for item in history if item["role"] == "user"]
        assert invocation == 2
        assert user_texts == ["更早一轮", "第二轮继续"]
        assert "第一轮阻塞" not in user_texts
        assert not [item for item in _event_data(first_events, "done") if item.get("status") == "completed"]
        assert _event_data(second_events, "done")
        assert getattr(main, "_active_chat_turns", None) == {}

    asyncio.run(run())


def test_new_turn_cancels_entire_old_sse_after_agent_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        invocation = 0
        done_seen = asyncio.Event()
        release_old_collector = asyncio.Event()

        async def fake_ainvoke(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            nonlocal invocation
            invocation += 1
            return {
                **state,
                "turn_marker": "first" if invocation == 1 else "second",
                "reply_draft": "第一轮回复" if invocation == 1 else "第二轮回复",
            }

        monkeypatch.setattr(main.agent_app, "ainvoke", fake_ainvoke)
        first_response = await main.chat_stream(
            _chat_request("race-user", "race-session", "第一轮"),
            _request("race-user", "race-session"),
        )
        first_events: list[dict[str, Any]] = []

        async def collect_first() -> None:
            try:
                async for event in first_response.body_iterator:
                    first_events.append(event)
                    if event.get("event") == "done":
                        done_seen.set()
                        await release_old_collector.wait()
            finally:
                await first_response.body_iterator.aclose()

        first_collector = asyncio.create_task(collect_first())
        await asyncio.wait_for(done_seen.wait(), timeout=0.3)

        second_response = await main.chat_stream(
            _chat_request("race-user", "race-session", "第二轮"),
            _request("race-user", "race-session"),
        )
        second_events = await asyncio.wait_for(_collect(second_response), timeout=0.5)
        release_old_collector.set()
        await asyncio.gather(first_collector, return_exceptions=True)

        history = handoff_store.recent_chat_history("race-session", limit=20)
        assistant_texts = [item["content"] for item in history if item["role"] == "assistant"]
        assert [item["content"] for item in history if item["role"] == "user"] == ["第一轮", "第二轮"]
        assert len(assistant_texts) == 2
        assert _event_data(first_events, "done")
        assert _event_data(second_events, "done")
        assert getattr(main, "_active_chat_turns", None) == {}

    asyncio.run(run())


def test_timeout_rolls_back_unpublished_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        cancelled = asyncio.Event()
        published: list[str] = []

        monkeypatch.setattr(handoff_service, "_emit_status", lambda *args, **kwargs: published.append("ws"))
        import im_sync_service

        monkeypatch.setattr(
            im_sync_service,
            "sync_handoff_created",
            lambda *args, **kwargs: published.append("im"),
        )

        async def queued_then_blocked(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            assert config["configurable"]["defer_handoff_publish"] is True
            handoff_service.enqueue_handoff(
                state["session_id"],
                {
                    "session_id": state["session_id"],
                    "user_id": state["user_id"],
                    "tenant_id": state["tenant_id"],
                    "summary": "待发布转接",
                },
                tenant_id=state["tenant_id"],
                publish=False,
            )
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        monkeypatch.setattr(main, "CHAT_TURN_TIMEOUT_SECONDS", 0.03)
        monkeypatch.setattr(main.agent_app, "ainvoke", queued_then_blocked)

        response = await main.chat_stream(
            _chat_request("handoff-timeout-user", "handoff-timeout-session", "请转人工"),
            _request("handoff-timeout-user", "handoff-timeout-session"),
        )
        events = await asyncio.wait_for(_collect(response), timeout=0.5)
        await asyncio.wait_for(cancelled.wait(), timeout=0.2)

        assert _event_data(events, "terminal") == [
            {"status": "failed", "reason_code": "chat_timeout"}
        ]
        entry = handoff_store.get_session("handoff-timeout-session")
        assert entry is not None and entry["status"] == "chatting"
        assert published == []
        assert handoff_store.recent_chat_history("handoff-timeout-session") == []

    asyncio.run(run())


def test_slow_cancellation_rejects_same_session_without_blocking_other_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        first_started = asyncio.Event()
        release_first = asyncio.Event()

        async def slow_cancel_ainvoke(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            if state["session_id"] != "slow-session":
                return {**state, "reply_draft": "其他会话正常完成"}
            first_started.set()
            try:
                await release_first.wait()
            except asyncio.CancelledError:
                await release_first.wait()
                raise

        monkeypatch.setattr(main, "CHAT_TURN_CANCEL_GRACE_SECONDS", 0.02, raising=False)
        monkeypatch.setattr(main.agent_app, "ainvoke", slow_cancel_ainvoke)

        first_response = await main.chat_stream(
            _chat_request("slow-user", "slow-session", "第一轮慢清理"),
            _request("slow-user", "slow-session"),
        )
        first_collector = asyncio.create_task(_collect(first_response))
        await asyncio.wait_for(first_started.wait(), timeout=0.3)

        second_response = await main.chat_stream(
            _chat_request("slow-user", "slow-session", "第二轮应拒绝"),
            _request("slow-user", "slow-session"),
        )
        other_response = await main.chat_stream(
            _chat_request("other-user", "other-session", "其他会话"),
            _request("other-user", "other-session"),
        )
        second_events, other_events = await asyncio.gather(
            asyncio.wait_for(_collect(second_response), timeout=0.3),
            asyncio.wait_for(_collect(other_response), timeout=0.3),
        )

        assert _event_data(second_events, "terminal") == [
            {"status": "failed", "reason_code": "chat_turn_busy"}
        ]
        assert _event_data(other_events, "done")
        release_first.set()
        await asyncio.gather(first_collector, return_exceptions=True)
        assert getattr(main, "_active_chat_turns", None) == {}

    asyncio.run(run())


def test_handoff_is_published_only_after_done_is_consumed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        published: list[str] = []
        monkeypatch.setattr(handoff_service, "_emit_status", lambda *args, **kwargs: published.append("ws"))
        import im_sync_service

        monkeypatch.setattr(
            im_sync_service,
            "sync_handoff_created",
            lambda *args, **kwargs: published.append("im"),
        )

        async def deferred_handoff(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            brief = {
                "session_id": state["session_id"],
                "user_id": state["user_id"],
                "tenant_id": state["tenant_id"],
                "summary": "待提交人工转接",
            }
            queued = handoff_service.enqueue_handoff(
                state["session_id"],
                brief,
                tenant_id=state["tenant_id"],
                publish=False,
            )
            queue = config["configurable"]["event_queue"]
            await queue.put({"type": "handoff_brief", "brief": brief})
            await queue.put({
                "type": "action_transfer",
                "brief": brief,
                "queue": queued,
                "action_state": queued["action_state"],
            })
            conversation_state = {
                **(state.get("conversation_state") or {}),
                "action_state": queued["action_state"],
            }
            return {
                **state,
                "should_transfer": True,
                "conversation_state": conversation_state,
                "action_state": queued["action_state"],
                "reply_draft": "已进入人工队列。",
            }

        monkeypatch.setattr(main.agent_app, "ainvoke", deferred_handoff)

        cancelled_response = await main.chat_stream(
            _chat_request("publish-cancel-user", "publish-cancel-session", "转人工后停止"),
            _request("publish-cancel-user", "publish-cancel-session"),
        )
        first_event = await cancelled_response.body_iterator.__anext__()
        assert first_event["event"] == "handoff_brief"
        assert published == []
        await cancelled_response.body_iterator.aclose()
        assert published == []
        assert handoff_store.get_session("publish-cancel-session")["status"] == "chatting"

        completed_response = await main.chat_stream(
            _chat_request("publish-done-user", "publish-done-session", "确认转人工"),
            _request("publish-done-user", "publish-done-session"),
        )
        completed_events = []
        while True:
            try:
                event = await completed_response.body_iterator.__anext__()
            except StopAsyncIteration:
                break
            completed_events.append(event)
            if event["event"] == "done":
                assert published == ["ws", "im"]
            else:
                assert published == []

        assert _event_data(completed_events, "done")
        assert published == ["ws", "im"]
        assert handoff_store.get_session("publish-done-session")["status"] == "queuing"

        monkeypatch.setattr(main, "publish_handoff", lambda *args, **kwargs: False)
        failed_response = await main.chat_stream(
            _chat_request("publish-failed-user", "publish-failed-session", "转人工发布失败"),
            _request("publish-failed-user", "publish-failed-session"),
        )
        failed_events = await _collect(failed_response)
        assert _event_data(failed_events, "done") == []
        assert _event_data(failed_events, "terminal") == [
            {"status": "failed", "reason_code": "handoff_publish_failed"}
        ]
        assert handoff_store.get_session("publish-failed-session")["status"] == "chatting"
        assert handoff_store.recent_chat_history("publish-failed-session") == []

    asyncio.run(run())


def test_cancelled_message_cleanup_is_scoped_to_turn_and_tenant() -> None:
    handoff_store.ensure_chat_session("scope-a", "user-a", tenant_id="tenant-a")
    older = handoff_store.append_message("scope-a", "user", "保留消息")
    cancelled = handoff_store.append_message("scope-a", "user", "取消消息")
    handoff_store.ensure_chat_session("scope-b", "user-b", tenant_id="tenant-b")
    other_tenant = handoff_store.append_message("scope-b", "user", "其他租户消息")

    assert handoff_store.delete_message(
        "scope-a",
        cancelled["id"],
        tenant_id="tenant-a",
    ) is True
    assert handoff_store.delete_message(
        "scope-a",
        older["id"],
        tenant_id="tenant-b",
    ) is False
    assert [item["id"] for item in handoff_store.get_messages_since("scope-a", 0)] == [older["id"]]
    assert [item["id"] for item in handoff_store.get_messages_since("scope-b", 0)] == [other_tenant["id"]]
