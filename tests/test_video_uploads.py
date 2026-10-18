"""Direct-upload helpers accept known media types and never trust filenames."""
import pytest
from video_studio.uploads import validate_upload, allowed_path

@pytest.mark.parametrize("mime,ext",[
    ("image/png",".png"),("image/jpeg",".jpg"),("image/webp",".webp"),
    ("video/mp4",".mp4"),("audio/mpeg",".mp3"),("audio/wav",".wav")
])
def test_supported_media(mime,ext):
    assert validate_upload(mime,1024)[0]==ext

@pytest.mark.parametrize("mime,size",[("text/html",10),("video/mp4",100_000_001),
                                    ("image/png",0),("video/mp4",-1)])
def test_invalid_media_rejected(mime,size):
    with pytest.raises(ValueError):validate_upload(mime,size)

def test_path_is_owner_and_scene_scoped():
    assert allowed_path("owner/project/scene/manual-foo.mp4","owner","project","scene")
    assert not allowed_path("owner/project/other/manual-foo.mp4","owner","project","scene")
    assert not allowed_path("owner/project/scene/../../other","owner","project","scene")
