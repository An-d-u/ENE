"""합성 브리지로 화면 공유 동의, 활성 표시와 종료를 실제 PC 채팅 런타임에서 검증한다."""

from tests.test_chat_dom_runtime import run_dom_case


def test_only_quick_menu_opens_controls_without_starting_capture():
    result = run_dom_case("""
const node = key => document.getElementById('screen-share-' + key);
bridge.screenStateCallback(JSON.stringify({available:true, model:'Demo Vision', remote:true, question:false, observe:false}));
node('floating-btn').click();
result = {fromChat:!!node('button'), fromOverlay:node('panel').open, target:node('destination').textContent,
    enabled:!node('question').disabled, badge:!node('indicator').hidden, calls:bridge.screenCalls};
node('close').click();
result.focus = document.activeElement?.id;
""")
    assert result == {"fromChat": False, "fromOverlay": True, "target": "외부 서버로 전송 · Demo Vision",
                      "focus": "floating-actions-toggle",
                      "enabled": True, "badge": False, "calls": []}


def test_modes_follow_native_confirmation_and_overlay_stop_stays_available():
    result = run_dom_case("""
const node = key => document.getElementById('screen-share-' + key);
const state = {available:true, model:'Demo Vision', remote:false, question:false, observe:false, title:''};
const emit = change => bridge.screen_share_state_changed.emit(JSON.stringify({...state, ...change}));
emit({});
node('floating-btn').click();
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
    modes:node('modes').textContent, receiver:node('receiver').textContent, canStop:!node('overlay-stop').disabled};
node('overlay-stop').click();
emit({});
result = {beforePicker, cancelled, active, stopped:node('indicator').hidden, calls:bridge.screenCalls};
""")
    assert result == {
        "beforePicker": {"checked": False, "hidden": True}, "cancelled": True,
        "active": {"hidden": False, "title": "가상 도형판", "modes": "질문", "receiver": "이 PC에서 처리 · Demo Vision", "canStop": True},
        "stopped": True, "calls": [[True, False], [False, True], [True, True], [True, False], "stop"],
    }


def test_active_icon_opens_details_and_dismisses_them_when_sharing_ends():
    result = run_dom_case("""
const node = key => document.getElementById('screen-share-' + key);
const icon = node('indicator'), details = node('info');
if (!details || icon.tagName !== 'BUTTON') { result = 'missing icon'; return; }
const send = (question, observe, title) => bridge.screen_share_state_changed.emit(JSON.stringify({
    available:true, model:'Demo Vision', remote:true, question, observe, title
}));
let dismissed = false;
details.hidePopover = () => { dismissed = true; };
send(true, true, '모니터 1, 모니터 2');
const active = [!icon.hidden, icon.title, icon.attributes.popovertarget,
    details.attributes.popover, node('window').textContent, node('modes').textContent, node('receiver').textContent];
send(false, false, '');
const ended = [icon.hidden, dismissed];
send(false, true, '가상 창');
window.eneScreenShare.setLanguage('en');
result = {active, ended, next:[icon.hidden, icon.title, node('window').textContent, node('modes').textContent],
    calls:bridge.screenCalls};
""")
    assert result == {
        "active": [True, "공유 중", "screen-share-info", "auto", "모니터 1, 모니터 2", "질문 · 관찰",
                   "외부 서버로 전송 · Demo Vision"],
        "ended": [True, True], "next": [False, "Sharing", "가상 창", "Observation"], "calls": [],
    }


def test_late_initial_read_does_not_overwrite_signal_and_errors_are_localized():
    result = run_dom_case("""
const node = key => document.getElementById('screen-share-' + key);
window.eneScreenShare.setLanguage('ja');
bridge.screen_share_state_changed.emit(JSON.stringify({available:true, model:'Demo Vision', remote:true,
    observe:true, question:false, title:'仮の図形'}));
bridge.screenStateCallback(JSON.stringify({available:false, model:'', remote:false, question:false, observe:false}));
const afterLateRead = node('window').textContent;
node('floating-btn').click();
bridge.screen_share_state_changed.emit(JSON.stringify({available:false, model:'', remote:false, question:false,
    observe:false, error:'capture_unavailable'}));
const error = node('status').textContent;
window.eneScreenShare.setLanguage('en');
window.eneScreenShare.connect({});
result = {afterLateRead, error, unsupported:node('status').textContent, disabled:node('observe').disabled,
    stopped:node('indicator').hidden, calls:bridge.screenCalls};
""")
    assert result == {"afterLateRead": "仮の図形", "error": "選択した共有対象をキャプチャできません。",
                      "unsupported": "Screen sharing is unavailable.", "disabled": True, "stopped": True, "calls": []}
