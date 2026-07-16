"""SHA-256 content hashing for document nodes."""

import hashlib


def compute_content_hash(heading: str, body_text: str) -> str:
    """Generate a SHA-256 hash from a node's heading and body text.

    Args:
        heading: The section heading text.
        body_text: The body text content of the node.

    Returns:
        Hex-encoded SHA-256 hash string.
    """
    raw = f"{heading}||{body_text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
