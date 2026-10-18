"""Video trim selection must be pure and bounded before invoking ffmpeg."""
import pytest
from video_studio.workflow import validate_trim_start

def test_trim_start_defaults_to_zero():
    assert validate_trim_start(None)==0

def test_trim_start_accepts_seconds():
    assert validate_trim_start(1.25)==1.25

@pytest.mark.parametrize("value",[-1,601,"bad",True])
def test_trim_start_rejects_invalid(value):
    with pytest.raises(ValueError):validate_trim_start(value)
