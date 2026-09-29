"""Identifiers of the notification service's own things; the shared kinds live in the kernel."""

from dataclasses import dataclass

from domain_kernel.ids import EntityId


@dataclass(frozen=True, slots=True)
class RecipientId(EntityId):
    """A person who receives a business's notifications. For someone who signs in to the web
    app it is their user id; the caller chooses it when registering the recipient."""


@dataclass(frozen=True, slots=True)
class DispatchId(EntityId):
    """One delivery to a channel. Items coalesced into one message share it."""
