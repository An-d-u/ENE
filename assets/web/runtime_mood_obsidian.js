
// -1~1 축값을 게이지 표시용 0~1 값으로 정규화한다.
function normalizeMoodAxis(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return 0.5;
    return Math.max(0, Math.min(1, (n + 1) / 2));
}

// 내부 mood 키를 사용자 표시용 라벨로 변환한다.
function formatMoodLabel(label) {
    const map = (currentUiStrings && currentUiStrings.mood && currentUiStrings.mood.states)
        ? currentUiStrings.mood.states
        : DEFAULT_UI_STRINGS.mood.states;
    return map[label] || label || map.unknown || DEFAULT_UI_STRINGS.mood.states.unknown;
}

// mood 바의 width(%)를 갱신한다.
function setMoodMeterWidth(el, normalized) {
    if (!el) return;
    const width = Math.round(Math.max(0, Math.min(1, normalized)) * 100);
    el.style.width = `${width}%`;
}

// mood 위젯 패널 열림/닫힘 상태를 반영한다.
function setMoodPanelOpen(open) {
    moodPanelOpen = Boolean(open);
    if (moodWidget) {
        moodWidget.classList.toggle('hidden', !moodPanelOpen);
    }
}

// 기분 패널을 드래그 가능하게 설정한다.
function initMoodWidgetDrag() {
    if (!moodWidget || !moodStatusHeader) return;

    moodStatusHeader.addEventListener('mousedown', (e) => {
        // 닫기 버튼 클릭은 드래그 시작하지 않는다.
        if (e.target && e.target.id === 'mood-status-collapse-btn') return;
        const rect = moodWidget.getBoundingClientRect();
        moodWidget.style.right = 'auto';
        moodWidget.style.left = `${rect.left}px`;
        moodWidget.style.top = `${rect.top}px`;

        moodWidgetDragState = {
            offsetX: e.clientX - rect.left,
            offsetY: e.clientY - rect.top,
        };
        e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!moodWidgetDragState || !moodWidget) return;
        const left = Math.max(0, e.clientX - moodWidgetDragState.offsetX);
        const top = Math.max(0, e.clientY - moodWidgetDragState.offsetY);
        moodWidget.style.left = `${left}px`;
        moodWidget.style.top = `${top}px`;
    });

    document.addEventListener('mouseup', () => {
        moodWidgetDragState = null;
    });
}

// mood 텍스트/게이지/툴팁을 한 번에 갱신한다.
function updateMoodWidget(label, temporaryState, valence, energy, bond, stress) {
    currentMoodSnapshot = {
        label: label,
        temporaryState: temporaryState || 'steady',
        valence: valence,
        energy: energy,
        bond: bond,
        stress: stress
    };

    if (moodStatusLabel) {
        moodStatusLabel.textContent = formatMoodStatusText(label, temporaryState);
    }

    setMoodMeterWidth(moodMeterValence, normalizeMoodAxis(valence));
    setMoodMeterWidth(moodMeterBond, normalizeMoodAxis(bond));
    setMoodMeterWidth(moodMeterEnergy, normalizeMoodAxis(energy));
    setMoodMeterWidth(moodMeterStress, normalizeMoodAxis(stress));

    const axis = (currentUiStrings && currentUiStrings.mood && currentUiStrings.mood.axis)
        ? currentUiStrings.mood.axis
        : DEFAULT_UI_STRINGS.mood.axis;
    if (moodMeterValence) moodMeterValence.title = `${axis.valence} ${Number(valence).toFixed(2)}`;
    if (moodMeterBond) moodMeterBond.title = `${axis.bond} ${Number(bond).toFixed(2)}`;
    if (moodMeterEnergy) moodMeterEnergy.title = `${axis.energy} ${Number(energy).toFixed(2)}`;
    if (moodMeterStress) moodMeterStress.title = `${axis.stress} ${Number(stress).toFixed(2)}`;
    if (moodStatusLabel) {
        moodStatusLabel.title = `${axis.valence} ${Number(valence).toFixed(2)} / ${axis.bond} ${Number(bond).toFixed(2)} / ${axis.energy} ${Number(energy).toFixed(2)} / ${axis.stress} ${Number(stress).toFixed(2)}`;
    }
}

window.applyENEUiStrings(window.eneUiStrings);
updateMoodWidget('calm', 'steady', 0, 0, 0, 0);
setMoodPanelOpen(false);
setGoalPanelOpen(false);
initMoodWidgetDrag();

// Obsidian 트리 데이터를 렌더링한다.
function renderObsTree(payload) {
    if (!obsTree) return;
    obsTree.innerHTML = '';

    if (!payload || !payload.ok) {
        const msg = document.createElement('div');
        msg.className = 'obs-node obs-file';
        msg.textContent = payload && payload.error
            ? `연결 실패: ${payload.error}`
            : 'Vault 연결 정보가 없습니다.';
        obsTree.appendChild(msg);
        return;
    }

    const checked = new Set(payload.checked_files || []);
    obsCheckedPaths = checked;

    const createNode = (node, depth = 0) => {
        const row = document.createElement('div');
        row.className = `obs-node ${node.type === 'dir' ? 'obs-dir' : 'obs-file'}`;
        row.style.paddingLeft = `${depth * 12}px`;

        if (node.type === 'file') {
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.checked = checked.has(node.path);
            cb.addEventListener('change', () => {
                if (!window.pyBridge || !window.pyBridge.set_obs_file_checked) return;
                window.pyBridge.set_obs_file_checked(node.path, cb.checked);
            });
            row.appendChild(cb);
        } else {
            const icon = document.createElement('span');
            icon.textContent = '📁';
            row.appendChild(icon);
        }

        const label = document.createElement('span');
        label.className = 'obs-path';
        label.textContent = node.path || node.name;
        row.appendChild(label);
        obsTree.appendChild(row);

        if (node.type === 'dir' && Array.isArray(node.children)) {
            node.children.forEach((child) => createNode(child, depth + 1));
        }
    };

    (payload.nodes || []).forEach((node) => createNode(node, 0));
}

function requestObsTree() {
    if (!window.pyBridge || typeof window.pyBridge.get_obs_tree_json !== 'function') return;
    const apply = (value) => {
        if (!value) return;
        try {
            const parsed = typeof value === 'string' ? JSON.parse(value) : value;
            renderObsTree(parsed);
        } catch (e) {
            renderObsTree({ ok: false, error: `트리 파싱 실패: ${e}` });
        }
    };
    try {
        window.pyBridge.get_obs_tree_json(function (value) {
            apply(value);
        });
    } catch (e) {
        renderObsTree({ ok: false, error: String(e) });
    }
}
