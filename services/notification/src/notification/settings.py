"""Process configuration of the notification service: ``CW_*`` on top of py-common's.

``notification_store`` picks the store: postgres (the default) for the service, memory for tests
and demos. The WhatsApp adapter needs a Meta business account, a phone number id and an access
token; none is created by the code. With ``whatsapp_enabled`` false the channel is wired disabled
and every WhatsApp send fails with that reason (docs/runbooks/whatsapp.md lists the manual steps).

``notification_batch_window_seconds`` is how long a notification waits for others to the same
person, so they go as one summary; it adds to the delivery time, and 0 sends each one alone.
``rulebook_url`` is where the facts of a change card come from, and ``web_base_url`` the web app
the messages link to.
"""

from typing import Literal

from pydantic import Field, SecretStr

from py_common.settings import Settings

Store = Literal["memory", "postgres"]


class NotificationSettings(Settings):
    notification_store: Store = "postgres"
    whatsapp_enabled: bool = False
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: SecretStr | None = None
    whatsapp_api_version: str = "v21.0"
    quiet_hours_start: str = "21:00"
    quiet_hours_end: str = "08:00"
    notification_batch_window_seconds: int = Field(default=300, ge=0, le=3600)
    rulebook_url: str = "http://localhost:8003"
    web_base_url: str = "http://localhost:3000"
