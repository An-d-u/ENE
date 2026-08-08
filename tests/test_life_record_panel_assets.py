from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess


WEB_DIR = Path(__file__).resolve().parents[1] / "assets" / "web"
PANEL_PATH = WEB_DIR / "runtime_life_record_panel.js"


def _run_panel_case(case_script: str) -> dict:
    node_script = f"""
const fs = require('fs');
const vm = require('vm');

class ClassList {{
    constructor(owner) {{ this.owner = owner; }}
    _parts() {{ return String(this.owner.className || '').split(/\\s+/).filter(Boolean); }}
    contains(name) {{ return this._parts().includes(name); }}
    add(name) {{ if (!this.contains(name)) this.owner.className = [...this._parts(), name].join(' '); }}
    remove(name) {{ this.owner.className = this._parts().filter((part) => part !== name).join(' '); }}
    toggle(name, force) {{
        const enabled = force === undefined ? !this.contains(name) : Boolean(force);
        if (enabled) this.add(name); else this.remove(name);
        return enabled;
    }}
}}

class Element {{
    constructor(tagName, id = '') {{
        this.tagName = String(tagName).toUpperCase();
        this.id = id;
        this.children = [];
        this.parentElement = null;
        this.className = '';
        this.classList = new ClassList(this);
        this.dataset = {{}};
        this.attributes = {{}};
        this.eventListeners = {{}};
        this.textContent = '';
        this.value = '';
        this.type = '';
        this.hidden = false;
    }}
    appendChild(child) {{ child.parentElement = this; this.children.push(child); return child; }}
    replaceChildren(...children) {{ this.children = []; this.textContent = ''; children.forEach((child) => this.appendChild(child)); }}
    setAttribute(name, value) {{ this.attributes[name] = String(value); }}
    getAttribute(name) {{ return this.attributes[name] ?? null; }}
    addEventListener(type, handler) {{ (this.eventListeners[type] ||= []).push(handler); }}
    dispatch(type, extra = {{}}) {{
        const event = {{ target: this, key: '', preventDefault() {{}}, stopPropagation() {{}}, ...extra }};
        (this.eventListeners[type] || []).forEach((handler) => handler(event));
    }}
    click() {{ this.dispatch('click'); }}
    focus() {{ document.activeElement = this; }}
    querySelectorAll(selector) {{
        const found = [];
        const visit = (node) => node.children.forEach((child) => {{
            if (selector.startsWith('.') && child.classList.contains(selector.slice(1))) found.push(child);
            visit(child);
        }});
        visit(this);
        return found;
    }}
    querySelector(selector) {{ return this.querySelectorAll(selector)[0] || null; }}
}}

const ids = [
  'life-records-floating-btn', 'life-records-panel', 'life-records-panel-title',
  'life-records-close-btn', 'life-records-previous-btn', 'life-records-next-btn',
  'life-records-today-btn', 'life-records-date-input', 'life-records-status',
  'life-records-list', 'floating-action-buttons'
];
const elements = Object.fromEntries(ids.map((id) => [id, new Element(id.includes('input') ? 'input' : 'div', id)]));
elements['life-records-panel'].className = 'hidden';
elements['life-records-floating-btn'].setAttribute('aria-expanded', 'false');

const requests = [];
const document = {{
    activeElement: null,
    documentElement: {{ lang: 'ko' }},
    createElement: (tagName) => new Element(tagName),
    createTextNode: (value) => {{ const node = new Element('#text'); node.textContent = String(value); return node; }},
    getElementById: (id) => elements[id] || null,
    addEventListener: () => {{}},
}};
const window = {{
    pyBridge: {{
        request_life_records_for_date: (date, requestId) => requests.push([date, requestId]),
    }},
    setFloatingActionsOpen: () => {{}},
}};
const context = {{ window, document, elements, requests, console: {{ warn: () => {{}}, error: () => {{}} }}, Intl, Date, setTimeout, clearTimeout, result: null }};
const runtimeSource = fs.readFileSync({json.dumps(str(PANEL_PATH))}, 'utf8');
const caseSource = {json.dumps(case_script)};
vm.createContext(context);
vm.runInContext(runtimeSource + '\\n' + caseSource, context, {{ filename: 'runtime_life_record_panel.js' }});
process.stdout.write(JSON.stringify(context.result));
"""
    try:
        completed = subprocess.run(
            ["node", "-e", node_script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
        )
    except subprocess.TimeoutExpired as error:
        raise AssertionError("life record panel Node test timed out") from error
    assert completed.returncode == 0, (
        f"life record panel Node test failed (exit={completed.returncode}); "
        f"stdout_chars={len(completed.stdout)} stderr_chars={len(completed.stderr)}"
    )
    return json.loads(completed.stdout)


def test_life_record_panel_markup_and_runtime_are_loaded_in_safe_order():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8-sig")

    assert 'id="life-records-floating-btn"' in html
    assert 'aria-controls="life-records-panel"' in html
    assert 'id="life-records-panel"' in html
    assert 'role="region"' in html
    assert 'aria-labelledby="life-records-panel-title"' in html
    assert 'id="life-records-date-input"' in html
    assert 'type="date"' in html
    assert 'id="life-records-status"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-atomic="true"' in html
    assert '<script src="runtime_life_record_panel.js"></script>' in html
    assert html.index("runtime_life_record_panel.js") < html.index("runtime_bridge.js")


def test_panel_starts_on_injected_local_today_and_all_date_controls_request_iso_dates():
    result = _run_panel_case(
        """
window.eneLifeRecordPanel.setNowProvider(() => new Date(2099, 7, 7, 10, 0, 0));
window.eneLifeRecordPanel.open();
elements['life-records-previous-btn'].click();
elements['life-records-next-btn'].click();
elements['life-records-date-input'].value = '2099-08-03';
elements['life-records-date-input'].dispatch('change');
elements['life-records-today-btn'].click();
result = {
  selected: window.eneLifeRecordPanel.getState().selectedDate,
  requests,
  focused: document.activeElement && document.activeElement.id,
  expanded: elements['life-records-floating-btn'].getAttribute('aria-expanded'),
};
"""
    )

    assert result["selected"] == "2099-08-07"
    assert [item[0] for item in result["requests"]] == [
        "2099-08-07",
        "2099-08-06",
        "2099-08-07",
        "2099-08-03",
        "2099-08-07",
    ]
    assert len({item[1] for item in result["requests"]}) == 5
    assert result["focused"] == "life-records-date-input"
    assert result["expanded"] == "true"


def test_stale_response_is_ignored_and_ready_records_keep_backend_order():
    result = _run_panel_case(
        """
window.eneLifeRecordPanel.setNowProvider(() => new Date(2099, 7, 7, 10, 0, 0));
window.eneLifeRecordPanel.open();
const first = requests[0];
elements['life-records-previous-btn'].click();
const current = requests[1];
window.eneLifeRecordPanel.receive({
  status: 'ready', requested_date: first[0], request_id: first[1],
  view_timezone: 'Asia/Seoul', language: 'ko', latest_id: 'latest',
  records: [{ id: 'stale', entries: [], ending_state: { place: 'x', summary: 'stale' } }]
});
const staleCount = elements['life-records-list'].children.length;
window.eneLifeRecordPanel.receive({
  status: 'ready', requested_date: current[0], request_id: current[1],
  view_timezone: 'Asia/Seoul', language: 'ko', latest_id: 'latest',
  records: [
    { id: 'newer', inactive_started_at: '2099-08-06T08:00:00+09:00', returned_at: '2099-08-06T09:00:00+09:00', entries: [{ started_at: '2099-08-06T08:00:00+09:00', ended_at: '2099-08-06T09:00:00+09:00', place: 'Garden', activity: 'First' }], ending_state: { place: 'Garden', summary: 'One' } },
    { id: 'older', inactive_started_at: '2099-08-06T06:00:00+09:00', returned_at: '2099-08-06T07:00:00+09:00', entries: [{ started_at: '2099-08-06T06:00:00+09:00', ended_at: '2099-08-06T07:00:00+09:00', place: 'Room', activity: 'Second' }], ending_state: { place: 'Room', summary: 'Two' } },
  ]
});
const cards = elements['life-records-list'].querySelectorAll('.life-record-card');
result = { staleCount, ids: cards.map((card) => card.dataset.recordId), state: window.eneLifeRecordPanel.getState() };
"""
    )

    assert result["staleCount"] == 0
    assert result["ids"] == ["newer", "older"]
    assert result["state"]["status"] == "ready"


def test_invalid_current_response_becomes_retryable_error_while_invalid_stale_is_ignored():
    result = _run_panel_case(
        """
window.eneLifeRecordPanel.setNowProvider(() => new Date(2099, 7, 7, 10, 0, 0));
window.eneLifeRecordPanel.open();
const stale = requests[0];
elements['life-records-previous-btn'].click();
const current = requests[1];
window.eneLifeRecordPanel.receive({ status: 'ready', requested_date: stale[0], request_id: stale[1], records: 'invalid' });
const afterStale = window.eneLifeRecordPanel.getState().status;
window.eneLifeRecordPanel.receive({ status: 'ready', requested_date: current[0], request_id: current[1], records: 'invalid' });
result = {
  afterStale,
  afterCurrent: window.eneLifeRecordPanel.getState().status,
  retryCount: elements['life-records-list'].querySelectorAll('.life-record-retry').length,
};
"""
    )

    assert result == {
        "afterStale": "loading",
        "afterCurrent": "error",
        "retryCount": 1,
    }


def test_midnight_entries_show_dates_and_record_text_never_uses_inner_html():
    result = _run_panel_case(
        """
window.eneLifeRecordPanel.setNowProvider(() => new Date(2099, 7, 7, 10, 0, 0));
window.eneLifeRecordPanel.open();
const request = requests[0];
window.eneLifeRecordPanel.receive({
  status: 'ready', requested_date: request[0], request_id: request[1],
  view_timezone: 'Asia/Seoul', language: 'en', latest_id: 'record-1',
  records: [{
    id: 'record-1', inactive_started_at: '2099-08-06T23:30:00+09:00', returned_at: '2099-08-07T00:30:00+09:00',
    entries: [{ started_at: '2099-08-06T23:30:00+09:00', ended_at: '2099-08-07T00:30:00+09:00', place: '<img src=x onerror=alert(1)>', activity: '**Walked** <script>boom()</script>' }],
    ending_state: { place: 'Square', summary: '<b>Safe</b>' }
  }]
});
const list = elements['life-records-list'];
const allText = [];
const allTags = [];
const visit = (node) => { allText.push(node.textContent); allTags.push(node.tagName); node.children.forEach(visit); };
visit(list);
result = { allText, allTags };
"""
    )

    rendered = " ".join(result["allText"])
    assert "2099" in rendered
    assert "<img src=x onerror=alert(1)>" in rendered
    assert "<script>boom()</script>" in rendered
    assert "SCRIPT" not in result["allTags"]
    assert "IMG" not in result["allTags"]


def test_empty_error_retry_and_escape_focus_lifecycle_are_distinct():
    result = _run_panel_case(
        """
window.eneLifeRecordPanel.setNowProvider(() => new Date(2099, 7, 7, 10, 0, 0));
window.eneLifeRecordPanel.open();
const first = requests[0];
window.eneLifeRecordPanel.receive({ status: 'ready', requested_date: first[0], request_id: first[1], view_timezone: 'Asia/Seoul', language: 'ja', records: [], latest_id: null });
const emptyStatus = window.eneLifeRecordPanel.getState().status;
window.eneLifeRecordPanel.showNotice('read_error');
const errorStatus = window.eneLifeRecordPanel.getState().status;
const retry = elements['life-records-list'].querySelector('.life-record-retry');
retry.click();
elements['life-records-panel'].dispatch('keydown', { key: 'Escape' });
result = {
  emptyStatus, errorStatus, requestCount: requests.length,
  hidden: elements['life-records-panel'].classList.contains('hidden'),
  focused: document.activeElement && document.activeElement.id,
  expanded: elements['life-records-floating-btn'].getAttribute('aria-expanded'),
};
"""
    )

    assert result == {
        "emptyStatus": "empty",
        "errorStatus": "error",
        "requestCount": 2,
        "hidden": True,
        "focused": "life-records-floating-btn",
        "expanded": "false",
    }


def test_bridge_connects_life_record_payloads_and_safe_notices():
    bridge = (WEB_DIR / "runtime_bridge.js").read_text(encoding="utf-8-sig")

    assert "window.pyBridge.life_record_items_updated" in bridge
    assert "window.eneLifeRecordPanel.receive(value)" in bridge
    assert "window.pyBridge.life_record_notice" in bridge
    assert "window.eneLifeRecordPanel.showNotice(code)" in bridge
    assert "console.log(value)" not in bridge


def test_panel_css_is_responsive_scrollable_wrapping_and_keyboard_visible():
    css = (WEB_DIR / "style.css").read_text(encoding="utf-8-sig")
    panel = re.search(r"#life-records-panel\s*\{(?P<body>.*?)\n\}", css, re.DOTALL)
    date_row = re.search(r"#life-records-date-controls\s*\{(?P<body>.*?)\n\}", css, re.DOTALL)
    list_rule = re.search(r"#life-records-list\s*\{(?P<body>.*?)\n\}", css, re.DOTALL)

    assert panel and "width: min(420px, calc(100vw - 24px));" in panel.group("body")
    assert panel and "max-height: calc(100vh - 124px);" in panel.group("body")
    assert date_row and "flex-wrap: wrap;" in date_row.group("body")
    assert list_rule and "overflow-y: auto;" in list_rule.group("body")
    assert "overflow-wrap: anywhere;" in css
    assert "min-width: 44px;" in css
    assert "min-height: 44px;" in css
    assert "#life-records-panel :focus-visible" in css
    assert "@media (max-width: 420px)" in css
    assert "max-width: 100%;" in css
