/* AnyAPI V1: endpoint-scoped API key management (functions are centrally registered). */
(() => {
 const view=()=>document.getElementById("resources-panel");
 const project=()=>window.anyapiProjectId;
 const el=(tag,value)=>{let x=document.createElement(tag);if(value!==undefined)x.textContent=value;return x};
 function button(name,fn){let b=el("button",name);b.type="button";b.className="secondary";b.onclick=fn;return b}
 async function load(){
  if(!project()||!view())return;
  let root=view();root.textContent="Loading keys…";
  try{
   let keys=await api("/projects/"+project()+"/api-keys");
   root.replaceChildren(el("h3","API keys"),el("p","For a private endpoint, callers must provide a valid Bearer API key."));
   for(let key of keys){
    let row=el("div");row.className="row";row.style.marginBottom="10px";
    row.append(el("span",key.name+" · "+key.prefix+(key.revoked_at?" (revoked)":"")));
    if(!key.revoked_at)row.append(button("Revoke",async()=>{if(!confirm("Revoke this API key?"))return;await api("/api-keys/"+key.id+"/revoke","POST",{});load()}));
    root.append(row);
   }
   let form=el("div");form.className="row";
   let name=el("input");name.placeholder="API key name";
   let scope=el("select");
   for(const [value,label] of [["","Entire project"],[id,"This endpoint"]]){let option=el("option",label);option.value=value;scope.append(option)}
   form.append(name,scope,button("Create key",async()=>{
    if(!name.value.trim())return;
    try{
     let result=await api("/projects/"+project()+"/api-keys","POST",{name:name.value.trim(),endpoint_id:scope.value||null});
     let secret=el("div");secret.append(el("strong","Copy now: this key is shown only once."),el("pre",result.key),button("Copy",()=>navigator.clipboard?.writeText(result.key)));
     root.prepend(secret);
    }catch(error){alert(error.message)}
   }));
   root.append(form);
  }catch(error){root.textContent="Could not load keys: "+error.message}
 }
 window.loadResources=load;
 if(project())load();
})();