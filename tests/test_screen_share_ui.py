"""합성 브리지로 화면 공유 동의, 활성 표시와 종료를 실제 PC 채팅 런타임에서 검증한다."""

from tests.test_chat_dom_runtime import run_dom_case


def test_chat_and_overlay_open_controls_without_starting_capture():
    result = run_dom_case("""
const node = key => document.getElementById('screen-share-' + key);
if (!node('button')) { result = {missing: true}; return; }
bridge.screenStateCallback(JSON.stringify({available:true, model:'Demo Vision', remote:true, question:false, observe:false}));
node('button').click();
const fromChat = node('panel').open;
node('close').click();
node('floating-btn').click();
result = {fromChat, fromOverlay:node('panel').open, target:node('destination').textContent,
    enabled:!node('question').disabled, badge:!node('indicator').hidden, calls:bridge.screenCalls};
""")
    assert result == {"fromChat": True, "fromOverlay": True, "target": "외부 서버로 전송 · Demo Vision",
                      "enabled": True, "badge": False, "calls": []}


def test_modes_follow_native_confirmation_and_overlay_stop_stays_available():
    result = run_dom_case("""
const node = key => document.getElementById('screen-share-' + key);
const state = {available:true, model:'Demo Vision', remote:false, question:false, observe:false, title:''};
const emit = change => bridge.screen_share_state_changed.emit(JSON.stringify({...state, ...change}));
emit({});
node('button').click();
node('question').checked = true;
node('question').listeners.change();
const beforePicker = {checked:node('question').checked, hidden:node('indicator').hidden};
emit({});
const cancelled = !node('question').checked && !node('question').disabled;
node('observe').checked = true;
node('observe').listeners.change();
emit({observe:true,title:'가상 도형판'});
node('question').checked = true;
node('question').listeners.change();
emit({question:true,observe:true,title:'가상 도형판'});
node('observe').checked = false;
node('observe').listeners.change();
emit({question:true,title:'가상 도형판'});
node('close').click();
setRequestPending(true);
const active = {hidden:node('indicator').hidden, title:node('window').textContent,
    detail:node('detail').textContent, canStop:!node('overlay-stop').disabled};
node('overlay-stop').click();
emit({});
result = {beforePicker, cancelled, active, stopped:node('indicator').hidden, calls:bridge.screenCalls};
""")
    assert result == {
        "beforePicker": {"checked": False, "hidden": True}, "cancelled": True,
        "active": {"hidden": False, "title": "가상 도형판", "detail": "질문 · 이 PC에서 처리 · Demo Vision", "canStop": True},
        "stopped": True, "calls": [[True, False], [False, True], [True, True], [True, False], "stop"],
    }


def test_late_initial_read_does_not_overwrite_signal_and_errors_are_localized():
    result = run_dom_case("""
const node = key => document.getElementById('screen-share-' + key);
window.eneScreenShare.setLanguage('ja');
bridge.screen_share_state_changed.emit(JSON.stringify({available:true, model:'Demo Vision', remote:true,
    observe:true, question:false, title:'仮の図形'}));
bridge.screenStateCallback(JSON.stringify({available:false, model:'', remote:false, question:false, observe:false}));
const afterLateRead = node('window').textContent;
node('button').click();
bridge.screen_share_state_changed.emit(JSON.stringify({available:false, model:'', remote:false, question:false,
    observe:false, error:'capture_unavailable'}));
const error = node('status').textContent;
window.eneScreenShare.setLanguage('en');
window.eneScreenShare.connect({});
result = {afterLateRead, error, unsupported:node('status').textContent, disabled:node('observe').disabled,
    stopped:node('indicator').hidden, calls:bridge.screenCalls};
""")
    assert result == {"afterLateRead": "仮の図形", "error": "選択したウィンドウを取得できません。",
                      "unsupported": "Window sharing is unavailable.", "disabled": True, "stopped": True, "calls": []}
