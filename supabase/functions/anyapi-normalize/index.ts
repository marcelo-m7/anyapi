import "jsr:@supabase/functions-js/edge-runtime.d.ts";
const headers = { "content-type": "application/json", "cache-control": "no-store" };
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers });
Deno.serve(async (request: Request) => {
  if (request.method !== "POST")
    return reply({success:false,data:null,error:{code:"METHOD_NOT_ALLOWED",message:"POST required"},meta:{}},405);
  const started = performance.now();
  try {
    const input = await request.json();
    if (!input || typeof input !== "object" || Array.isArray(input)
        || typeof input.value !== "string" || input.value.length > 10000)
      return reply({success:false,data:null,error:{code:"INVALID_INPUT",message:"value must be a string (max 10000 characters)"},meta:{}},400);
    if (input.label != null && (typeof input.label !== "string" || input.label.length > 120))
      return reply({success:false,data:null,error:{code:"INVALID_INPUT",message:"label must be a string (max 120 characters)"},meta:{}},400);
    const data = { value: input.value.trim(), label: input.label?.trim() ?? null, processed: true };
    return reply({success:true,data,error:null,meta:{duration_ms:Math.round(performance.now()-started)}});
  } catch {
    return reply({success:false,data:null,error:{code:"INVALID_JSON",message:"JSON object expected"},meta:{}},400);
  }
});
