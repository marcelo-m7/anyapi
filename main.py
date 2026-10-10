"""AnyAPI Flask entry point (Vercel WSGI-compatible)."""
from flask import Flask, jsonify, render_template_string, request
from anyapi.config import load_settings
from anyapi.supabase import Supabase
from anyapi.security import SecretBox
from anyapi.runtime.code_runner import CodeRunner
from anyapi.auth import bp as auth_bp, csrf_token, current_user
from anyapi.management import bp as management_bp
from anyapi.gateway import bp as gateway_bp

settings = load_settings()
app = Flask(__name__)
app.secret_key = settings.secret_key
app.config["ANYAPI_SETTINGS"] = settings
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=settings.is_production,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=settings.max_payload_bytes,
    ANYAPI_PUBLIC_URL=settings.public_base_url,
)
app.extensions["anyapi.supabase"] = Supabase(settings)
app.extensions["anyapi.secrets"] = SecretBox(settings.encryption_key_material or settings.secret_key)
app.extensions["anyapi.runner"] = CodeRunner(settings.runner_url, settings.runner_token)
app.jinja_env.globals["csrf_token"] = csrf_token
app.register_blueprint(auth_bp)
app.register_blueprint(management_bp)

@app.get("/")
def landing():
    return render_template_string("""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AnyAPI — Build APIs in minutes</title>
<style>body{background:#0b0d13;color:#f5f7fc;font:16px system-ui;margin:0}main{max-width:950px;margin:10vh auto;padding:30px}h1{font-size:clamp(3rem,9vw,6rem);letter-spacing:-.07em;margin-bottom:0}p{color:#abb3c5;font-size:1.25rem}a{color:#8dd9ff}nav{display:flex;justify-content:space-between}code{color:#88f3c1}section{background:#171b25;border:1px solid #31394a;border-radius:18px;padding:25px;margin-top:30px}</style>
<main><nav><strong>AnyAPI</strong><a href="/login">Sign in</a></nav>
<h1>Build APIs in minutes.</h1><p>Connect. Process. Publish. No infrastructure required.</p>
<a href="/signup">Start building →</a><section><code>POST https://anyapi.tech/username/project/endpoint</code><p>Define input and output schemas, add processing steps, test and publish.</p></section></main></html>""")

@app.get("/health")
def health():
    return jsonify(status="ok", service="anyapi")

@app.get("/dashboard")
def dashboard():
    if not current_user():
        from flask import redirect, url_for
        return redirect(url_for("auth.login"))
    return render_template_string("""<!doctype html><html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AnyAPI Studio</title><style>body{background:#10131b;color:white;font:16px system-ui;margin:5vw auto;max-width:950px;padding:20px}a{color:#86d9fd}button,input,textarea{padding:10px;border-radius:7px}article{padding:20px;border:1px solid #344050;border-radius:12px;margin:15px 0}</style>
<h1>AnyAPI Studio</h1><p>Welcome, {{ user.username }}.</p><button onclick="newProject()">+ New project</button><div id="projects">Loading projects…</div>
<script>
const csrf={{ csrf|tojson }};
async function api(path,options={}){let r=await fetch('/_api'+path,{...options,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf,...(options.headers||{})}});let j=await r.json();if(!r.ok)throw Error(j.error||JSON.stringify(j));return j}
async function load(){try{let data=await api('/projects');document.getElementById('projects').replaceChildren(...data.map(p=>{let x=document.createElement('article');let h=document.createElement('h2');h.textContent=p.name;let b=document.createElement('button');b.textContent='Create endpoint';b.onclick=()=>newEndpoint(p.id);x.append(h,document.createTextNode(p.slug+' · '+p.description),b);let area=document.createElement('div');x.append(area);api('/projects/'+p.id+'/endpoints').then(es=>{es.forEach(e=>{let a=document.createElement('a');a.href='/'+encodeURIComponent({{ user.username|tojson }})+'/'+encodeURIComponent(p.slug)+'/'+encodeURIComponent(e.slug);a.textContent=e.method+' '+e.slug+' ('+e.status+')';area.append(a,document.createElement('br'))})});return x}));}catch(e){document.getElementById('projects').textContent=e.message}}
async function newProject(){let name=prompt('Project name');if(!name)return;let slug=prompt('Project slug',name.toLowerCase().replace(/[^a-z0-9]+/g,'-'));if(!slug)return;try{await api('/projects',{method:'POST',body:JSON.stringify({name,slug})});load()}catch(e){alert(e.message)}}
async function newEndpoint(project){let name=prompt('Endpoint name');if(!name)return;let slug=prompt('Endpoint slug',name.toLowerCase().replace(/[^a-z0-9]+/g,'-'));if(!slug)return;try{await api('/projects/'+project+'/endpoints',{method:'POST',body:JSON.stringify({name,slug})});load()}catch(e){alert(e.message)}}
load()
</script></html>""",user=current_user(),csrf=csrf_token())

app.register_blueprint(gateway_bp)
