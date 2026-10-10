/* AnyAPI lightweight visual JSON Schema editor. Existing schema textareas remain canonical. */
(()=> {
const TYPES=['string','integer','number','boolean','object','array'];
function setup(key) {
 const area=document.getElementById(key);
 if(!area)return;
 const block=area.parentElement;
 const controls=document.createElement('div');
 controls.className='row';
 const visual=document.createElement('button');visual.type='button';visual.textContent='Visual fields';visual.className='secondary';
 const add=document.createElement('button');add.type='button';add.textContent='+ Field';add.className='secondary';
 const yamlBtn=document.createElement('button');yamlBtn.type='button';yamlBtn.textContent='YAML';yamlBtn.className='secondary';
 const jsonBtn=document.createElement('button');jsonBtn.type='button';jsonBtn.textContent='JSON';jsonBtn.className='secondary';
 const fields=document.createElement('div');fields.style.margin='16px 0';
 controls.append(visual,add,yamlBtn,jsonBtn);
 area.before(controls,fields);
 let format='json';
 async function parse(){const response=await api('/schema/convert','POST',{format,text:area.value});return response}
 async function render() {
  if(format!=='json')return;
  let schema;
  try{schema=JSON.parse(area.value)}catch(e){fields.textContent='Invalid JSON: '+e.message;return}
  if(!schema || schema.type!=='object'||typeof schema.properties!=='object'){fields.textContent='Visual editor supports object properties. Advanced JSON editing remains available.';return}
  fields.replaceChildren();
  Object.entries(schema.properties).forEach(([name,definition])=>{
    const row=document.createElement('div');row.className='row';row.draggable=true;row.style.marginBottom='8px';
    let drag=document.createElement('span');drag.textContent='⋮⋮';drag.title='Drag to reorder';drag.style.cursor='grab';
    const input=document.createElement('input');input.value=name;input.title='Field name';
    const type=document.createElement('select');
    TYPES.forEach(t=>{let option=document.createElement('option');option.value=t;option.textContent=t;type.append(option)});
    type.value=definition.type||'string';
    const required=document.createElement('label');required.textContent='Required ';
    const check=document.createElement('input');check.type='checkbox';check.checked=(schema.required||[]).includes(name);
    required.append(check);
    const del=document.createElement('button');del.textContent='×';del.type='button';del.className='secondary';
    const commit=()=>{
      let fresh=JSON.parse(area.value);let entries=Object.entries(fresh.properties);
      let old=entries.find(([k])=>k===name)?.[1]||{};
      delete fresh.properties[name];
      const newName=input.value.trim()||name;
      fresh.properties[newName]={...old,type:type.value};
      fresh.required=(fresh.required||[]).filter(v=>v!==name && v!==newName);
      if(check.checked)fresh.required.push(newName);
      area.value=JSON.stringify(fresh,null,2);render();
    };
    input.addEventListener('change',commit);type.addEventListener('change',commit);check.addEventListener('change',commit);
    del.onclick=()=>{delete schema.properties[name];schema.required=(schema.required||[]).filter(x=>x!==name);area.value=JSON.stringify(schema,null,2);render()};
    row.ondragstart=e=>{e.dataTransfer.setData('text/plain',name)};
    row.ondragover=e=>e.preventDefault();
    row.ondrop=e=>{e.preventDefault();let moving=e.dataTransfer.getData('text/plain');if(!schema.properties[moving]||moving===name)return;let entries=Object.entries(schema.properties);let item=entries.find(x=>x[0]===moving);entries=entries.filter(x=>x[0]!==moving);entries.splice(entries.findIndex(x=>x[0]===name),0,item);schema.properties=Object.fromEntries(entries);area.value=JSON.stringify(schema,null,2);render()};
    row.append(drag,input,type,required,del);fields.append(row);
  });
 }
 visual.onclick=()=>{if(format==='yaml'){jsonBtn.click();return}render()};
 add.onclick=async()=>{
  try{
   if(format==='yaml')await jsonBtn.onclick();
   const schema=JSON.parse(area.value);
   if(schema.type!=='object')return alert('Visual fields require an object schema');
   schema.properties||={};let i=1;while(schema.properties['field_'+i])i++;
   schema.properties['field_'+i]={type:'string'};area.value=JSON.stringify(schema,null,2);render();
  }catch(e){alert(e.message)}
 };
 yamlBtn.onclick=async()=>{try{const data=await parse();area.value=data.yaml;format='yaml';fields.replaceChildren();yamlBtn.disabled=true;jsonBtn.disabled=false}catch(e){alert(e.message)}};
 jsonBtn.onclick=async()=>{try{const data=await parse();area.value=data.json;format='json';fields.replaceChildren();yamlBtn.disabled=false;jsonBtn.disabled=true;render()}catch(e){alert(e.message)}};
 area.addEventListener('change',()=>{if(format==='json')render()});
 jsonBtn.disabled=true;render();
}
window.addEventListener('load',()=>{setup('input_schema');setup('output_schema')});
})();
