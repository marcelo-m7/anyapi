/* Studio V1: ordered catalogue-backed Edge Function steps. */
(() => {
 const root=()=>document.getElementById("processor");
 const textarea=()=>document.getElementById("processor_code");
 const make=(tag,label)=>{const n=document.createElement(tag);if(label!==undefined)n.textContent=label;return n;};
 const banner=make("div");
 let catalog=[];
 async function initialize(){
  if(!root()||!textarea())return;
  const heading=make("h3","Edge Function Pipeline");
  const help=make("p","Choose registered functions and map inputs from the request or a previous step. Each step uses the standard {success,data,error,meta} response.");
  const add=make("select");add.id="edge-function-picker";
  const addButton=make("button","Add function");addButton.type="button";
  const rows=make("div");rows.id="edge-pipeline-rows";
  const output=make("input");output.placeholder="Output expression, e.g. {{steps.step1.data}}";output.style.width="95%";
  const label=make("label","Final output mapping");
  label.append(output);
  const editor=make("div");editor.id="edge-pipeline-builder";editor.append(heading,help,add,addButton,rows,label,banner);
  textarea().before(editor);
  let current={type:"edge_pipeline",steps:[],output:""};
  const slugId=()=>{let index=1;while(current.steps.some(x=>x.id==="step"+index))index++;return "step"+index};
  function save(){current.output=output.value.trim()||undefined;textarea().value=JSON.stringify(current,null,2)}
  function draw(){
   rows.replaceChildren();add.replaceChildren();
   catalog.forEach(f=>{const opt=make("option",f.title+" ("+f.slug+")");opt.value=f.slug;add.append(opt)});
   current.steps.forEach((step,index)=>{
    const box=make("div");box.style.cssText="border:1px solid #35445c;padding:14px;margin:10px 0;border-radius:12px";
    const title=make("strong",(index+1)+". "+step.function+" · "+step.id);
    const args=make("textarea");args.style.minHeight="96px";args.value=JSON.stringify(step.arguments||{},null,2);
    const row=make("div");row.className="row";
    const up=make("button","↑");up.type="button";up.className="secondary";up.disabled=index===0;
    const down=make("button","↓");down.type="button";down.className="secondary";down.disabled=index===current.steps.length-1;
    const del=make("button","Remove");del.type="button";del.className="secondary";
    const hint=make("small","Arguments JSON. Use {{input.field}} or {{steps.step1.data.field}}.");
    args.oninput=()=>{try{step.arguments=JSON.parse(args.value);banner.textContent="";save()}catch{banner.textContent="Invalid arguments JSON — fix before saving."}};
    up.onclick=()=>{[current.steps[index-1],current.steps[index]]=[current.steps[index],current.steps[index-1]];save();draw()};
    down.onclick=()=>{[current.steps[index],current.steps[index+1]]=[current.steps[index+1],current.steps[index]];save();draw()};
    del.onclick=()=>{current.steps.splice(index,1);save();draw()};
    row.append(up,down,del);box.append(title,hint,args,row);rows.append(box);
   });
   output.value=current.output||"";
  }
  addButton.onclick=()=>{
   const chosen=catalog.find(x=>x.slug===add.value);if(!chosen||current.steps.length>=8)return;
   const id=slugId();const required=(chosen.input_schema?.required||[]);
   const properties=chosen.input_schema?.properties||{};
   const argumentsObject=Object.fromEntries(Object.keys(properties).map(k=>[k,required.includes(k)?"{{input."+k+"}}":null]).filter(([k,v])=>v!==null));
   current.steps.push({id,function:chosen.slug,arguments:argumentsObject,on_error:"stop"});
   if(!current.output)current.output="{{steps."+id+".data}}";
   save();draw();
  };
  output.oninput=save;
  function synchronize(){
   try{
    const parsed=JSON.parse(textarea().value);
    if(parsed?.type==="edge_pipeline" && Array.isArray(parsed.steps)){current=parsed;draw()}
   }catch{}
  }
  textarea().addEventListener("change",synchronize);
  try{catalog=await api("/edge-functions");banner.textContent=catalog.length?"":"No functions registered.";synchronize();draw()}
  catch(e){banner.textContent="Unable to load function catalog: "+e.message}
  window.anyapiPipelineRefresh=synchronize;
 }
 window.addEventListener("load",initialize);
})();