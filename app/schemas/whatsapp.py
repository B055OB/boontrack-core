"""app/schemas/whatsapp.py
Pydantic Schemas for Meta WhatsApp Cloud API Inbound Webhooks.

Defines:
- WebhookChallenge: Handshake verification schema (hub.mode, hub.challenge, hub.verify_token).
- WhatsAppMessage: Individual incoming message details (wamid, from, type, text, etc.).
- WhatsAppValue: Inner value containing messages, statuses, and metadata.
- WhatsAppChange: Change item under an entry.
- WhatsAppEntry: Entry object for WhatsApp Business Account.
- WhatsAppWebhookPayload: Root envelope payload from Meta Cloud API.
"""

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class WebhookChallenge(BaseModel):
    """Handshake query params sent by Meta during Webhook configuration."""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    mode: Optional[str] = Field(
        default=None,
        alias="hub.mode",
        description="Handshake mode, expected to be 'subscribe'",
    )
    challenge: Optional[Union[str, int]] = Field(
        default=None,
        alias="hub.challenge",
        description="Random challenge string/integer echoed back upon successful verification",
    )
    verify_token: Optional[str] = Field(
        default=None,
        alias="hub.verify_token",
        description="Verification token matching configured secret",
    )


class WhatsAppTextMessage(BaseModel):
    """Text message body wrapper."""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    body: str = Field(default="", description="Text message content")


class WhatsAppMessage(BaseModel):
    """Individual WhatsApp message object within webhook changes."""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    from_: str = Field(
        alias="from",
        description="Sender WhatsApp Phone ID / phone number",
    )
    id: str = Field(
        description="WhatsApp Message ID (wamid.HBg...)",
    )
    timestamp: str = Field(
        description="Epoch timestamp when the message was sent",
    )
    type: Optional[str] = Field(
        default="text",
        description="Message type (text, interactive, image, audio, video, document, etc.)",
    )
    text: Optional[Union[WhatsAppTextMessage, Dict[str, Any]]] = Field(
        default=None,
        description="Text payload object containing body",
    )
    interactive: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Interactive button or list reply",
    )
    image: Optional[Dict[str, Any]] = Field(default=None, description="Image attachment payload")
    audio: Optional[Dict[str, Any]] = Field(default=None, description="Audio/Voice attachment payload")
    video: Optional[Dict[str, Any]] = Field(default=None, description="Video attachment payload")
    document: Optional[Dict[str, Any]] = Field(default=None, description="Document attachment payload")
    location: Optional[Dict[str, Any]] = Field(default=None, description="Location coordinates payload")
    contacts: Optional[List[Dict[str, Any]]] = Field(default=None, description="Shared contact cards")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Context of replied message")
    errors: Optional[List[Dict[str, Any]]] = Field(default=None, description="Delivery or parse error details")


class WhatsAppMetadata(BaseModel):
    """Metadata regarding receiving business phone number."""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    display_phone_number: Optional[str] = Field(default=None, description="Business display phone number")
    phone_number_id: Optional[str] = Field(default=None, description="Meta phone number ID")


class WhatsAppProfile(BaseModel):
    """Profile details of message sender."""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: Optional[str] = Field(default=None, description="WhatsApp profile display name")


class WhatsAppContact(BaseModel):
    """Contact entry for message sender."""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    wa_id: Optional[str] = Field(default=None, description="Sender WhatsApp ID")
    profile: Optional[Union[WhatsAppProfile, Dict[str, Any]]] = Field(default=None, description="Sender profile")


class WhatsAppValue(BaseModel):
    """Value structure under changes in Meta webhook."""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    messaging_product: str = Field(default="whatsapp", description="Messaging product name")
    metadata: Optional[Union[WhatsAppMetadata, Dict[str, Any]]] = Field(
        default=None,
        description="Phone number metadata",
    )
    contacts: Optional[List[Union[WhatsAppContact, Dict[str, Any]]]] = Field(
        default_factory=list,
        description="Contacts list for inbound messages",
    )
    messages: Optional[List[WhatsAppMessage]] = Field(
        default_factory=list,
        description="List of incoming messages",
    )
    statuses: Optional[List[Dict[str, Any]]] = Field(
        default_factory=list,
        description="Status updates (sent, delivered, read)",
    )
    errors: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Error details if webhook event encountered an issue",
    )


class WhatsAppChange(BaseModel):
    """Change event item."""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    field: str = Field(default="messages", description="Change notification field name")
    value: WhatsAppValue = Field(description="Change value details")


class WhatsAppEntry(BaseModel):
    """Entry element within webhook payload."""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = Field(description="WhatsApp Business Account ID (WABA ID)")
    changes: List[WhatsAppChange] = Field(default_factory=list, description="Array of change events")


class WhatsAppWebhookPayload(BaseModel):
    """Root Meta WhatsApp Cloud API Webhook payload envelope."""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    object: str = Field(
        default="whatsapp_business_account",
        description="Object type, typically 'whatsapp_business_account'",
    )
    entry: List[WhatsAppEntry] = Field(
        default_factory=list,
        description="List of entry events delivered in this webhook POST",
    )
