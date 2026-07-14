"""Base62 encoding for turning a numeric DB id into a compact short code.

Base62 uses [0-9a-zA-Z] (62 symbols). Encoding the auto-increment primary key
means every code is unique by construction — no random generation, no
collision-retry loop. A 7-character base62 code addresses 62^7 ≈ 3.5 trillion
URLs, which is plenty for this design.
"""

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE = len(ALPHABET)


def encode(num: int) -> str:
    """Encode a non-negative integer into a base62 string."""
    if num < 0:
        raise ValueError("Cannot encode a negative number")
    if num == 0:
        return ALPHABET[0]
    chars = []
    while num > 0:
        num, rem = divmod(num, BASE)
        chars.append(ALPHABET[rem])
    return "".join(reversed(chars))


def decode(code: str) -> int:
    """Decode a base62 string back into its integer value."""
    num = 0
    for char in code:
        num = num * BASE + ALPHABET.index(char)
    return num
