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
const applications = [], resizes = [], hitPoints = [], mediaQueries = [];
const bufferStates = [];
let gpuValues = [8192, 8192, new Int32Array([8192,8192])], gpuReadError = false, resizeFailure = false;
const gl = {MAX_TEXTURE_SIZE:0,MAX_RENDERBUFFER_SIZE:1,MAX_VIEWPORT_DIMS:2,
    getParameter(key) {if(gpuReadError)throw new Error('합성 GPU 조회 실패');return gpuValues[key];}};
let now = 1000, id = 0, releaseModel;
function target(name) { return {
    style: {}, width: 400, height: 600,
    addEventListener(type, fn) { listeners.set(name + ':' + type, fn); },
    removeEventListener(type) { listeners.delete(name + ':' + type); },
    getBoundingClientRect() { return {x:0,y:0,width:400,height:600}; }
}; }
const canvas = target('canvas');
const model = () => ({
    width: 100, height: 200, autoUpdate: true, anchor: {set() {}}, scale: {value: 1, set(value) {this.value=value;}},
    internalModel: {
        width: 100, height: 200,
        coreModel: {setParameterValueById(k,v) { values.set(k,v); },
            getParameterValueById() {return 0;}, getParameterIndex() {return 0;},
            getParameterCount() {return 1;}, _parameterIds: ['ParamAccent'],
            _parameterValues: [0], _parameterMinimumValues: [-1], _parameterMaximumValues: [1], _parameterDefaultValues: [0]},
        on(type, fn) {listeners.set('model:'+type,fn);}, off(type) {listeners.delete('model:'+type);},
    },
    destroy() {calls.push('destroyModel');}, motion() {}, hitTest(...args) {hitPoints.push(args);return ['Head'];}
});
const context = {
    crypto: {randomUUID:()=> '00000000-0000-4000-8000-'+String(++id).padStart(12,'0')},
    console: {log(){}, warn(){}, error(){}}, URL, AbortController,
    location: {href:'https://appassets.androidplatform.net/character/index.html'},
    innerWidth:400, innerHeight:600, performance:{now:()=>now},
    devicePixelRatio:1,
    matchMedia(query) {
        const item={query,callbacks:new Set(),addEventListener(type,fn){this.callbacks.add(fn);},
            removeEventListener(type,fn){this.callbacks.delete(fn);}};
        mediaQueries.push(item);return item;
    },
    document:{getElementById:(key)=>key==='live2d-canvas'?canvas:null},
    setTimeout(fn) {const key=++id;timers.set(key,fn);return key;},
    clearTimeout(key) {timers.delete(key);},
    requestAnimationFrame(fn) {const key=++id;frames.set(key,fn);return key;},
    cancelAnimationFrame(key) {frames.delete(key);},
    fetch: async()=>({ok:true,json:async()=>({Parameters:[{Id:'ParamAccent',Value:0.4,Blend:'Overwrite'}]})}),
    PIXI:{Application:class {
        constructor(options) {
            this.view=options.view;this.stage={addChild(){},removeChild(){}};
            this.view.width=Math.round((options.width??400)*(options.resolution??1));
            this.view.height=Math.round((options.height??600)*(options.resolution??1));
            this.renderer={gl,resolution:options.resolution??1,resize(width,height){
                if(resizeFailure)throw new Error('합성 크기 적용 실패');
                resizes.push({width,height,resolution:this.resolution});
                options.view.width=Math.round(width*this.resolution);
                bufferStates.push([options.view.width,options.view.height]);
                options.view.height=Math.round(height*this.resolution);
                bufferStates.push([options.view.width,options.view.height]);
            }};
            applications.push({options,instance:this});calls.push('createApp');
        }
        destroy() {calls.push('destroyApp');}
        start() {calls.push('startApp');}
        stop() {calls.push('stopApp');}
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
        .replace("PHONE_ENTRY", json.dumps((WEB / "character/entry.js").read_text(encoding="utf-8")))
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


def test_phone_invalidation_preserves_prepared_model_and_cancels_late_expression():
    run_character(r"""
host.kind='phone';const character=context.createCharacter(host,canvas);
await character.applySnapshot(snapshot);const original=context.live2dModel;
let release;
context.fetch=()=>new Promise(resolve=>{release=()=>resolve({ok:true,json:async()=>({Parameters:[{Id:'ParamAccent',Value:0.9,Blend:'Overwrite'}]})});});
const action=character.applyAction({model_version:snapshot.model_version,kind:'expression',action_id:'bright',duration_ms:0});
character.invalidatePending();release();await action;
assert.notEqual(values.get('ParamAccent'),0.9);
context.fetch=async()=>({ok:true,json:async()=>({Parameters:[]})});
const placement={scale:1,xPercent:50,yPercent:50};
for(let i=0;i<3;i++) {
    character.applyPresentation({placement,visible:false});character.invalidatePending();
    assert.equal(frames.size,0);assert.equal(original.autoUpdate,false);
    assert.equal(await character.applySnapshot(snapshot),true);
    character.applyPresentation({placement,visible:true});
    assert.equal(context.live2dModel,original);
}
assert.equal(calls.filter(x=>x.endsWith(snapshot.entry_asset_id)).length,1);
assert.equal(calls.filter(x=>x==='destroyModel').length,0);
assert.equal(calls.filter(x=>x==='createApp').length,1);character.dispose();
""")


def test_cancelled_initial_model_cannot_replace_new_binding_model():
    run_character(r"""
host.kind='phone';const waits=[];
context.PIXI.live2d.Live2DModel.from=()=>new Promise(resolve=>waits.push(resolve));
const character=context.createCharacter(host,canvas);
const previous=character.applySnapshot(snapshot);
character.invalidatePending();
const current=character.applySnapshot(snapshot);
const latest=model();waits[1](latest);assert.equal(await current,true);
waits[0](model());assert.equal(await previous,false);
assert.equal(context.live2dModel,latest);
assert.equal(calls.filter(x=>x==='destroyModel').length,1);
character.dispose();
""")


@pytest.mark.parametrize("kind", ["pc", "phone"])
def test_shared_runtime_without_chat_and_dispose_clears_callbacks(kind):
    run_character(
        f"host.kind={json.dumps(kind)};"
        + r"""
const character=context.createCharacter(host,canvas);
assert.deepEqual(Object.keys(character).sort(),['applyAction','applyHeadPat','applyPlayback','applyPresentation','applyPreview','applySnapshot','dispose','invalidatePending']);
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


def test_preview_does_not_reload_assets_or_reset_expression_and_uses_pc_pat_defaults():
    run_character(r"""
const character=context.createCharacter(host,canvas);
snapshot.head_pat_defaults={active:'bright',end:'normal'};
snapshot.parameter_catalog=[{id:'ParamAccent',min:-1,max:1,default:0}];
await character.applySnapshot(snapshot);
const before=calls.length;
const states=[];context.setHeadPatConfig=(...args)=>states.push(args);
assert.equal(character.applyPreview({...snapshot,settings:{...snapshot.settings,head_pat_strength:2},parameters:{ParamAccent:0.8}}),true);
assert.equal(calls.length,before);assert.equal(states[0][4],'bright');
listeners.get('model:beforeModelUpdate')();assert.equal(values.get('ParamAccent'),0.8);
assert.equal(character.applyPreview({...snapshot,model_version:'c'.repeat(64)}),false);
character.applyPreview(snapshot);listeners.get('model:beforeModelUpdate')();assert.equal(values.get('ParamAccent'),0.2);
character.applyPreview({...snapshot,parameters:{}});assert.equal(values.get('ParamAccent'),0);
character.dispose();assert.equal(character.applyPreview(snapshot),false);
""")


def test_phone_placement_fits_once_per_model_and_survives_snapshots_and_resize():
    run_character(r"""
host.kind='phone'; context.innerHeight=200;
const character=context.createCharacter(host,canvas);
const placement={scale:1.5,xPercent:25,yPercent:75};
assert.equal(character.applyPresentation({placement,visible:true}),true);
await character.applySnapshot(snapshot);
const original=context.live2dModel;
assert.equal(original.scale.value,1.35); assert.equal(original.x,100); assert.equal(original.y,150);
original.width=5000; original.internalModel.width=5000;
await character.applySnapshot({...snapshot,settings:{...snapshot.settings,enable_idle_motion:false}});
character.applyPreview(snapshot);
assert.equal(original.scale.value,1.35);
context.innerWidth=200;context.innerHeight=400; listeners.get('window:resize')();
assert.equal(original.scale.value,2.7);assert.equal(original.x,50);assert.equal(original.y,300);
context.innerHeight=0; listeners.get('window:resize')();assert.equal(original.scale.value,2.7);
for (const bad of [{placement:{...placement,scale:NaN},visible:true},{placement,visible:'true'},
    {placement:{...placement,extra:1},visible:true},{placement,visible:true,extra:1}]) {
    assert.equal(character.applyPresentation(bad),false);
}
assert.equal(context.live2dModel,original);
assert.equal(calls.filter(x=>x.endsWith(snapshot.entry_asset_id)).length,1);
character.dispose();
""")


def test_phone_expanded_placement_keeps_css_coordinates_and_rejects_invalid_values():
    run_character(r"""
host.kind='phone';context.innerHeight=200;
const character=context.createCharacter(host,canvas);
await character.applySnapshot(snapshot);const original=context.live2dModel;
const placement={scale:6,xPercent:-300,yPercent:400};
assert.equal(character.applyPresentation({placement,visible:true}),true);
assert.equal(original.scale.value,5.4);assert.equal(original.x,-1200);assert.equal(original.y,800);
await character.applySnapshot(snapshot);character.applyPreview(snapshot);
character.applyPlayback({active:true,mouth_open:.4});
assert.equal(original.scale.value,5.4);assert.equal(original.x,-1200);assert.equal(original.y,800);
for(const valid of [{scale:.5,xPercent:0,yPercent:100},{scale:2,xPercent:100,yPercent:0},
    {scale:2.01,xPercent:-1,yPercent:101},{scale:6,xPercent:400,yPercent:-300}]) {
    assert.equal(character.applyPresentation({placement:valid,visible:true}),true);
}
for(const [key,invalid] of [['scale',.49],['scale',6.01],['xPercent',-300.01],['xPercent',400.01],
    ['yPercent',-300.01],['yPercent',400.01],['scale','6'],['scale',null],['scale',NaN],['xPercent',Infinity]]) {
    const bad={...placement,[key]:invalid};
    assert.equal(character.applyPresentation({placement:bad,visible:true}),false);
    assert.equal(context.calculatePhonePlacement(400,200,100,200,bad,{}),null);
}
assert.equal(character.applyPresentation({placement:{...placement,extra:1},visible:true}),false);
assert.equal(character.applyPresentation({placement:{scale:1,xPercent:50},visible:true}),false);
assert.equal(context.live2dModel,original);
assert.equal(calls.filter(x=>x.endsWith(snapshot.entry_asset_id)).length,1);
character.dispose();
""")


def test_phone_render_size_clamps_density_and_rounds_within_gpu_and_pixel_limits():
    run_character(r"""
const calc=context.calculatePhoneRenderSize;
assert.equal(typeof calc,'function');
const limits={valid:true,width:4096,height:4096};
for(const [dpr,expected] of [[1,1],[2,2],[3,3],[10,3],[.5,1],[NaN,1],[Infinity,1],[0,1],[-1,1],[undefined,1],['3',1]]) {
    const size=calc(400,600,dpr,limits);
    assert.equal(size.resolution,expected);
    assert.equal(size.bufferWidth,400*expected);assert.equal(size.bufferHeight,600*expected);
    assert.equal(size.logicalWidth,400);assert.equal(size.logicalHeight,600);
}
for(const width of [1,333,500.5,1025,1921,4097,16000]) {
    for(const height of [17,337.25,1441,3000,8000]) {
        for(const dpr of [1.25,2.625,3]) {
            const size=calc(width,height,dpr,limits);
            assert.ok(size.bufferWidth>0&&size.bufferWidth<=4096);
            assert.ok(size.bufferHeight>0&&size.bufferHeight<=4096);
            assert.ok(size.bufferWidth*size.bufferHeight<=4194304);
            assert.equal(size.bufferWidth,Math.round(width*size.resolution));
            assert.equal(size.bufferHeight,Math.round(height*size.resolution));
        }
    }
}
const limited=calc(400,600,3,{valid:true,width:800,height:600});
assert.equal(limited.resolution,1);assert.equal(limited.bufferHeight,600);
assert.ok(calc(8000,8000,3,limits).resolution<1);
assert.equal(calc(400,600,3,{valid:false,width:4096,height:4096}).resolution,1);
for(const size of [[0,600],[400,0],[-1,600],[400,NaN],[Infinity,600]]) assert.equal(calc(...size,3,limits),null);
""")


@pytest.mark.parametrize("dpr", [1, 3])
def test_phone_renderer_uses_tiny_initial_buffer_and_css_pat_coordinates(dpr):
    run_character(f"context.devicePixelRatio={dpr};" + r"""
host.kind='phone';const character=context.createCharacter(host,canvas);
const options=applications[0].options;
assert.equal(options.width,1);assert.equal(options.height,1);assert.equal(options.resolution,1);
assert.equal(options.autoDensity,true);assert.equal(options.resizeTo,undefined);
assert.deepEqual(resizes,[{width:400,height:600,resolution:context.devicePixelRatio}]);
await character.applySnapshot(snapshot);const original=context.live2dModel;
character.applyPresentation({placement:{scale:6,xPercent:-300,yPercent:400},visible:true});
await character.applySnapshot(snapshot);character.applyPreview(snapshot);character.applyPlayback({active:true,mouth_open:.4});
listeners.get('window:resize')();
assert.equal(resizes.length,1);assert.equal(context.live2dModel,original);
assert.equal(calls.filter(x=>x.endsWith(snapshot.entry_asset_id)).length,1);
listeners.get('canvas:pointerdown')({pointerType:'touch',button:0,pointerId:1,clientX:42,clientY:73,target:canvas,preventDefault(){}});
assert.ok(hitPoints.length>0);assert.deepEqual(hitPoints[0].slice(-2),[42,73]);
character.dispose();assert.equal(mediaQueries.flatMap(x=>[...x.callbacks]).length,0);
""")


def test_phone_rotation_keeps_intermediate_pixi_width_first_buffers_within_budget():
    run_character(r"""
host.kind='phone';context.devicePixelRatio=3;context.innerWidth=1000;context.innerHeight=2000;
const character=context.createCharacter(host,canvas);
await character.applySnapshot(snapshot);const original=context.live2dModel;
context.innerWidth=2000;context.innerHeight=1000;listeners.get('window:resize')();
for(const [width,height] of bufferStates) {
    assert.ok(width*height<=4194304,`중간 버퍼 초과: ${width}x${height}`);
    assert.ok(width<=4096&&height<=4096);
}
assert.equal(canvas.width,2896);assert.equal(canvas.height,1448);
assert.equal(context.live2dModel,original);assert.equal(calls.filter(x=>x.endsWith(snapshot.entry_asset_id)).length,1);
const before=resizes.length;listeners.get('window:resize')();assert.equal(resizes.length,before);
character.dispose();
""")


def test_phone_gpu_queries_limit_each_axis_and_fall_back_without_upscaling():
    run_character(r"""
host.kind='phone';context.devicePixelRatio=3;
gpuValues=[1024,2048,new Int32Array([800,600])];
context.createCharacter(host,canvas).dispose();assert.equal(resizes.at(-1).resolution,1);
for(const invalid of [[0,8192,[8192,8192]],[8192,NaN,[8192,8192]],
    [8192,8192,[8192]],[8192,8192,[8192,0]],[undefined,8192,[8192,8192]],
    [8192,8192,['8192',8192]]]) {
    gpuValues=invalid;
    context.createCharacter(host,canvas).dispose();assert.equal(resizes.at(-1).resolution,1);
}
gpuReadError=true;context.createCharacter(host,canvas).dispose();assert.equal(resizes.at(-1).resolution,1);
""")


def test_phone_density_resize_defers_hidden_and_detaches_stale_callbacks():
    run_character(r"""
host.kind='phone';const character=context.createCharacter(host,canvas);
await character.applySnapshot(snapshot);
const oldResize=listeners.get('window:resize');
const oldChange=[...mediaQueries.at(-1).callbacks][0];assert.equal(typeof oldChange,'function');
context.devicePixelRatio=3;oldChange();
assert.equal(resizes.at(-1).resolution,3);assert.equal(mediaQueries[0].callbacks.size,0);
assert.equal(mediaQueries.flatMap(x=>[...x.callbacks]).length,1);
const placement={scale:6,xPercent:400,yPercent:-300};
character.applyPresentation({placement,visible:false});const before=resizes.length;
context.innerWidth=600;context.innerHeight=400;context.devicePixelRatio=2;
oldResize();[...mediaQueries.at(-1).callbacks][0]();
assert.equal(resizes.length,before);assert.equal(frames.size,0);assert.equal(timers.size,0);
character.applyPresentation({placement,visible:true});
assert.deepEqual(resizes.at(-1),{width:600,height:400,resolution:2});
assert.equal(calls.filter(x=>x==='startApp').length,1);
const afterResume=resizes.length;
character.applyPresentation({placement,visible:true});oldResize();assert.equal(resizes.length,afterResume);
context.innerHeight=0;oldResize();assert.equal(resizes.length,afterResume);
context.innerHeight=200;oldResize();assert.equal(resizes.at(-1).height,200);
const lastChange=[...mediaQueries.at(-1).callbacks][0];
character.dispose();assert.equal(mediaQueries.flatMap(x=>[...x.callbacks]).length,0);
const next=context.createCharacter(host,canvas);const beforeLate=resizes.length;
context.devicePixelRatio=1;oldChange();lastChange();oldResize();assert.equal(resizes.length,beforeLate);
next.dispose();assert.equal(frames.size,0);assert.equal(timers.size,0);assert.equal(listeners.size,0);
assert.equal(mediaQueries.flatMap(x=>[...x.callbacks]).length,0);
""")


@pytest.mark.parametrize("mode", ["missing", "legacy", "throws"])
def test_phone_density_observer_is_optional_and_resume_still_updates(mode):
    run_character("const mode=" + json.dumps(mode) + ";" + r"""
host.kind='phone';let legacyCallback=null;
if(mode==='missing')context.matchMedia=undefined;
else if(mode==='throws')context.matchMedia=()=>{throw new Error('합성 미지원 감지');};
else context.matchMedia=()=>({addListener(fn){legacyCallback=fn;},removeListener(fn){if(legacyCallback===fn)legacyCallback=null;}});
const character=context.createCharacter(host,canvas),placement={scale:1,xPercent:50,yPercent:50};
character.applyPresentation({placement,visible:false});context.devicePixelRatio=3;
character.applyPresentation({placement,visible:true});assert.equal(resizes.at(-1).resolution,3);
character.dispose();assert.equal(legacyCallback,null);
""")


def test_pc_renderer_keeps_existing_options_and_does_not_query_density():
    run_character(r"""
host.kind='pc';context.devicePixelRatio=3;
context.matchMedia=()=>{throw new Error('PC 밀도 감지 금지');};
gl.getParameter=()=>{throw new Error('PC GPU 한도 조회 금지');};
const character=context.createCharacter(host,canvas),options=applications[0].options;
assert.equal(options.resizeTo,vm.runInContext('window',ctx));assert.equal(options.resolution,undefined);
assert.equal(options.width,undefined);assert.equal(options.autoDensity,undefined);
listeners.get('window:resize')();assert.equal(resizes.length,0);
character.dispose();
""")


@pytest.mark.parametrize("phase", ["initialize", "resize", "density", "resume"])
def test_phone_resize_failure_releases_resources_once_and_allows_manual_recreate(phase):
    run_character("const phase=" + json.dumps(phase) + ";" + r"""
host.kind='phone';let character;
if(phase==='initialize') {
    resizeFailure=true;assert.throws(()=>context.createCharacter(host,canvas));
} else {
    character=context.createCharacter(host,canvas);await character.applySnapshot(snapshot);
    const resize=listeners.get('window:resize'),change=[...mediaQueries.at(-1).callbacks][0];
    const placement={scale:1,xPercent:50,yPercent:50};
    if(phase==='resume')character.applyPresentation({placement,visible:false});
    resizeFailure=true;context.innerWidth=600;context.devicePixelRatio=2;
    if(phase==='resume')assert.throws(()=>character.applyPresentation({placement,visible:true}));
    else {
        (phase==='resize'?resize:change)();resize();change();
        assert.deepEqual(JSON.parse(JSON.stringify(inputs.filter(x=>x.type==='document_error'))),[{type:'document_error',code:'character_render_failed'}]);
    }
    character.dispose();
}
assert.equal(vm.runInContext('app',ctx),null);assert.equal(context.live2dModel,null);
assert.equal(frames.size,0);assert.equal(timers.size,0);assert.equal(listeners.size,0);
assert.equal(mediaQueries.flatMap(x=>[...x.callbacks]).length,0);
assert.equal(calls.filter(x=>x==='destroyApp').length,1);
resizeFailure=false;context.createCharacter(host,canvas).dispose();
""")


def test_phone_hidden_suspends_all_owned_activity_and_resumes_same_model():
    run_character(r"""
host.kind='phone';const character=context.createCharacter(host,canvas);
snapshot.settings.enable_idle_synthetic_gestures=true;
await character.applySnapshot(snapshot);const original=context.live2dModel;
const placement={scale:1.5,xPercent:25,yPercent:75};
character.applyPresentation({placement,visible:false});
assert.equal(original.autoUpdate,false);assert.equal(frames.size,0);assert.equal(timers.size,0);
await character.applySnapshot(snapshot); character.applyPreview(snapshot);
await character.applyAction({model_version:snapshot.model_version,kind:'gesture',action_id:'nod'});
character.applyPlayback({active:true,mouth_open:0.6});
assert.equal(values.get('ParamMouthOpenY'),0);assert.equal(frames.size,0);assert.equal(timers.size,0);
character.applyPresentation({placement,visible:true});
character.applyPresentation({placement,visible:true});
assert.equal(original.autoUpdate,true);assert.equal(context.live2dModel,original);
assert.equal(calls.filter(x=>x==='startApp').length,1);
assert.equal(frames.size,1);assert.equal(timers.size,1);
character.dispose();assert.equal(frames.size,0);assert.equal(timers.size,0);
""")


def test_phone_hidden_while_loading_does_not_restart_updates():
    run_character(r"""
host.kind='phone';context.PIXI.live2d.Live2DModel.from=()=>new Promise(resolve=>{releaseModel=resolve;});
const character=context.createCharacter(host,canvas);
const pending=character.applySnapshot(snapshot);
character.applyPresentation({placement:{scale:1,xPercent:50,yPercent:50},visible:false});
releaseModel(model());assert.equal(await pending,true);
assert.equal(context.live2dModel.autoUpdate,false);assert.equal(frames.size,0);assert.equal(timers.size,0);
character.dispose();
""")


@pytest.mark.parametrize("visible", [True, False])
def test_phone_resume_snapshot_cannot_overwrite_newer_expression_during_asset_read(visible):
    run_character(r"""
context.location.origin='https://appassets.androidplatform.net';
const replies=[];context.eneCharacterNative={postMessage:x=>replies.push(JSON.parse(x))};
const generation='00000000-0000-4000-8000-000000000001';
let releaseRead, delayRead=false;
context.fetch=async url=>{
    if(url.endsWith(snapshot.entry_asset_id)) {
        if(delayRead) await new Promise(resolve=>{releaseRead=resolve;});
        return {ok:true,json:async()=>({FileReferences:{Expressions:[
            {Name:'normal',File:'c'.repeat(64)},{Name:'bright',File:'d'.repeat(64)}]}})};
    }
    return {ok:true,json:async()=>({Parameters:[]})};
};
vm.runInContext(PHONE_ENTRY,ctx);
async function send(type,value) {return context.eneCharacterNative.onmessage({data:JSON.stringify({type,value,generation,presentation_generation:1})});}
await send('initialize');await send('binding');await send('snapshot',{...snapshot,action_seq:3});
const original=context.live2dModel;
const placement={scale:1.5,xPercent:25,yPercent:75};
await send('presentation',{placement,visible:false});await send('presentation',{placement,visible:TEST_VISIBLE});
delayRead=true;const refresh=send('snapshot',{...snapshot,action_seq:3});
await send('action',{model_version:snapshot.model_version,kind:'expression',action_id:'bright',action_seq:4,duration_ms:0});
await send('action',{model_version:snapshot.model_version,kind:'gesture',action_id:'nod',action_seq:5});
releaseRead();await refresh;
assert.equal(vm.runInContext('currentEmotionTag',ctx),'bright');
assert.equal(vm.runInContext('activeGestureKey',ctx),'');
assert.equal(context.live2dModel,original);assert.equal(calls.filter(x=>x.endsWith(snapshot.entry_asset_id)).length,1);
assert.equal(replies.at(-1).type,'ready');
if (!TEST_VISIBLE) { assert.equal(frames.size,0); assert.equal(timers.size,0); }
listeners.get('window:pagehide')();
""".replace("TEST_VISIBLE", str(visible).lower()))


def test_pc_placement_does_not_use_phone_fit_or_visibility():
    run_character(r"""
host.kind='pc';const character=context.createCharacter(host,canvas);
await character.applySnapshot(snapshot);
await context.applyENEModelSettings({scale:0.4,xPercent:30,yPercent:60});
assert.equal(character.applyPresentation({placement:{scale:2,xPercent:0,yPercent:0},visible:false}),false);
assert.equal(context.live2dModel.scale.value,0.4);assert.equal(context.live2dModel.x,120);
assert.equal(context.live2dModel.y,360);assert.equal(context.live2dModel.autoUpdate,true);
character.dispose();
""")


def test_all_pc_motion_settings_apply_without_overwriting_phone_placement():
    from tests.test_companion_character_state import MOTION_SETTINGS

    run_character("snapshot.settings=" + json.dumps(MOTION_SETTINGS) + ";" + r"""
host.kind='phone';context.innerHeight=200;
const character=context.createCharacter(host,canvas);
character.applyPresentation({placement:{scale:1.5,xPercent:25,yPercent:75},visible:true});
const configured={};
for(const key of ['setBuiltinIdleMotionEnabled','setAutoEyeBlinkEnabled','setIdleMotionEnabled','setIdleMotionConfig',
    'setExpressiveMotionConfig','setSyntheticGestureScale','setIdleSyntheticGestureConfig','setHeadPatConfig']) {
    const original=context[key];context[key]=(...args)=>{configured[key]=args;return original(...args);};
}
await character.applySnapshot(snapshot);
assert.deepEqual(configured.setBuiltinIdleMotionEnabled,[false]);
assert.deepEqual(configured.setAutoEyeBlinkEnabled,[false]);
assert.deepEqual(configured.setIdleMotionEnabled,[false]);
assert.deepEqual(configured.setIdleMotionConfig,[1.4,1.3]);
assert.deepEqual(configured.setExpressiveMotionConfig,[false,1.6,1.2,0,false]);
assert.deepEqual(configured.setSyntheticGestureScale,[1.7]);
assert.deepEqual(configured.setIdleSyntheticGestureConfig,[true,'high']);
assert.deepEqual(configured.setHeadPatConfig,[false,1.5,300,400,'bright','normal',7]);
await character.applySnapshot({...snapshot,model_version:'c'.repeat(64)});
character.applyPreview({...snapshot,model_version:'c'.repeat(64),settings:{enable_head_pat:true}});
assert.equal(context.live2dModel.scale.value,1.35);assert.equal(context.live2dModel.x,100);assert.equal(context.live2dModel.y,150);
character.dispose();
""")


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
