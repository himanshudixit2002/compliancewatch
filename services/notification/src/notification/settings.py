"""Process configuration of the notification service: ``CW_*`` on top of py-common's.

The WhatsApp adapter needs a Meta business account, a phone number id and an access token;
none is created by the code. With ``whatsapp_enabled`` false the channel is wired disabled and
every WhatsApp send fails with that reason (docs/runbooks/whatsapp.md lists the manual steps).
"""

from pydantic import SecretStr

from py_common.settings import Settings


class NotificationSettings(Settings):
    whatsapp_enabled: bool = False
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: SecretStr | None = None
    whatsapp_api_version: str = "v21.0"
    quiet_hours_start: str = "21:00"
    quiet_hours_end: str = "08:00"
