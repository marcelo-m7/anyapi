-- V1 typed argument and return schema for the reference Edge Function
update public.edge_function_catalog
set title = 'Normalize text',
    description = 'Trim a required text value and return a normalized string, an optional label and a processed flag.',
    input_schema = '{"type":"object","required":["value"],"properties":{"value":{"type":"string","maxLength":10000,"description":"Text to normalize"},"label":{"type":"string","maxLength":120,"description":"Optional label"}},"additionalProperties":false}'::jsonb,
    output_schema = '{"type":"object","required":["value","label","processed"],"properties":{"value":{"type":"string"},"label":{"type":["string","null"]},"processed":{"type":"boolean"}}}'::jsonb,
    updated_at = now()
where slug = 'anyapi-normalize';
