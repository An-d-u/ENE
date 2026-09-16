"""실제 모델 없이 내부 문서의 세대 교환과 취소 경계만 검사한다."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_entry_requires_native_generation_before_accepting_commands():
    script = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const origin = 'https://appassets.androidplatform.net';
const generation = '00000000-0000-4000-8000-000000000001';
const listeners = {}, calls = [], replies = [];
let host;
const character = {applySnapshot:async x=>{calls.push(x);return false;},
    applyAction:async x=>calls.push(x),applyPlayback:x=>calls.push(x),applyHeadPat:x=>calls.push(x),applyPreview:x=>calls.push(x),
    dispose:()=>{calls.push('disposed');host.emitInput({type:'head_pat_input',phase:'cancel'});}};
const context = {AbortController, document:{getElementById:()=>({})},window:{
    location:{origin},createCharacter:value=>{host=value;return character;},
    eneCharacterNative:{postMessage:x=>replies.push(JSON.parse(x))},
    addEventListener:(name,fn)=>listeners[name]=fn, removeEventListener:()=>{}}};
vm.runInNewContext(fs.readFileSync('assets/web/character/entry.js','utf8'),context);
async function send(data, from=origin) { await listeners.message({origin:from,data:JSON.stringify(data)}); }
(async()=>{
    assert.equal(replies.length,0);
    await send({type:'snapshot',value:{status:'unavailable'}});
    assert.equal(calls.length,0);
    await send({type:'initialize',generation},'https://example.invalid');
    assert.equal(replies.length,0);
    await send({type:'initialize',generation});
    assert.equal(replies[0].type,'document_ready');
    assert.equal(replies[0].generation,generation);
    await send({type:'snapshot',generation:'00000000-0000-4000-8000-000000000002',value:{status:'unavailable'}});
    assert.equal(calls.length,0);
    await send({type:'initialize',generation:'00000000-0000-4000-8000-000000000002'});
    await send({type:'snapshot',generation,value:{status:'unavailable'}});
    assert.equal(calls.length,1);
    assert.equal(replies[1].type,'unavailable');
    assert.equal(replies[1].generation,generation);
    await send({type:'head_pat',generation,value:{phase:'accepted'}});
    assert.equal(calls[1].phase,'accepted');
    await send({type:'preview',generation,value:{settings:{enable_head_pat:false}}});
    assert.equal(calls[2].settings.enable_head_pat,false);
    listeners.pagehide();
    assert.equal(replies[2].phase,'cancel');assert.equal(replies[2].generation,generation);
    await send({type:'action',generation,value:{kind:'gesture'}});
    assert.equal(calls.length,4);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
