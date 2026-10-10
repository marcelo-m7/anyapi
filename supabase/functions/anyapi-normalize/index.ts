import "jsr:@supabase/functions-js/edge-runtime.d.ts";
const headers={"content-type":"application/json"};
Deno.serve(async (req: Request) => {
  if(req.method!=="POST") return new Response(JSON.stringify({success:false,data:null,error:{code:"METHOD_NOT_ALLOWED",message:"POST required"},meta:{}}),{status:405,headers});
  try {
    const input=await req.json();
    if(!input || typeof input!=="object" || Array.isArray(input)) throw new Error("Expected an object");
    const started=performance.now();
    const data={...input,processed:true};
    return new Response(JSON.stringify({success:true,data,error:null,meta:{duration_ms:Math.round(performance.now()-started)}}),{headers});
  } catch {
    return new Response(JSON.stringify({success:false,data:null,error:{code:"BAD_INPUT",message:"Invalid JSON object"},meta:{}}),{status:400,headers});
  }
});
