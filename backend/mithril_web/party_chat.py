"""Bounded, ephemeral party messages. Owned by the Finder's event loop."""

import unicodedata
from collections import OrderedDict, deque

HISTORY_LIMIT = 100
RETRY_WINDOW = 600


def valid_text(text):
    return (
        isinstance(text, str)
        and 1 <= len(text) <= 256
        and bool(text.strip())
        and all(unicodedata.category(char) not in {"Cc", "Cs"} for char in text)
        and not any(
            char in "§\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069" for char in text
        )
    )


class ChatLog:
    def __init__(self):
        self.messages = deque(maxlen=HISTORY_LIMIT)
        self.receipts = OrderedDict()
        self.sequence = 0

    def previous(self, uuid, request_id, now):
        while self.receipts and next(iter(self.receipts.values()))[0] <= now - RETRY_WINDOW:
            self.receipts.popitem(last=False)
        receipt = self.receipts.get((uuid, request_id))
        return receipt[1] if receipt else None

    def append(self, uuid, name, request_id, text, source, now):
        self.sequence += 1
        message = {
            "id": str(self.sequence),
            "text": text,
            "at": int(now * 1000),
            "sender": {"uuid": uuid, "name": name},
            "source": source,
        }
        self.messages.append(message)
        self.receipts[uuid, request_id] = (now, message)
        # At most five members, 20 messages/minute each, with ten-minute retries.
        while len(self.receipts) > 1024:
            self.receipts.popitem(last=False)
        return message
