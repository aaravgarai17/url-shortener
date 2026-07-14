import pytest

from app import base62


@pytest.mark.parametrize("num", [0, 1, 61, 62, 12345, 3521614606207])
def test_encode_decode_roundtrip(num):
    assert base62.decode(base62.encode(num)) == num


def test_encoding_is_unique_and_monotonic_length():
    codes = {base62.encode(i) for i in range(1000)}
    assert len(codes) == 1000  # no collisions


def test_negative_raises():
    with pytest.raises(ValueError):
        base62.encode(-1)
