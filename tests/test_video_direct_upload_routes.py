from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from main import app

def test_signed_upload_routes_require_authenticated_session():
    c=app.test_client()
    p="00000000-0000-0000-0000-000000000000"
    for endpoint in ("upload-intent","commit"):
        response=c.post(f"/_api/video-studio/projects/{p}/media/{endpoint}",json={})
        assert response.status_code==401
