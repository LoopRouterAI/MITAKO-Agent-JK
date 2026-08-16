# API Contract: Handoff & Desk (v1)

Base: `/api/v1`

## Client — Handoff

### POST `/handoff/request`
Body: `{ user_id, session_id, history[], reason, last_user_message, intent, emotion_level }`  
Response: `{ ok, brief, queue: { position, ahead, eta, required_tier }, reason }`

### GET `/handoff/status/{session_id}`
Response: `{ ok, status, position, ahead, eta_minutes, agent?, welcome?, assigned_agent?, pending_agent?, observer_mode? }`

### GET `/handoff/messages/{session_id}?since={ts}`
Response: `{ ok, messages: [{ id, role, content, agent_id, created_at, meta }], latest_ts }`

### POST `/handoff/user-message`
Body: `{ session_id, content, user_id }`  
When connected: persists user msg; if `@虾饺` triggers observer reply.  
Response: `{ ok, messages_added[] }`

### POST `/handoff/connect?session_id=`
Only when status=connected. Response: `{ ok, agent, welcome, brief }`

### POST `/handoff/reset?session_id=`

### GET `/handoff/routing`
Response: `{ ok, config }` (read-only for desk)

## Desk

### GET `/desk/agents` | GET `/desk/sessions` | GET `/desk/session/{id}`

### POST `/desk/session/{id}/accept`
Body: `{ agent_id }` — respects routing tier when rule enabled.

### POST `/desk/session/{id}/reply`
Body: `{ content, agent_id }` — requires can_chat.

### POST `/desk/session/{id}/transfer`
Body: `{ from_agent_id, to_agent_id, note }` — colleague handoff.

### POST `/desk/session/{id}/escalate`
Body: `{ note }` — department/supervisor queue.
