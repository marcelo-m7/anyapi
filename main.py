"""AnyAPI Flask entry point (Vercel WSGI-compatible)."""
from flask import Flask, jsonify, render_template_string, request
from anyapi.config import load_settings
from anyapi.supabase import Supabase
from anyapi.security import SecretBox
from anyapi.runtime.code_runner import CodeRunner
from anyapi.auth import bp as auth_bp, csrf_token, current_user
from anyapi.management import bp as management_bp
from anyapi.gateway import bp as gateway_bp
from anyapi.schema_editor import bp as schema_editor_bp
from flask import send_from_directory
from pathlib import Path

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
app.register_blueprint(schema_editor_bp)

@app.get("/assets/<path:filename>")
def assets(filename):
    return send_from_directory(Path(__file__).parent / "public", filename)

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
async function load(){try{let data=await api('/projects');document.getElementById('projects').replaceChildren(...data.map(p=>{let x=document.createElement('article');let h=document.createElement('h2');h.textContent=p.name;let b=document.createElement('button');b.textContent='Create endpoint';b.onclick=()=>newEndpoint(p.id);x.append(h,document.createTextNode(p.slug+' · '+p.description),b);let area=document.createElement('div');x.append(area);api('/projects/'+p.id+'/endpoints').then(es=>{es.forEach(e=>{let a=document.createElement('a');a.href='/studio/endpoints/'+encodeURIComponent(e.id);a.textContent=e.method+' '+e.slug+' ('+e.status+')';area.append(a,document.createElement('br'))})});return x}));}catch(e){document.getElementById('projects').textContent=e.message}}
async function newProject(){let name=prompt('Project name');if(!name)return;let slug=prompt('Project slug',name.toLowerCase().replace(/[^a-z0-9]+/g,'-'));if(!slug)return;try{await api('/projects',{method:'POST',body:JSON.stringify({name,slug})});load()}catch(e){alert(e.message)}}
async function newEndpoint(project){let name=prompt('Endpoint name');if(!name)return;let slug=prompt('Endpoint slug',name.toLowerCase().replace(/[^a-z0-9]+/g,'-'));if(!slug)return;try{await api('/projects/'+project+'/endpoints',{method:'POST',body:JSON.stringify({name,slug})});load()}catch(e){alert(e.message)}}
load()
</script></html>""",user=current_user(),csrf=csrf_token())


@app.get("/studio/endpoints/<endpoint_id>")
def studio_endpoint(endpoint_id):
    from flask import abort, redirect, url_for
    user=current_user()
    if not user:return redirect(url_for("auth.login"))
    return render_template_string("""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Endpoint Builder · AnyAPI</title>
<style>body{background:#0b1019;color:#eaf1fa;font:15px system-ui;margin:0}header{border-bottom:1px solid #313b50;padding:18px 5vw;display:flex;align-items:center;gap:16px}main{max-width:1050px;margin:auto;padding:32px 20px}a{color:#8fdefb}h1{margin:12px 0}textarea,input,select{background:#121c2c;color:white;border:1px solid #41516b;border-radius:9px;padding:10px}textarea{box-sizing:border-box;width:100%;font:13px ui-monospace,monospace;min-height:210px}button{background:#a0e8fc;color:#101724;border:0;border-radius:8px;padding:11px 17px;cursor:pointer}button.secondary{background:#253449;color:white}nav{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0}nav button.active{background:#a0e8fc;color:#111}section{border:1px solid #344158;border-radius:14px;padding:24px;background:#141d2b}label{display:block;margin-bottom:14px}.row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.hide{display:none}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#101622;padding:20px;border-radius:8px}small{color:#b2bfd0}</style>
<header><a href="/dashboard">← Projects</a><strong>AnyAPI / Endpoint Builder</strong></header>
<main><h1 id="title">Loading…</h1><p><small id="status"></small></p>
<nav><button onclick="tab('overview')" id="b-overview">Overview</button><button onclick="tab('input')" id="b-input">Input</button><button onclick="tab('processor')" id="b-processor">Processor</button><button onclick="tab('output')" id="b-output">Output</button><button onclick="tab('test')" id="b-test">Test</button><button onclick="tab('logs')" id="b-logs">Logs</button><button onclick="tab('resources')" id="b-resources">API Keys</button></nav>
<section id="overview"><label>Name <input id="name"></label><label>Description <input id="description"></label><div class="row"><label>HTTP method <select id="method"><option>POST</option><option>GET</option><option>PUT</option><option>PATCH</option><option>DELETE</option></select></label><label>Visibility <select id="visibility"><option>public</option><option>private</option></select></label></div></section>
<section id="input" class="hide"><h2>Input JSON Schema</h2><p><small>JSON Schema editor. Visual drag-and-drop coming later.</small></p><textarea id="input_schema"></textarea></section>
<section id="processor" class="hide"><h2>Processor</h2><p><small>Visual steps or code (isolated runner required for code).</small></p><textarea id="processor_code"></textarea></section>
<section id="output" class="hide"><h2>Output JSON Schema</h2><textarea id="output_schema"></textarea></section>
<section id="test" class="hide"><h2>Test draft</h2><textarea id="payload">{}</textarea><p><button onclick="test()">Run Test</button></p><pre id="test_result">No test executed</pre></section>
<section id="logs" class="hide"><h2>Recent executions</h2><button onclick="logs()">Refresh</button><pre id="log_result">No logs loaded</pre></section>
<section id="resources" class="hide"><h2>Project resources</h2><p><small>Scoped API keys; Edge Functions are centrally managed</small></p><div id="resources-panel">Loading...</div></section><div class="row" style="margin-top:20px"><button onclick="save()">Save draft</button><button class="secondary" onclick="publish()">Publish</button><button class="secondary" onclick="versions()">Versions</button><small id="message"></small></div><pre id="versions" class="hide"></pre>
</main><script>
const id={{ endpoint_id|tojson }},csrf={{ csrf|tojson }};
const by=id=>document.getElementById(id);
async function api(path,method='GET',data){let r=await fetch('/_api'+path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:data===undefined?undefined:JSON.stringify(data)});let j=await r.json();if(!r.ok)throw Error(JSON.stringify(j));return j;}
function tab(n){for(const x of ['overview','input','processor','output','test','logs','resources']){by(x).classList.toggle('hide',n!==x);by('b-'+x).classList.toggle('active',n===x)}}
async function load(){try{let e=await api('/endpoints/'+id);by('title').textContent=e.name;window.anyapiProjectId=e.project_id;if(window.loadResources)window.loadResources();by('status').textContent=e.method+' · '+e.status+' · '+e.slug;for(let k of ['name','description','method','visibility'])by(k).value=e[k]||'';for(let k of ['input_schema','output_schema'])by(k).value=JSON.stringify(e[k],null,2);by('processor_code').value=JSON.stringify(e.processor,null,2);if(window.anyapiPipelineRefresh)window.anyapiPipelineRefresh();tab('overview')}catch(err){by('message').textContent=err.message}}
async function values(){let ins=await api('/schema/convert','POST',{format:by('input_schema').value.trim().startsWith('{')?'json':'yaml',text:by('input_schema').value});let outs=await api('/schema/convert','POST',{format:by('output_schema').value.trim().startsWith('{')?'json':'yaml',text:by('output_schema').value});return {name:by('name').value,description:by('description').value,method:by('method').value,visibility:by('visibility').value,input_schema:ins.schema,output_schema:outs.schema,processor:JSON.parse(by('processor_code').value)}}
async function save(){try{await api('/endpoints/'+id,'PATCH',await values());by('message').textContent='Draft saved';await load()}catch(err){by('message').textContent=err.message}}
async function publish(){try{await save();let v=await api('/endpoints/'+id+'/publish','POST',{});by('message').textContent='Published version '+v.version;await load()}catch(err){by('message').textContent=err.message}}
async function test(){try{let res=await api('/endpoints/'+id+'/test','POST',JSON.parse(by('payload').value));by('test_result').textContent=JSON.stringify(res,null,2)}catch(err){by('test_result').textContent=err.message}}
async function logs(){try{by('log_result').textContent=JSON.stringify(await api('/endpoints/'+id+'/executions'),null,2)}catch(err){by('log_result').textContent=err.message}}
async function versions(){try{by('versions').classList.remove('hide');by('versions').textContent=JSON.stringify(await api('/endpoints/'+id+'/versions'),null,2)}catch(err){by('message').textContent=err.message}}
load();
</script><script src="/assets/schema-builder.js"></script><script src="/assets/studio-resources.js"></script><script src="/assets/pipeline-builder.js"></script></html>""",endpoint_id=endpoint_id,csrf=csrf_token())

app.register_blueprint(gateway_bp)
