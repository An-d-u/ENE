"""실제 모델/SDK 대신 가상 PIXI로 공유 캐릭터 코드의 수명과 호스트 경계를 검증한다."""

import json
from pathlib import Path
import subprocess

import pytest


WEB = Path(__file__).resolve().parents[1] / "assets/web"
SCRIPTS = [
    "runtime_character_state.js",
    "runtime_live2d_model.js",
    "runtime_motion_state.js",
    "runtime_gesture_engine.js",
    "runtime_head_pat.js",
    "runtime_auto_blink_tracking.js",
    "runtime_expression.js",
    "runtime_lipsync.js",
    "runtime_live2d_parameter_core.js",
    "runtime_character_host.js",
]


def run_character(case):
    source = "\n".join((WEB / name).read_text(encoding="utf-8") for name in SCRIPTS)
    harness = r"""
const vm = require('vm');
const assert = require('assert/strict');
const listeners = new Map(), timers = new Map(), frames = new Map();
const calls = [], inputs = [], values = new Map();
let now = 1000, id = 0, releaseModel;
function target(name) { return {
    style: {}, width: 400, height: 600,
    addEventListener(type, fn) { listeners.set(name + ':' + type, fn); },
    removeEventListener(type) { listeners.delete(name + ':' + type); },
    getBoundingClientRect() { return {x:0,y:0,width:400,height:600}; }
}; }
const canvas = target('canvas');
const model = () => ({
    width: 100, height: 200, anchor: {set() {}}, scale: {set() {}},
    internalModel: {
        coreModel: {setParameterValueById(k,v) { values.set(k,v); },
            getParameterValueById() {return 0;}, getParameterIndex() {return 0;},
            getParameterCount() {return 1;}, _parameterIds: ['ParamAccent'],
            _parameterValues: [0], _parameterMinimumValues: [-1], _parameterMaximumValues: [1], _parameterDefaultValues: [0]},
        on(type, fn) {listeners.set('model:'+type,fn);}, off(type) {listeners.delete('model:'+type);},
    },
    destroy() {calls.push('destroyModel');}, motion() {}, hitTest() {return ['Head'];}
});
const context = {
    crypto: {randomUUID:()=> '00000000-0000-4000-8000-'+String(++id).padStart(12,'0')},
    console: {log(){}, warn(){}, error(){}}, URL, AbortController,
    location: {href:'https://appassets.androidplatform.net/character/index.html'},
    innerWidth:400, innerHeight:600, performance:{now:()=>now},
    document:{getElementById:(key)=>key==='live2d-canvas'?canvas:null},
    setTimeout(fn) {const key=++id;timers.set(key,fn);return key;},
    clearTimeout(key) {timers.delete(key);},
    requestAnimationFrame(fn) {const key=++id;frames.set(key,fn);return key;},
    cancelAnimationFrame(key) {frames.delete(key);},
    fetch: async()=>({ok:true,json:async()=>({Parameters:[{Id:'ParamAccent',Value:0.4,Blend:'Overwrite'}]})}),
    PIXI:{Application:class {
        constructor(options) {this.view=options.view;this.stage={addChild(){},removeChild(){}};this.renderer={resize(){}};calls.push('createApp');}
        destroy() {calls.push('destroyApp');}
    }, live2d:{Live2DModel:{from:async(path)=>{calls.push(path);return model();}}}},
};
Object.assign(context,target('window'));
context.window=context;
const ctx=vm.createContext(context);
vm.runInContext(SOURCE,ctx);
async function tick() { now+=50;const work=[...frames.values()];frames.clear();work.forEach(fn=>fn(now));await Promise.resolve(); }
const snapshot={status:'ready',model_version:'a'.repeat(64),entry_asset_id:'b'.repeat(64),
    expression_ids:['normal','bright'],gesture_ids:['nod'],default_expression:'normal',
    settings:{enable_head_pat:true,enable_idle_synthetic_gestures:false},parameters:{ParamAccent:0.2}};
const host={emitInput:value=>inputs.push(value),assetUrl:(kind,id)=>'https://appassets.androidplatform.net/models/'+snapshot.model_version+'/assets/'+id};
async function main() {
CASE
}
main().then(()=>process.stdout.write(JSON.stringify({ok:true}))).catch(error=>{console.error(error);process.exitCode=1;});
"""
    pc_entry = (WEB / "script.js").read_text(encoding="utf-8")
    script = harness.replace("SOURCE", json.dumps(source)).replace(
        "CASE", case.replace("PC_ENTRY", json.dumps(pc_entry))
    )
    result = subprocess.run(
        ["node"],
        input=script,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"ok": True}


@pytest.mark.parametrize("kind", ["pc", "android"])
def test_shared_runtime_without_chat_and_dispose_clears_callbacks(kind):
    run_character(
        f"host.kind={json.dumps(kind)};"
        + r"""
const character=context.createCharacter(host,canvas);
assert.deepEqual(Object.keys(character).sort(),['applyAction','applyHeadPat','applyPlayback','applySnapshot','dispose']);
assert.equal(calls.filter(x=>x==='createApp').length,1);
await character.applySnapshot(snapshot);
assert.ok(calls.some(x=>x.endsWith(snapshot.entry_asset_id)));
await character.applyAction({model_version:snapshot.model_version,kind:'expression',action_id:'bright',duration_ms:0});
character.applyPlayback({active:true,mouth_open:0.6});
assert.equal(values.get('ParamMouthOpenY'),0.6);
await character.applyAction({model_version:snapshot.model_version,kind:'gesture',action_id:'nod',duration_ms:500});
await tick();
assert.ok(frames.size>0);
character.dispose();character.dispose();
assert.equal(frames.size,0);assert.equal(timers.size,0);assert.equal(listeners.size,0);
assert.equal(calls.filter(x=>x==='destroyModel').length,1);
assert.equal(calls.filter(x=>x==='destroyApp').length,1);
assert.equal(await character.applySnapshot(snapshot),false);
"""
    )


def test_dispose_and_model_reset_discard_late_load_and_expression():
    run_character(r"""
context.PIXI.live2d.Live2DModel.from=()=>new Promise(resolve=>{releaseModel=resolve;});
const character=context.createCharacter(host,canvas);
const pending=character.applySnapshot(snapshot);
character.dispose();releaseModel(model());await pending;
assert.equal(context.live2dModel,null);
assert.equal(calls.filter(x=>x==='destroyModel').length,1);
assert.equal(frames.size,0);assert.equal(listeners.size,0);
""")


def test_late_expression_cannot_apply_to_replaced_model_or_recreate_timers():
    run_character(r"""
const character=context.createCharacter(host,canvas);
await character.applySnapshot(snapshot);
let resolveExpression;
context.fetch=()=>new Promise(resolve=>{resolveExpression=resolve;});
const pending=character.applyAction({model_version:snapshot.model_version,kind:'expression',action_id:'bright'});
character.dispose();
resolveExpression({ok:true,json:async()=>({Parameters:[{Id:'ParamAccent',Value:1}]})});
await pending;
assert.equal(vm.runInContext('expressionRuntimeState.transition.to.emotion',ctx),'normal');
assert.equal(frames.size,0);assert.equal(timers.size,0);assert.equal(listeners.size,0);
""")


def test_same_model_snapshot_during_load_waits_and_applies_latest_state():
    run_character(r"""
context.PIXI.live2d.Live2DModel.from=()=>new Promise(resolve=>{releaseModel=resolve;});
const character=context.createCharacter(host,canvas);
const first=character.applySnapshot(snapshot);
const second=character.applySnapshot({...snapshot,parameters:{ParamAccent:0.7}});
releaseModel(model());
assert.equal(await first,false);
assert.equal(await second,true);
assert.equal(vm.runInContext('live2dParameterState.values.ParamAccent',ctx),0.7);
character.dispose();
""")


def test_invalid_action_and_missing_model_never_fall_back_to_local_path():
    run_character(r"""
const character=context.createCharacter(host,canvas);
assert.equal(calls.length,1);
await character.applySnapshot({...snapshot,status:'unavailable',model_version:null,entry_asset_id:null});
assert.equal(calls.length,1);
await character.applySnapshot(snapshot);
await character.applyAction({model_version:'c'.repeat(64),kind:'expression',action_id:'bright'});
await character.applyAction({model_version:snapshot.model_version,kind:'expression',action_id:'../../private'});
character.applyPlayback({active:true,mouth_open:NaN});
assert.ok(!calls.some(x=>x.includes('live2d_models')||x.includes('private')));
character.dispose();
""")


def test_actual_pc_adapter_retains_local_model_and_count_boundary():
    run_character(r"""
let count=0; const submitted=[];
context.pyBridge={increment_head_pat_count_from_js(){count++;}, submit_head_pat_input(raw, done){submitted.push(JSON.parse(raw));done(JSON.stringify({phase:'rejected'}));}};
vm.runInContext("const DEFAULT_MODEL_PATH='https://synthetic.invalid/model.model3.json'; let chatPanelHeightPx=null;",ctx);
vm.runInContext(PC_ENTRY,ctx);
await Promise.resolve(); await Promise.resolve();
assert.ok(calls.includes('https://synthetic.invalid/model.model3.json'));
vm.runInContext("characterHost.emitInput({type:'head_pat_input', model_generation:'synthetic',interaction_id:'synthetic',phase:'start',seq:0,intensity:.3})",ctx);
assert.equal(count,0);assert.equal(submitted.length,1);
context.eneCharacter.dispose();
assert.equal(frames.size,0);assert.equal(timers.size,0);assert.equal(listeners.size,0);
""")


def test_lost_render_context_still_releases_owned_callbacks():
    run_character(r"""
const character=context.createCharacter(host,canvas);
await character.applySnapshot(snapshot);
context.live2dModel.destroy=()=>{throw new Error('합성 렌더러 정리 실패');};
vm.runInContext("app.destroy=()=>{throw new Error('합성 컨텍스트 손실');};",ctx);
character.dispose();character.dispose();
assert.equal(context.live2dModel,null);
assert.equal(frames.size,0);assert.equal(timers.size,0);assert.equal(listeners.size,0);
assert.equal(vm.runInContext('app',ctx),null);
""")


def test_head_pat_stationary_heartbeat_and_end_are_inputs_not_direct_counts():
    run_character(r"""
const character=context.createCharacter(host,canvas);await character.applySnapshot(snapshot);
const event={pointerType:'touch',button:0,pointerId:1,clientX:50,clientY:50,target:canvas,preventDefault(){}};
listeners.get('canvas:pointerdown')(event);
assert.equal(inputs[0].type,'head_pat_input');assert.equal(inputs[0].phase,'start');
now+=500;const pending=[...timers.values()];timers.clear();pending.forEach(fn=>fn());
assert.equal(inputs[1].phase,'update');assert.equal(inputs[1].seq,1);
listeners.get('window:pointerup')(event);listeners.get('window:pointerup')(event);
assert.deepEqual(inputs.map(x=>x.phase),['start','update','end']);
assert.equal(inputs[2].seq,2);assert.ok(inputs.every(x=>x.model_generation===snapshot.model_version));
character.dispose();assert.equal(timers.size,0);
""")


@pytest.mark.parametrize("cause", ["pointercancel", "blur", "model", "dispose"])
def test_head_pat_interrupted_input_cancels_without_normal_end(cause):
    run_character(r"""
const character=context.createCharacter(host,canvas);await character.applySnapshot(snapshot);
const event={pointerType:'touch',button:0,pointerId:1,clientX:50,clientY:50,target:canvas,preventDefault(){}};
listeners.get('canvas:pointerdown')(event);
CAUSE
assert.deepEqual(inputs.map(x=>x.phase),['start','cancel']);
character.dispose();assert.equal(timers.size,0);assert.equal(listeners.size,0);
""".replace("CAUSE", {
        "pointercancel": "listeners.get('window:pointercancel')(event);",
        "blur": "listeners.get('window:blur')();",
        "model": "await character.applySnapshot({...snapshot,model_version:'c'.repeat(64)});",
        "dispose": "character.dispose();",
    }[cause]))


def test_remote_pat_echo_never_emits_input_or_revives_old_session():
    run_character(r"""
const character=context.createCharacter(host,canvas);await character.applySnapshot(snapshot);
const state={model_version:snapshot.model_version,source:'pc',connection_generation:'synthetic',
    interaction_id:'00000000-0000-4000-8000-000000000001',interaction_no:1,seq:0,phase:'accepted',intensity:.5};
character.applyHeadPat(state);assert.equal(vm.runInContext('isHeadPatting',ctx),true);
character.applyHeadPat({...state,phase:'ended',seq:1});assert.equal(vm.runInContext('isHeadPatting',ctx),false);
character.applyHeadPat(state);assert.equal(vm.runInContext('isHeadPatting',ctx),false);
character.applyHeadPat({...state,interaction_no:2});
character.applyHeadPat({...state,phase:'ended',seq:2});assert.equal(vm.runInContext('isHeadPatting',ctx),true);
assert.equal(inputs.length,0);character.dispose();assert.equal(inputs.length,0);
""")


def test_own_rejected_prediction_stops_without_sending_an_echo_input():
    run_character(r"""
const character=context.createCharacter(host,canvas);await character.applySnapshot(snapshot);
const event={pointerType:'touch',button:0,pointerId:1,clientX:50,clientY:50,target:canvas,preventDefault(){}};
listeners.get('canvas:pointerdown')(event);
character.applyHeadPat({...inputs[0],source:'phone',phase:'rejected',model_version:snapshot.model_version,interaction_no:1});
assert.equal(vm.runInContext('isHeadPatting',ctx),false);
listeners.get('window:pointerup')(event);assert.equal(inputs.length,1);
character.dispose();assert.equal(timers.size,0);
""")
