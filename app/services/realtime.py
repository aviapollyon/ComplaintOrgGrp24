import json
import threading
from collections import defaultdict, deque


_EVENT_BUFFER_SIZE = 200
_conditions = defaultdict(threading.Condition)
_queues = defaultdict(lambda: deque(maxlen=_EVENT_BUFFER_SIZE))


def _user_condition(user_id: int) -> threading.Condition:
    return _conditions[user_id]


def publish_user_event(user_id: int, event_type: str, payload: dict):
    if not user_id:
        return

    condition = _user_condition(int(user_id))
    with condition:
        _queues[int(user_id)].append({
            'type': event_type,
            'payload': payload,
        })
        condition.notify_all()


def wait_for_events(user_id: int, timeout_seconds: int = 15):
    condition = _user_condition(int(user_id))
    with condition:
        if not _queues[int(user_id)]:
            condition.wait(timeout=timeout_seconds)

        events = list(_queues[int(user_id)])
        _queues[int(user_id)].clear()
        return events


def sse_frame(event_type: str, payload: dict, event_id: str = '') -> str:
    lines = []
    if event_id:
        lines.append(f'id: {event_id}')
    lines.append(f'event: {event_type}')
    lines.append(f'data: {json.dumps(payload, default=str)}')
    return '\n'.join(lines) + '\n\n'
