/* Project resource controls: all actions call the authenticated Flask API. */
(() => {
  const panel = () => document.getElementById("resources-panel");
  const project = () => window.anyapiProjectId;
  const el = (tag, text) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; };
  const button = (label, action) => { const node = el("button", label); node.type="button"; node.className="secondary"; node.onclick=action; return node; };
  const formInput = (placeholder, type="text") => {const node=el("input");node.placeholder=placeholder;node.type=type;node.style.margin="6px";return node;};
  async function load() {
    if (!project() || !panel()) return;
    const root=panel();root.textContent="Loading resources…";
    try {
      const [connectors,keys] = await Promise.all([api("/projects/"+project()+"/connectors"),api("/projects/"+project()+"/api-keys")]);
      root.replaceChildren();
      const h=el("h3","HTTP connectors");
      root.append(h);
      if (!connectors.length) root.append(el("p","No connectors configured."));
      for(const c of connectors){
        const row=el("div");row.className="row";row.style.marginBottom="10px";
        row.append(el("span",c.name+" · "+(c.config?.url||c.config?.base_url||"")+" · "+(c.secret_hint?"Secret configured":"No secret")));
        row.append(button("Remove",async()=>{if(!confirm("Remove connector "+c.name+"?"))return;let res=await fetch("/_api/connectors/"+c.id,{method:"DELETE",headers:{"X-CSRF-Token":csrf}});if(!res.ok){alert("Could not delete connector");return}load()}));
        root.append(row);
      }
      const fields=el("div");fields.className="row";
      const name=formInput("Connector name"),url=formInput("https://api.example.com");
      const secret=formInput("Bearer/API token (optional)","password");
      fields.append(name,url,secret,button("Add connector",async()=>{
        if(!name.value.trim()||!url.value.trim())return alert("Name and HTTPS URL are required");
        try{await api("/projects/"+project()+"/connectors","POST",{name:name.value.trim(),type:"http",config:{url:url.value.trim(),method:"GET"},secret:secret.value});secret.value="";load()}
        catch(e){alert(e.message)}
      }));
      root.append(fields,el("hr"),el("h3","API keys"));
      if (!keys.length)root.append(el("p","No API keys created."));
      for(const k of keys){
        const row=el("div");row.className="row";row.style.marginBottom="10px";
        row.append(el("span",k.name+" · "+k.prefix+(k.revoked_at?" · revoked":"")));
        if(!k.revoked_at)row.append(button("Revoke",async()=>{if(!confirm("Revoke key "+k.name+"?"))return;try{await api("/api-keys/"+k.id+"/revoke","POST",{});load()}catch(e){alert(e.message)}}));
        root.append(row);
      }
      const keyRow=el("div");keyRow.className="row";
      const keyName=formInput("Key name");
      const scope=el("select");
      for(const [value,label] of [["","Entire project"],[id,"This endpoint only"]]){let opt=el("option",label);opt.value=value;scope.append(opt)}
      keyRow.append(keyName,scope,button("Create API key",async()=>{
        if(!keyName.value.trim())return alert("Key name required");
        try{
          const result=await api("/projects/"+project()+"/api-keys","POST",{name:keyName.value.trim(),endpoint_id:scope.value||null});
          const wrap=el("div");const heading=el("strong","Copy this API key now; it will not be shown again.");
          const value=el("pre",result.key);const copy=button("Copy key",()=>navigator.clipboard?.writeText(result.key));
          wrap.append(heading,value,copy);root.prepend(wrap);keyName.value="";
        }catch(e){alert(e.message)}
      }));
      root.append(keyRow);
    }catch(e){root.textContent="Unable to load project resources: "+e.message}
  }
  window.loadResources=load;
  if(project())load();
})();
