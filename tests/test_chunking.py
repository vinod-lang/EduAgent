import pytest
from chunking import chunk_text

@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_empty(text):
    assert chunk_text(text) == []

def test_short():
    assert chunk_text(" Short text ") == ["Short text"]

def test_overlap():
    text = "0123456789ABCDEFGHIJ"
    assert chunk_text(text, 10, 2) == [text[:10], text[8:18], text[16:]]

def test_large_default():
    assert list(map(len, chunk_text("a" * 1200))) == [500,500,300]

@pytest.mark.parametrize("size,overlap", [(0,0),(-1,0),(10,-1),(10,10),(10,11),(1.5,0),(10,1.5),(True,0)])
def test_invalid(size,overlap):
    with pytest.raises(ValueError): chunk_text("text",size,overlap)
