"""The identity service's signing keys: ES256 on the P-256 curve.

A key set is stored as a JSON array of ``{"kid": ..., "pem": ...}`` records, each ``pem`` a PKCS#8
private key (``CW_IDENTITY_SIGNING_KEYS``). The first key signs; every key is published in the
JWKS, so a new key can be added second, published for longer than verifiers cache keys (an hour),
and then moved to the front. Tokens name their key by ``kid``.
"""

import json
from dataclasses import dataclass
from typing import Any, Final

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

ALGORITHM: Final = "ES256"
"""The only algorithm tokens are signed and verified with."""
MAX_KID_CHARS: Final = 64


def is_signing_curve(candidate: object) -> bool:
    """Whether ``candidate`` is a P-256 elliptic-curve key, public or private: what ES256 uses."""
    if not isinstance(candidate, ec.EllipticCurvePublicKey | ec.EllipticCurvePrivateKey):
        return False
    return isinstance(candidate.curve, ec.SECP256R1)


@dataclass(frozen=True, slots=True)
class SigningKey:
    """One private key and the ``kid`` tokens signed with it carry in their header."""

    kid: str
    private_key: ec.EllipticCurvePrivateKey

    def __post_init__(self) -> None:
        if not isinstance(self.kid, str) or not self.kid.strip() or self.kid != self.kid.strip():
            raise ValueError("a signing key needs a kid without surrounding whitespace")
        if len(self.kid) > MAX_KID_CHARS:
            raise ValueError(f"a kid has at most {MAX_KID_CHARS} characters")
        if not is_signing_curve(self.private_key):
            raise ValueError(f"signing key {self.kid!r} is not a P-256 elliptic-curve key")

    def public_jwk(self) -> dict[str, Any]:
        """The public half as a JWK, with its ``kid``, ``use`` and ``alg``."""
        jwk = ECAlgorithm.to_jwk(self.private_key.public_key(), as_dict=True)
        return {**jwk, "kid": self.kid, "use": "sig", "alg": ALGORITHM}

    def private_pem(self) -> str:
        """The private key as unencrypted PKCS#8 PEM, for the key set's JSON record."""
        return self.private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii")

    def record(self) -> dict[str, str]:
        return {"kid": self.kid, "pem": self.private_pem()}


@dataclass(frozen=True, slots=True)
class KeySet:
    """Signing keys, the first of which signs. Every key is published."""

    keys: tuple[SigningKey, ...]

    def __post_init__(self) -> None:
        if not self.keys:
            raise ValueError("a key set needs at least one signing key")
        kids = [key.kid for key in self.keys]
        if len(set(kids)) != len(kids):
            raise ValueError(f"signing key ids must be unique, got {kids}")

    @property
    def signing_key(self) -> SigningKey:
        return self.keys[0]

    def public_jwks(self) -> dict[str, Any]:
        """The JWKS document: ``{"keys": [...]}`` with the public half of every key."""
        return {"keys": [key.public_jwk() for key in self.keys]}

    def dumps(self) -> str:
        """The JSON array of ``{"kid", "pem"}`` records ``load_signing_keys`` reads."""
        return json.dumps([key.record() for key in self.keys], indent=2)


def generate_signing_key(kid: str) -> SigningKey:
    """A fresh P-256 key named ``kid``."""
    return SigningKey(kid, ec.generate_private_key(ec.SECP256R1()))


def load_signing_keys(text: str) -> KeySet:
    """The key set in ``text``: a JSON array of ``{"kid", "pem"}`` records. Anything else is a
    ValueError that names the problem but never the key material."""
    try:
        records = json.loads(text)
    except ValueError as exc:
        raise ValueError("signing keys must be a JSON array of {kid, pem} records") from exc
    if not isinstance(records, list) or not records:
        raise ValueError("signing keys must be a non-empty JSON array of {kid, pem} records")
    return KeySet(tuple(_load_record(record, index) for index, record in enumerate(records)))


def _load_record(record: object, index: int) -> SigningKey:
    if not isinstance(record, dict) or set(record) != {"kid", "pem"}:
        raise ValueError(f"signing key {index} must be an object with exactly kid and pem")
    kid, pem = record["kid"], record["pem"]
    if not isinstance(kid, str) or not isinstance(pem, str):
        raise ValueError(f"signing key {index}: kid and pem must be strings")
    try:
        private_key = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
    except (ValueError, TypeError, UnicodeEncodeError) as exc:
        raise ValueError(f"signing key {kid!r} is not an unencrypted PEM private key") from exc
    if not isinstance(private_key, ec.EllipticCurvePrivateKey):
        raise ValueError(f"signing key {kid!r} is not a P-256 elliptic-curve key")
    return SigningKey(kid, private_key)
