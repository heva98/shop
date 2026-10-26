"""Abstract NotificationChannel interface. SMS and Email are active now;
WhatsApp is a future sibling implementing the same interface. Notifications
are cloud-side only, fired once a store's day's data has synced — never
computed from local/offline state (see architecture.txt §4)."""

from abc import ABC, abstractmethod


class NotificationChannel(ABC):
    @abstractmethod
    def send(self, recipient: str, subject: str, body: str) -> bool:
        raise NotImplementedError
