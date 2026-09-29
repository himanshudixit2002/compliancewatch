"""Process configuration of the notification service: ``CW_*`` on top of py-common's.

``notification_store`` picks the store: postgres (the default) for the service, memory for tests
and demos. The WhatsApp adapter needs a Meta business account, a phone number id and an access
token; none is created by the code. With ``whatsapp_enabled`` false the channel is wired disabled
and every WhatsApp send fails with that reason (docs/runbooks/whatsapp.md lists the manual steps).

``notification_batch_window_seconds`` is how long a notification waits for others to the same
person, so they go as one summary; it adds to the delivery time, and 0 sends each one alone.
``rulebook_url`` is where the facts of a change card come from, and ``web_base_url`` the web app
the messages link to. The worker sends what is due every ``notification_dispatch_interval_seconds``.
``notification_digest_at`` is the time in IST (``HH:MM``) of the daily digest that recipients who
hear by digest get: a daily digest chosen, and a CA firm's people.

``notification_bot_token`` is the shared secret the WhatsApp bot sends (``x-cw-bot-token``) with
the delivery statuses and inbound times it forwards; unset, the receipt route refuses them all.

Email goes out over SMTP only behind ``email_enabled`` (the ``notification.email`` flag, off by
default) with ``smtp_host`` and ``email_from``; STARTTLS is required, and the channel logs in
with ``smtp_username`` and ``smtp_password`` when a username is set. The SES bounce and
complaint feedback arrives through SNS with HTTP basic credentials whose password is
``notification_email_feedback_token`` (unset, the route refuses everything), and, when
``notification_ses_topic_arn`` is set, only from that topic.
"""

from typing import Literal

from pydantic import Field, SecretStr

from py_common.settings import Settings

Store = Literal["memory", "postgres"]
CLOCK_TIME = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"
"""``HH:MM`` on a 24-hour clock."""


class NotificationSettings(Settings):
    notification_store: Store = "postgres"
    whatsapp_enabled: bool = False
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: SecretStr | None = None
    whatsapp_api_version: str = "v21.0"
    quiet_hours_start: str = "21:00"
    quiet_hours_end: str = "08:00"
    notification_batch_window_seconds: int = Field(default=300, ge=0, le=3600)
    notification_dispatch_interval_seconds: float = Field(default=5.0, gt=0, le=300)
    notification_digest_at: str = Field(default="09:00", pattern=CLOCK_TIME)
    notification_bot_token: SecretStr | None = None
    email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: SecretStr | None = None
    email_from: str = ""
    notification_email_feedback_token: SecretStr | None = None
    notification_ses_topic_arn: str = ""
    rulebook_url: str = "http://localhost:8003"
    web_base_url: str = "http://localhost:3000"
