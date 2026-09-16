"""가상 SDK 경계에서 PC 모델의 실제 범위와 로컬 세대 대조를 검증한다."""

import json

from tests.test_companion_character_runtime import WEB, run_character


def catalog_case(case):
    source = (WEB / "runtime_companion_character.js").read_text(encoding="utf-8")
    run_character(
        "vm.runInContext("
        + json.dumps(source)
        + ",ctx);\n"
        + r"""
const reports=[];
ctx.pyBridge={report_companion_character_catalog:value=>reports.push(JSON.parse(value))};
ctx.createCharacter(host,canvas);
ctx.eneModelConfig={modelPath:'synthetic.model3.json',companionModelGeneration:'11111111-1111-4111-8111-111111111111',availableEmotions:['normal','bright']};
const request={generation:ctx.eneModelConfig.companionModelGeneration,model_version:'a'.repeat(64)};
const actual=model();
actual.internalModel.coreModel._model={parameters:{ids:['ParamAccent'],minimumValues:[-0.5],maximumValues:[0.75],defaultValues:[0.25]}};
ctx.PIXI.live2d.Live2DModel.from=async()=>actual;
"""
        + case
    )


def test_pc_catalog_waits_for_sdk_ready_and_never_widens_actual_ranges():
    catalog_case(r"""
ctx.requestCompanionCharacterCatalog(JSON.stringify(request));
assert.equal(reports.length,0);
await ctx.applyENEModelSettings(ctx.eneModelConfig);
assert.equal(reports.length,1);
assert.deepEqual(reports[0].parameters,[{id:'ParamAccent',min:-0.5,max:0.75,default:0.25}]);
assert.deepEqual(reports[0].expressions,['bright','normal']);
assert.ok(reports[0].gestures.includes('nod'));
assert.equal(JSON.stringify(reports[0]).includes('synthetic.model3.json'),false);
ctx.eneModelConfig.companionModelGeneration='22222222-2222-4222-8222-222222222222';
ctx.requestCompanionCharacterCatalog(JSON.stringify(request));
assert.equal(reports.length,1);
ctx.eneCharacter?.dispose();
""")


def test_sdk_without_real_parameter_limits_is_not_reported_as_ready():
    catalog_case(r"""
actual.internalModel.coreModel._model.parameters.minimumValues[0]=NaN;
await ctx.applyENEModelSettings(ctx.eneModelConfig);
ctx.requestCompanionCharacterCatalog(JSON.stringify(request));
assert.equal(reports.length,1);
assert.equal(reports[0].status,'unsupported');
assert.equal(reports[0].parameters,undefined);
""")


def test_replaced_model_does_not_let_old_load_report_catalog():
    catalog_case(r"""
let release;
ctx.PIXI.live2d.Live2DModel.from=()=>new Promise(resolve=>{release=resolve;});
ctx.requestCompanionCharacterCatalog(JSON.stringify(request));
const loading=ctx.applyENEModelSettings(ctx.eneModelConfig);
ctx.eneModelConfig.companionModelGeneration='22222222-2222-4222-8222-222222222222';
release(actual);
await loading;
assert.equal(reports.length,0);
""")
