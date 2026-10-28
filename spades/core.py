"""Data contracts, ingestion, and retrieval defense. No model dependencies."""

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
import secrets


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Document:
    source_id: str
    text: str
    author_role: str = "editor"
    access: int = 0
    channel_trust: float = 0.9
    timestamp: str = "2026-10-28T00:00:00+00:00"

    def __post_init__(self):
        if not self.source_id or not self.text or len(self.text) > 1_000_000:
            raise ValueError("A source ID and 1–1,000,000 text characters are required")
        if self.access not in (0, 1, 2) or not 0 <= self.channel_trust <= 1:
            raise ValueError("Access must be 0–2 and channel trust must be 0–1")
        if self.author_role not in ("editor", "admin", "external"):
            raise ValueError("Unknown author role")
        if datetime.fromisoformat(self.timestamp).tzinfo is None:
            raise ValueError("Timestamp must include a timezone")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source_id: str
    text: str
    document_hash: str
    author_role: str
    access: int
    channel_trust: float
    timestamp: str
    token: str = ""


def split_document(doc: Document, size: int = 700, overlap: int = 100, adaptive: bool = False) -> list[Chunk]:
    if not 0 <= overlap < size:
        raise ValueError("Overlap must be nonnegative and smaller than chunk size")
    result = []
    start = 0
    document_hash = digest(doc.text)
    while start < len(doc.text):
        end = min(start + size, len(doc.text))
        if adaptive and end < len(doc.text):
            boundary = doc.text.rfind("\n\n", start + max(size // 2, overlap + 1), end)
            if boundary > start + overlap:
                end = boundary + 2
        result.append(Chunk(f"{doc.source_id}:{start}", doc.source_id,
                            doc.text[start:end], document_hash,
                            doc.author_role, doc.access, doc.channel_trust, doc.timestamp))
        if end >= len(doc.text):
            break
        start = end - overlap
    return result


class Registry:
    """Trusted ingestion authority, kept outside the attacker-controlled index.

    The registry signs complete chunk envelopes, including identity and ACLs.
    SHA-256 identifies the source; HMAC authenticates the retrieved envelope.
    """

    def __init__(self):
        self._key = secrets.token_bytes(32)
        self._approved: dict[str, str] = {}

    def _sign(self, chunk: Chunk) -> str:
        data = asdict(chunk)
        data.pop("token")
        return hmac.new(self._key, json.dumps(data, sort_keys=True).encode(), "sha256").hexdigest()

    def approve(self, doc: Document, size: int = 700, overlap: int = 100, adaptive: bool = False) -> list[Chunk]:
        if doc.source_id in self._approved:
            raise ValueError("Source ID already registered")
        self._approved[doc.source_id] = digest(doc.text)
        return [replace(c, token=self._sign(c)) for c in split_document(doc, size, overlap, adaptive)]

    def verify(self, chunk: Chunk) -> bool:
        try:
            return (self._approved.get(chunk.source_id) == chunk.document_hash
                    and isinstance(chunk.token, str)
                    and hmac.compare_digest(chunk.token, self._sign(chunk)))
        except (TypeError, ValueError):
            return False


PATTERNS = [
    r"ignore\s+(?:all\s+)?previous\s+instructions",
    r"system\s+override", r"you\s+are\s+now\s+in\s+DAN\s+mode",
    r"(?:print|reveal|output|return)\s+(?:the\s+)?(?:secret|canary|SPADES_ATTACK_SUCCESS)",
    r"https?://[^\s<>]+", r"</?(?:system|context|instructions)\b",
]
SUSPICIOUS = re.compile("|".join(PATTERNS), re.IGNORECASE)


@dataclass
class Decision:
    chunk_id: str
    allowed: bool
    trust: float
    reason: str
    sanitized_text: str | None = None


class Defense:
    def __init__(self, registry: Registry, threshold: float = 0.7,
                 clearance: int = 0, blacklist: set[str] | None = None, policy: str = "strict"):
        if not 0 <= threshold <= 1 or clearance not in (0, 1, 2):
            raise ValueError("Invalid trust threshold or clearance")
        self.registry, self.threshold, self.clearance = registry, threshold, clearance
        self.blacklist = blacklist or set()
        if policy not in ("strict", "sanitize"):
            raise ValueError("Unknown sanitization policy")
        self.policy = policy

    def inspect(self, chunk: Chunk, now: datetime | None = None) -> Decision:
        def reject(reason):
            return Decision(chunk.chunk_id, False, 0.0, reason)
        if chunk.source_id in self.blacklist:
            return reject("Source is blocked")
        if not self.registry.verify(chunk):
            return reject("Unknown source or modified signed envelope")
        if chunk.access > self.clearance:
            return reject("Insufficient access clearance")
        current = now or datetime.now(timezone.utc)
        age = (current - datetime.fromisoformat(chunk.timestamp)).total_seconds() / 86400
        if age < -1:
            return reject("Source timestamp is in the future")
        freshness = max(0.0, 1 - max(0, age) / 365)
        role = {"admin": 1.0, "editor": 0.85, "external": 0.2}[chunk.author_role]
        trust = round(0.4 * chunk.channel_trust + 0.3 + 0.15 * freshness + 0.15 * role, 4)
        if trust < self.threshold:
            return Decision(chunk.chunk_id, False, trust, "Below trust threshold")
        text = chunk.text
        if self.policy == "sanitize":
            # Only transform content after authenticating its original envelope.
            def neutralize_quote(match):
                return "[quoted instruction removed]" if SUSPICIOUS.search(match[0]) else match[0]
            text = re.sub(r'"[^"\n]{1,500}"', neutralize_quote, text)
            text = re.sub(r"https?://[^\s<>]+", "[external reference removed]", text, flags=re.IGNORECASE)
        if SUSPICIOUS.search(text):
            return Decision(chunk.chunk_id, False, trust, "Suspicious instruction or external URL")
        if text != chunk.text:
            return Decision(chunk.chunk_id, True, trust, "Verified; quoted instructions or URLs neutralized", text)
        return Decision(chunk.chunk_id, True, trust, "Verified and permitted")

    def filter(self, chunks: list[Chunk]) -> tuple[list[Chunk], list[Decision]]:
        decisions = [self.inspect(c) for c in chunks]
        ranked = sorted(zip(chunks, decisions), key=lambda pair: pair[1].trust, reverse=True)
        return [replace(c, text=d.sanitized_text) if d.sanitized_text is not None else c
                for c, d in ranked if d.allowed], decisions
