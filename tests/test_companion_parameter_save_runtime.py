"""합성 Qt 콜백으로 저장 확인·충돌·늦은 응답을 검사한다."""

from test_chat_ui_assets import _run_live2d_parameter_runtime_case


SETUP = """
const timers = new Map(); let timerId = 0; let snapshotCallback; let commitCallback;
const calls = []; const toasts = [];
window.setTimeout = (fn) => { timers.set(++timerId, fn); return timerId; };
window.clearTimeout = (id) => timers.delete(id);
window.showToast = (message, type) => toasts.push(type);
window.pyBridge = {
    get_live2d_parameter_edit_snapshot: (key, cb) => { snapshotCallback = cb; },
    commit_live2d_parameter_overrides: (key, payload, baseline, cb) => {
        calls.push({ key, payload: JSON.parse(payload), baseline: JSON.parse(baseline) });
        commitCallback = cb;
    },
};
const baseline = { model_key: 'synthetic', generation: 'g1', settings_revision: 1,
    payload: { values: { ParamAccent: .2, ParamKeep: .3 }, favorites: ['ParamKeep'] } };
window.onLive2DParameterModelChanged({modelKey: 'synthetic', companionModelGeneration: 'g1', parameterOverrides: baseline.payload});
live2dParameterState.metadataStatus = 'ready';
live2dParameterState.metadata = [{id:'ParamAccent', current:.2, default:0, min:0, max:1}];
getLive2DParameterInspectorSnapshot();
snapshotCallback(JSON.stringify(baseline));
live2dParameterState.dirtyValues.ParamAccent = .8;
"""


def run(case):
    return _run_live2d_parameter_runtime_case(SETUP + case)


def test_success_waits_for_storage_acknowledgement():
    answer = run("""
saveLive2DParameterOverrides();
const pending = {toasts: [...toasts], dirty: {...live2dParameterState.dirtyValues}, state: buildLive2DParameterInspectorSnapshot().saveStatus};
commitCallback(JSON.stringify({status:'accepted', baseline: {...baseline, settings_revision:2,
    payload:{values:{ParamAccent:.8, ParamKeep:.9}, favorites:['ParamKeep']}}}));
result = {pending, toasts, dirty:live2dParameterState.dirtyValues, values:live2dParameterState.values, timers:timers.size};
""")
    assert answer["pending"] == {"toasts": [], "dirty": {"ParamAccent": .8}, "state": "saving"}
    assert answer["toasts"] == ["success"] and answer["dirty"] == {}
    assert answer["values"] == {"ParamAccent": .8, "ParamKeep": .9}
    assert answer["timers"] == 0


def test_failure_keeps_edits_without_success_or_retry():
    answer = run("""
saveLive2DParameterOverrides();
commitCallback(JSON.stringify({status:'rejected', reason:'storage_failed'}));
result = {toasts, dirty:live2dParameterState.dirtyValues, calls:calls.length, state:buildLive2DParameterInspectorSnapshot().saveStatus};
""")
    assert answer == {"toasts": ["error"], "dirty": {"ParamAccent": .8}, "calls": 1, "state": "error"}


def test_remote_untouched_values_do_not_become_local_edits_on_conflict_retry():
    answer = run("""
window.onLive2DParameterModelChanged({modelKey:'synthetic', companionModelGeneration:'g1',
    parameterOverrides:{values:{ParamAccent:.6, ParamKeep:.9}, favorites:['ParamKeep']}});
saveLive2DParameterOverrides();
commitCallback(JSON.stringify({status:'conflict', reason:'revision_conflict', conflicts:{ParamAccent:.6},
    baseline:{...baseline, settings_revision:2, payload:{values:{ParamAccent:.6, ParamKeep:.9}, favorites:['ParamKeep']}}}));
const afterConflict = {calls:calls.length, state:buildLive2DParameterInspectorSnapshot().saveStatus};
saveLive2DParameterOverrides();
result = {calls, afterConflict, toasts};
""")
    assert answer["afterConflict"] == {"calls": 1, "state": "conflict"}
    assert answer["calls"][0]["payload"]["values"]["ParamKeep"] == .3
    second = answer["calls"][1]
    assert second["baseline"]["payload"]["values"] == {"ParamAccent": .6, "ParamKeep": .3}
    assert second["payload"]["values"] == {"ParamAccent": .8, "ParamKeep": .3}
    assert answer["toasts"] == ["error"]


def test_late_commit_after_model_replacement_cannot_clear_new_edits():
    answer = run("""
saveLive2DParameterOverrides(); const oldCallback = commitCallback;
window.onLive2DParameterModelChanged({modelKey:'synthetic', companionModelGeneration:'g2', parameterOverrides:{values:{}, favorites:[]}});
live2dParameterState.dirtyValues.ParamAccent = .4;
oldCallback(JSON.stringify({status:'accepted', baseline}));
result = {toasts, dirty:live2dParameterState.dirtyValues, timers:timers.size};
""")
    assert answer == {"toasts": [], "dirty": {"ParamAccent": .4}, "timers": 0}


def test_timeout_is_unknown_and_late_success_is_ignored():
    answer = run("""
saveLive2DParameterOverrides(); const oldCallback = commitCallback;
const timeout = [...timers.values()][0]; timeout();
oldCallback(JSON.stringify({status:'accepted', baseline}));
result = {toasts, dirty:live2dParameterState.dirtyValues, calls:calls.length, state:buildLive2DParameterInspectorSnapshot().saveStatus};
""")
    assert answer == {"toasts": ["error"], "dirty": {"ParamAccent": .8}, "calls": 1, "state": "unknown"}
