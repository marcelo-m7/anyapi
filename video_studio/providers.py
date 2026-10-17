"""Private media, AI images, voice and video providers. Credentials are server-side."""
import base64
import os
from urllib.parse import quote
import requests

class ProviderError(RuntimeError): pass

def env(name):
    value=os.getenv(name,"").strip()
    if not value: raise ProviderError("Missing environment variable: "+name)
    return value

def openai_json(path,payload):
    r=requests.post("https://api.openai.com/v1/"+path,headers={"Authorization":"Bearer "+env("OPENAI_API_KEY")},json=payload,timeout=120)
    if not r.ok:raise ProviderError("OpenAI HTTP "+str(r.status_code)+": "+r.text[:200])
    return r.json()

def image(prompt,portrait=False):
    result=openai_json("images/generations",{
        "model":os.getenv("STUDIO_IMAGE_MODEL","gpt-image-1"),
        "size":"1024x1536" if portrait else "1536x1024",
        "quality":"medium","n":1,"prompt":prompt[:8000]})
    return base64.b64decode(result["data"][0]["b64_json"])

def voice(text):
    if not text.strip(): raise ProviderError("Cannot synthesize empty narration")
    r=requests.post("https://api.openai.com/v1/audio/speech",
        headers={"Authorization":"Bearer "+env("OPENAI_API_KEY")},
        json={"model":os.getenv("STUDIO_VOICE_MODEL","gpt-4o-mini-tts"),
              "voice":os.getenv("STUDIO_VOICE","coral"),"input":text[:4096],"response_format":"mp3"},
        timeout=120)
    if not r.ok:raise ProviderError("TTS HTTP "+str(r.status_code)+": "+r.text[:200])
    return r.content

def video(prompt,image_bytes=None):
    """Runway SDK handles task polling; output is downloaded and stored privately."""
    try:from runwayml import RunwayML
    except ImportError as exc:raise ProviderError("Install runwayml to use video generation") from exc
    client=RunwayML(api_key=env("RUNWAYML_API_SECRET"))
    params={"model":os.getenv("STUDIO_VIDEO_MODEL","gen4.5"),
            "prompt_text":prompt[:1000],"ratio":"1280:720","duration":5}
    if image_bytes:params["prompt_image"]="data:image/png;base64,"+base64.b64encode(image_bytes).decode()
    task=client.image_to_video.create(**params).wait_for_task_output()
    if not task.output:raise ProviderError("Video provider returned no assets")
    url=str(task.output[0])
    if not url.startswith("https://"):raise ProviderError("Unexpected provider asset URL")
    response=requests.get(url,timeout=180,stream=True)
    response.raise_for_status()
    data=bytearray()
    for chunk in response.iter_content(256*1024):
        data.extend(chunk)
        if len(data)>100_000_000:raise ProviderError("Generated video exceeds 100 MB")
    return bytes(data)

class Media:
    def __init__(self):
        self.root=env("SUPABASE_URL").rstrip("/")+"/storage/v1"
        self.key=env("SUPABASE_SERVICE_ROLE_KEY")
        self.bucket="video-studio"
    def headers(self):
        return {"apikey":self.key,**({} if self.key.startswith("sb_secret_") else {"Authorization":"Bearer "+self.key})}
    def put(self,path,data,mime):
        if not data:raise ProviderError("Cannot store empty file")
        r=requests.post(self.root+"/object/"+self.bucket+"/"+quote(path,safe="/"),
            data=data,headers={**self.headers(),"Content-Type":mime,"x-upsert":"true"},timeout=180)
        if not r.ok:raise ProviderError("Upload HTTP "+str(r.status_code)+": "+r.text[:200])
        return path
    def get(self,path):
        r=requests.get(self.root+"/object/"+self.bucket+"/"+quote(path,safe="/"),
            headers=self.headers(),timeout=180)
        if not r.ok:raise ProviderError("Download HTTP "+str(r.status_code))
        return r.content
    def signed(self,path,seconds=600):
        r=requests.post(self.root+"/object/sign/"+self.bucket+"/"+quote(path,safe="/"),
            json={"expiresIn":seconds},headers=self.headers(),timeout=20)
        if not r.ok:raise ProviderError("Signed URL HTTP "+str(r.status_code))
        url=r.json()["signedURL"]
        return self.root+url if url.startswith("/") else url
