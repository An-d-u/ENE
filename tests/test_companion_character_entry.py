"""실제 모델 없이 내부 문서의 세대 교환과 취소 경계만 검사한다."""

from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("phase", ["initialize", "resize", "resume"])
def test_real_host_render_failure_uses_existing_safe_generation_error(phase):
    from tests.test_companion_character_runtime import run_character
    import json

    run_character("const phase=" + json.dumps(phase) + ";" + r"""
context.location.origin='https://appassets.androidplatform.net';
const replies=[];context.eneCharacterNative={postMessage:x=>replies.push(JSON.parse(x))};
const generation='00000000-0000-4000-8000-000000000001';
vm.runInContext(PHONE_ENTRY,ctx);
const send=(type,value)=>context.eneCharacterNative.onmessage({data:JSON.stringify({type,value,generation})});
resizeFailure=phase==='initialize';await send('initialize');
if(phase!=='initialize') {
    const placement={scale:1,xPercent:50,yPercent:50};
    if(phase==='resume')await send('presentation',{placement,visible:false});
    context.innerWidth=600;resizeFailure=true;
    if(phase==='resume')await send('presentation',{placement,visible:true});
    else listeners.get('window:resize')();
}
const code=phase==='initialize'?'character_initialization_failed':'character_render_failed';
assert.deepEqual(replies.filter(x=>x.type==='error'),[{type:'error',code,generation}]);
assert.equal(vm.runInContext('app',ctx),null);assert.equal(frames.size,0);
""")


def test_entry_requires_native_generation_before_accepting_commands():
    script = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const origin = 'https://appassets.androidplatform.net';
const generation = '00000000-0000-4000-8000-000000000001';
const listeners = {}, calls = [], replies = [];
let host;
const character = {applySnapshot:async x=>{calls.push(x);return false;},
    applyAction:async x=>calls.push(x),applyPlayback:x=>calls.push(x),applyHeadPat:x=>calls.push(x),applyPreview:x=>calls.push(x),applyPresentation:x=>calls.push(x),
    dispose:()=>{calls.push('disposed');host.emitInput({type:'head_pat_input',phase:'cancel'});}};
const context = {AbortController, document:{getElementById:()=>({})},window:{
    location:{origin},createCharacter:value=>{host=value;return character;},
    eneCharacterNative:{postMessage:x=>replies.push(JSON.parse(x))},
    addEventListener:(name,fn)=>listeners[name]=fn, removeEventListener:()=>{}}};
vm.runInNewContext(fs.readFileSync('assets/web/character/entry.js','utf8'),context);
async function send(data) { await context.window.eneCharacterNative.onmessage({data:JSON.stringify(data)}); }
(async()=>{
    assert.deepEqual(replies,[{type:'bridge_ready'}]);
    assert.equal(listeners.message,undefined);
    assert.equal(host,undefined);
    replies.length=0;
    await send({type:'snapshot',value:{status:'unavailable'}});
    assert.equal(calls.length,0);
    await send({type:'initialize',generation:'invalid'});
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
    const presentation={placement:{scale:1.5,xPercent:25,yPercent:75},visible:false};
    await send({type:'presentation',generation:'00000000-0000-4000-8000-000000000002',value:presentation});
    assert.equal(calls.length,3);
    await send({type:'presentation',generation,value:presentation});
    assert.deepEqual(calls[3],presentation);
    const lateReceive = context.window.eneCharacterNative.onmessage;
    listeners.pagehide();
    assert.equal(replies[2].phase,'cancel');assert.equal(replies[2].generation,generation);
    assert.equal(context.window.eneCharacterNative.onmessage,null);
    await lateReceive({data:JSON.stringify({type:'action',generation,value:{kind:'gesture'}})});
    assert.equal(calls.length,5);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr


def test_character_initialization_failure_is_reported_without_raw_error():
    script = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const replies = [], listeners = {};
const generation = '00000000-0000-4000-8000-000000000001';
const native = {postMessage:raw=>replies.push(JSON.parse(raw))};
const context = {AbortController,document:{getElementById:()=>({})},window:{
    location:{origin:'https://appassets.androidplatform.net'},eneCharacterNative:native,
    createCharacter:()=>{throw new Error('synthetic private renderer detail');},
    addEventListener:(name,fn)=>listeners[name]=fn,removeEventListener:()=>{}}};
vm.runInNewContext(fs.readFileSync('assets/web/character/entry.js','utf8'),context);
(async()=>{
    await native.onmessage({data:JSON.stringify({type:'initialize',generation})});
    assert.deepEqual(replies,[{type:'bridge_ready'},
        {type:'error',code:'character_initialization_failed',generation}]);
    listeners.pagehide();
    assert.equal(native.onmessage,null);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr


def test_pending_expression_respects_snapshot_sequence_and_new_snapshot_ownership():
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const generation='00000000-0000-4000-8000-000000000001';
const native={postMessage(){}},waits=[],actions=[];
let releaseAction;
const character={applySnapshot:()=>new Promise(resolve=>waits.push(resolve)),
    applyAction:async value=>{actions.push(value.action_seq);if(value.action_seq===11)await new Promise(resolve=>{releaseAction=resolve;});}};
const context={AbortController,document:{getElementById:()=>({})},
    fetch:async()=>({ok:true,json:async()=>({})}),window:{
        location:{origin:'https://appassets.androidplatform.net'},eneCharacterNative:native,
        createCharacter:()=>character,addEventListener(){},removeEventListener(){}}};
vm.runInNewContext(fs.readFileSync('assets/web/character/entry.js','utf8'),context);
const model='a'.repeat(64);
const snapshot=seq=>({status:'ready',model_version:model,entry_asset_id:'b'.repeat(64),expression_ids:['normal','bright'],action_seq:seq});
const action=seq=>({model_version:model,kind:'expression',action_id:'bright',action_seq:seq});
const send=(type,value)=>native.onmessage({data:JSON.stringify({type,value,generation})});
async function settle(){for(let i=0;i<8;i++)await Promise.resolve();}
(async()=>{
    await send('initialize');
    const first=send('snapshot',snapshot(3));await settle();
    await send('action',action(4));
    const second=send('snapshot',snapshot(10));await settle();
    waits[0](true);await first;
    await send('action',action(9));await send('action',action(11));
    waits[1](true);await settle();
    assert.deepEqual(actions,[11]);
    await send('action',action(12));releaseAction();await second;
    assert.deepEqual(actions,[11,12]);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("failure", ["asset", "render"])
def test_character_snapshot_failure_reports_only_its_safe_stage(failure):
    script = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const failure = process.argv[1], replies = [];
const generation = '00000000-0000-4000-8000-000000000001';
const native = {postMessage:raw=>replies.push(JSON.parse(raw))};
const context = {AbortController,document:{getElementById:()=>({})},
    fetch:async()=>({ok:failure !== 'asset',json:async()=>({})}),window:{
    location:{origin:'https://appassets.androidplatform.net'},eneCharacterNative:native,
    createCharacter:()=>({applySnapshot:async()=>{throw new Error('synthetic renderer detail');}}),
    addEventListener:()=>{},removeEventListener:()=>{}}};
vm.runInNewContext(fs.readFileSync('assets/web/character/entry.js','utf8'),context);
(async()=>{
    await native.onmessage({data:JSON.stringify({type:'initialize',generation})});
    await native.onmessage({data:JSON.stringify({type:'snapshot',generation,value:{
        status:'ready',model_version:'a'.repeat(64),entry_asset_id:'b'.repeat(64)}})});
    assert.deepEqual(replies.at(-1),{type:'error',code:`character_${failure}_failed`,generation});
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", script, failure], cwd=ROOT, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
