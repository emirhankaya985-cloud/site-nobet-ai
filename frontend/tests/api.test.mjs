import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
test('frontend contains required real API endpoints',()=>{
 const code=fs.readFileSync(new URL('../app/dashboard/page.tsx',import.meta.url),'utf8');
 assert.match(code, /\/organizations\/\$\{session\.organization_id\}/);
 assert.match(code, /\/monitors/);
 assert.match(code, /\/dashboard/);
});
test('monitor detail contains observed and unobserved availability',()=>{
 const code=fs.readFileSync(new URL('../app/monitors/[id]/page.tsx',import.meta.url),'utf8');
 assert.match(code, /unobserved_seconds/);
 assert.match(code,/\.checks/);
});
