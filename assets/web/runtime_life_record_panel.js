(function initializeLifeRecordPanel() {
    'use strict';

    const byId = (id) => document.getElementById(id);
    const floatingActionsToggle = byId('floating-actions-toggle');
    const trigger = byId('life-records-floating-btn');
    const panel = byId('life-records-panel');
    const title = byId('life-records-panel-title');
    const closeButton = byId('life-records-close-btn');
    const previousButton = byId('life-records-previous-btn');
    const nextButton = byId('life-records-next-btn');
    const todayButton = byId('life-records-today-btn');
    const dateInput = byId('life-records-date-input');
    const statusNode = byId('life-records-status');
    const list = byId('life-records-list');

    const TEXT = {
        ko: {
            title: '생활 기록', close: '생활 기록 닫기', previous: '이전 날짜', next: '다음 날짜', today: '오늘', date: '생활 기록 날짜',
            loading: '생활 기록을 불러오는 중…', empty: '이 날짜의 생활 기록이 없습니다.', readError: '생활 기록을 읽지 못했습니다.',
            invalidDate: '올바른 날짜를 선택해 주세요.', retry: '다시 시도', latest: '최신 기록', ending: '마지막 상태',
            worldEmpty: '생활 환경이 비어 있어 기록을 만들지 않았습니다.', openSettings: '생활 환경 설정 열기',
            generationFailed: '생활 기록을 만들지 못했습니다.', saveFailed: '생활 기록을 저장하지 못했습니다.',
            regenerationFailed: '다시 만들지 못해 기존 기록을 유지했습니다.', unknownError: '생활 기록을 표시하지 못했습니다.',
            regenerate: '재생성', regenerateTitle: '최신 생활 기록 재생성',
            regenerateDescription: 'API를 호출해 이 기록을 다시 만들고 기존 기록을 교체합니다.', cancel: '취소', confirm: '재생성',
            regenerating: '생활 기록 다시 만드는 중…', preparing: '복귀 기록 정리 중…', thinking: '생각 중…',
            busy: '다른 작업이 진행 중입니다. 잠시 후 다시 시도해 주세요.',
            readOnly: '현재 생활 기록은 읽기 전용입니다.', notLatest: '최신 기록만 재생성할 수 있습니다.',
            cancelled: '생활 기록 재생성이 취소되었습니다.', refreshFailed: '기록은 저장됐지만 화면을 새로 고치지 못했습니다.'
        },
        en: {
            title: 'Life records', close: 'Close life records', previous: 'Previous date', next: 'Next date', today: 'Today', date: 'Life record date',
            loading: 'Loading life records…', empty: 'There are no life records for this date.', readError: 'Life records could not be read.',
            invalidDate: 'Choose a valid date.', retry: 'Retry', latest: 'Latest record', ending: 'Ending state',
            worldEmpty: 'No record was created because the life world is empty.', openSettings: 'Open life world settings',
            generationFailed: 'The life record could not be created.', saveFailed: 'The life record could not be saved.',
            regenerationFailed: 'The original record was kept because regeneration failed.', unknownError: 'The life record could not be displayed.',
            regenerate: 'Regenerate', regenerateTitle: 'Regenerate the latest life record',
            regenerateDescription: 'This calls the API to recreate and replace this record.', cancel: 'Cancel', confirm: 'Regenerate',
            regenerating: 'Regenerating the life record…', preparing: 'Preparing your return record…', thinking: 'Thinking…',
            busy: 'Another task is in progress. Try again shortly.', readOnly: 'Life records are currently read-only.',
            notLatest: 'Only the latest record can be regenerated.', cancelled: 'Life record regeneration was cancelled.',
            refreshFailed: 'The record was saved, but the view could not be refreshed.'
        },
        ja: {
            title: '生活記録', close: '生活記録を閉じる', previous: '前の日', next: '次の日', today: '今日', date: '生活記録の日付',
            loading: '生活記録を読み込み中…', empty: 'この日の生活記録はありません。', readError: '生活記録を読み込めませんでした。',
            invalidDate: '正しい日付を選んでください。', retry: '再試行', latest: '最新の記録', ending: '最後の状態',
            worldEmpty: '生活環境が空のため、記録を作成しませんでした。', openSettings: '生活環境の設定を開く',
            generationFailed: '生活記録を作成できませんでした。', saveFailed: '生活記録を保存できませんでした。',
            regenerationFailed: '再作成に失敗したため、元の記録を維持しました。', unknownError: '生活記録を表示できませんでした。',
            regenerate: '再作成', regenerateTitle: '最新の生活記録を再作成',
            regenerateDescription: 'APIを呼び出してこの記録を作り直し、元の記録と置き換えます。', cancel: 'キャンセル', confirm: '再作成',
            regenerating: '生活記録を作り直しています…', preparing: '帰宅記録を整理しています…', thinking: '考え中…',
            busy: '別の処理を実行中です。しばらくしてからお試しください。', readOnly: '現在、生活記録は読み取り専用です。',
            notLatest: '最新の記録だけ再作成できます。', cancelled: '生活記録の再作成をキャンセルしました。',
            refreshFailed: '記録は保存されましたが、表示を更新できませんでした。'
        }
    };
    const LOCALE_TAG = { ko: 'ko-KR', en: 'en-US', ja: 'ja-JP' };
    let nowProvider = () => new Date();
    let requestSequence = 0;
    const regenerationDisabledSnapshots = new Map();

    function normalizeLanguage(value) {
        const language = String(value || '').trim().toLowerCase().split('-')[0];
        return Object.prototype.hasOwnProperty.call(TEXT, language) ? language : 'en';
    }

    const state = {
        open: false,
        selectedDate: '',
        requestId: '',
        status: 'idle',
        records: [],
        latestId: null,
        lifeRecordsWritable: false,
        readOnlyReason: '',
        interactionLocked: false,
        manualSubmission: false,
        backendPendingObserved: false,
        todayIso: '',
        viewTimezone: 'UTC',
        language: normalizeLanguage(document.documentElement && document.documentElement.lang),
    };

    const strings = () => TEXT[state.language] || TEXT.en;

    function localIsoDate(value) {
        const date = value instanceof Date ? value : new Date(value);
        if (Number.isNaN(date.getTime())) return '';
        return [
            String(date.getFullYear()).padStart(4, '0'),
            String(date.getMonth() + 1).padStart(2, '0'),
            String(date.getDate()).padStart(2, '0'),
        ].join('-');
    }

    function isIsoDate(value) {
        const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if (!match) return false;
        return localIsoDate(new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 12)) === value;
    }

    function shiftedIsoDate(isoDate, offset) {
        const [year, month, day] = String(isoDate || '').split('-').map(Number);
        if (![year, month, day].every(Number.isInteger)) return '';
        return localIsoDate(new Date(year, month - 1, day + offset, 12));
    }

    function updateLabels() {
        const text = strings();
        if (trigger) {
            trigger.textContent = state.language === 'ko' ? '생활' : (state.language === 'ja' ? '生活' : 'Life');
            trigger.title = text.title;
            trigger.setAttribute('aria-label', text.title);
        }
        if (title) title.textContent = text.title;
        if (closeButton) {
            closeButton.title = text.close;
            closeButton.setAttribute('aria-label', text.close);
        }
        if (previousButton) previousButton.setAttribute('aria-label', text.previous);
        if (nextButton) nextButton.setAttribute('aria-label', text.next);
        if (todayButton) todayButton.textContent = text.today;
        if (dateInput) dateInput.setAttribute('aria-label', text.date);
        const dialog = panel && panel.querySelector('.life-record-regeneration-overlay');
        if (dialog) {
            const dialogTitle = dialog.querySelector('.life-record-regeneration-title');
            const dialogDescription = dialog.querySelector('.life-record-regeneration-description');
            const cancel = dialog.querySelector('.life-record-regeneration-cancel');
            const confirm = dialog.querySelector('.life-record-regeneration-confirm');
            if (dialogTitle) dialogTitle.textContent = text.regenerateTitle;
            if (dialogDescription) dialogDescription.textContent = text.regenerateDescription;
            if (cancel) cancel.textContent = text.cancel;
            if (confirm) confirm.textContent = text.confirm;
        }
    }

    function setStatus(kind, message) {
        state.status = kind;
        if (!statusNode) return;
        const nextMessage = String(message || '');
        if (statusNode.dataset.state === kind && statusNode.textContent === nextMessage) return;
        statusNode.textContent = nextMessage;
        statusNode.dataset.state = kind;
    }

    function textElement(tag, className, value) {
        const node = document.createElement(tag);
        node.className = className;
        node.textContent = String(value == null ? '' : value);
        return node;
    }

    function appendSafeMarkdown(target, value) {
        const tokens = String(value == null ? '' : value).split(/(\*\*[^*\n]+\*\*|`[^`\n]+`|\*[^*\n]+\*)/g);
        tokens.forEach((token) => {
            if (!token) return;
            let tag = 'span';
            let text = token;
            if (token.startsWith('**') && token.endsWith('**')) { tag = 'strong'; text = token.slice(2, -2); }
            else if (token.startsWith('`') && token.endsWith('`')) { tag = 'code'; text = token.slice(1, -1); }
            else if (token.startsWith('*') && token.endsWith('*')) { tag = 'em'; text = token.slice(1, -1); }
            target.appendChild(textElement(tag, '', text));
        });
    }

    function formatter(options) {
        try {
            return new Intl.DateTimeFormat(LOCALE_TAG[state.language], { timeZone: state.viewTimezone, ...options });
        } catch (error) {
            return new Intl.DateTimeFormat(LOCALE_TAG[state.language], options);
        }
    }

    function parsedDate(value) {
        const date = new Date(String(value || ''));
        return Number.isNaN(date.getTime()) ? null : date;
    }

    function localDateKey(value) {
        const date = parsedDate(value);
        return date ? formatter({ year: 'numeric', month: '2-digit', day: '2-digit' }).format(date) : '';
    }

    function formatRange(startValue, endValue) {
        const start = parsedDate(startValue);
        const end = parsedDate(endValue);
        if (!start || !end) return '';
        if (localDateKey(startValue) === localDateKey(endValue)) {
            const time = formatter({ hour: '2-digit', minute: '2-digit' });
            return `${time.format(start)} – ${time.format(end)}`;
        }
        const dateTime = formatter({ year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
        return `${dateTime.format(start)} – ${dateTime.format(end)}`;
    }

    function createRecordCard(record) {
        const card = document.createElement('article');
        card.className = 'life-record-card';
        card.dataset.recordId = String(record && record.id || '');
        const header = document.createElement('header');
        header.className = 'life-record-card-header';
        header.appendChild(textElement('div', 'life-record-range', formatRange(record.inactive_started_at, record.returned_at)));
        if (record.id && record.id === state.latestId) header.appendChild(textElement('span', 'life-record-latest', strings().latest));
        card.appendChild(header);

        (Array.isArray(record.entries) ? record.entries : []).forEach((entry) => {
            const row = document.createElement('div');
            row.className = 'life-record-entry';
            row.appendChild(textElement('div', 'life-record-entry-time', formatRange(entry.started_at, entry.ended_at)));
            row.appendChild(textElement('div', 'life-record-entry-place', entry.place));
            const activity = document.createElement('div');
            activity.className = 'life-record-entry-activity';
            appendSafeMarkdown(activity, entry.activity);
            row.appendChild(activity);
            card.appendChild(row);
        });

        const ending = record.ending_state && typeof record.ending_state === 'object' ? record.ending_state : {};
        const endingNode = document.createElement('div');
        endingNode.className = 'life-record-ending';
        endingNode.appendChild(textElement('div', 'life-record-ending-title', strings().ending));
        endingNode.appendChild(textElement('div', 'life-record-ending-place', ending.place));
        const summary = document.createElement('div');
        summary.className = 'life-record-ending-summary';
        appendSafeMarkdown(summary, ending.summary);
        endingNode.appendChild(summary);
        card.appendChild(endingNode);
        if (record.id && record.id === state.latestId) {
            const regenerate = textElement('button', 'life-record-regenerate', strings().regenerate);
            regenerate.type = 'button';
            regenerate.dataset.recordId = record.id;
            regenerate.setAttribute('aria-label', strings().regenerateTitle);
            const baseDisabled = !state.lifeRecordsWritable;
            if (state.interactionLocked) regenerationDisabledSnapshots.set(regenerate, baseDisabled);
            regenerate.disabled = baseDisabled || state.interactionLocked || state.manualSubmission;
            regenerate.addEventListener('click', () => openRegenerationDialog(record.id, regenerate));
            card.appendChild(regenerate);
        }
        return card;
    }

    function renderRecords() {
        if (!list) return;
        list.replaceChildren();
        state.records.forEach((record) => list.appendChild(createRecordCard(record)));
    }

    function renderActionState(kind, message, actionLabel = '', action = null) {
        if (!list) return;
        list.replaceChildren();
        if (!actionLabel || typeof action !== 'function') return;
        const button = textElement('button', kind === 'error' ? 'life-record-retry' : 'life-record-state-action', actionLabel);
        button.type = 'button';
        button.setAttribute('aria-label', `${message} ${actionLabel}`.trim());
        button.addEventListener('click', action);
        list.appendChild(button);
    }

    function safeFocusTarget(preferred) {
        let current = preferred;
        let visible = Boolean(preferred && preferred.isConnected !== false);
        while (visible && current) {
            if (current.hidden || (current.classList && current.classList.contains('hidden'))) visible = false;
            current = current.parentElement;
        }
        if (visible) return preferred;
        if (state.open && dateInput) return dateInput;
        if (floatingActionsToggle) return floatingActionsToggle;
        return trigger;
    }

    let dialogOrigin = null;
    let dialogRecordId = '';
    let operationFocusOrigin = null;

    function restoreDialogFocus() {
        const target = safeFocusTarget(dialogOrigin);
        dialogOrigin = null;
        if (target && typeof target.focus === 'function') target.focus();
    }

    function restoreOperationFocus() {
        const target = safeFocusTarget(operationFocusOrigin);
        operationFocusOrigin = null;
        if (target && typeof target.focus === 'function') target.focus();
    }

    function closeRegenerationDialog(restoreFocus = true) {
        const overlay = panel && panel.querySelector('.life-record-regeneration-overlay');
        if (overlay) overlay.classList.add('hidden');
        if (restoreFocus) restoreDialogFocus();
        dialogRecordId = '';
    }

    function ensureRegenerationDialog() {
        if (!panel) return null;
        let overlay = panel.querySelector('.life-record-regeneration-overlay');
        if (overlay) return overlay;
        overlay = document.createElement('div');
        overlay.className = 'life-record-regeneration-overlay hidden';
        overlay.setAttribute('role', 'alertdialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-labelledby', 'life-record-regeneration-title');
        overlay.setAttribute('aria-describedby', 'life-record-regeneration-description');
        const dialog = document.createElement('div');
        dialog.className = 'life-record-regeneration-dialog';
        const dialogTitle = textElement('div', 'life-record-regeneration-title', strings().regenerateTitle);
        dialogTitle.id = 'life-record-regeneration-title';
        const description = textElement('div', 'life-record-regeneration-description', strings().regenerateDescription);
        description.id = 'life-record-regeneration-description';
        const actions = document.createElement('div');
        actions.className = 'life-record-regeneration-actions';
        const cancel = textElement('button', 'life-record-regeneration-cancel', strings().cancel);
        cancel.type = 'button';
        const confirm = textElement('button', 'life-record-regeneration-confirm', strings().confirm);
        confirm.type = 'button';
        cancel.addEventListener('click', () => closeRegenerationDialog(true));
        confirm.addEventListener('click', confirmRegeneration);
        actions.appendChild(cancel);
        actions.appendChild(confirm);
        dialog.appendChild(dialogTitle);
        dialog.appendChild(description);
        dialog.appendChild(actions);
        overlay.appendChild(dialog);
        overlay.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                closeRegenerationDialog(true);
                return;
            }
            if (event.key !== 'Tab') return;
            const focusable = [cancel, confirm].filter((node) => !node.disabled);
            if (!focusable.length) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        });
        panel.appendChild(overlay);
        return overlay;
    }

    function openRegenerationDialog(recordId, origin) {
        if (recordId !== state.latestId || !state.lifeRecordsWritable || state.interactionLocked || state.manualSubmission) return false;
        const overlay = ensureRegenerationDialog();
        if (!overlay) return false;
        dialogRecordId = recordId;
        dialogOrigin = origin;
        overlay.classList.remove('hidden');
        const cancel = overlay.querySelector('.life-record-regeneration-cancel');
        const confirm = overlay.querySelector('.life-record-regeneration-confirm');
        if (confirm) confirm.disabled = false;
        if (cancel) cancel.focus();
        return true;
    }

    function updateRegenerationButtons() {
        if (!list) return;
        list.querySelectorAll('.life-record-regenerate').forEach((button) => {
            if (state.interactionLocked && !regenerationDisabledSnapshots.has(button)) {
                regenerationDisabledSnapshots.set(button, Boolean(button.disabled));
            }
            button.disabled = !state.lifeRecordsWritable || state.interactionLocked || state.manualSubmission;
        });
    }

    function setInteractionLocked(active, reason = '') {
        const shouldLock = Boolean(active);
        if (shouldLock === state.interactionLocked) return;
        state.interactionLocked = shouldLock;
        if (shouldLock) {
            updateRegenerationButtons();
        } else {
            regenerationDisabledSnapshots.forEach((wasDisabled, button) => {
                if (button && button.isConnected !== false) {
                    button.disabled = wasDisabled || !state.lifeRecordsWritable;
                }
            });
            regenerationDisabledSnapshots.clear();
        }
        if (state.interactionLocked && String(reason) === 'life_record_regeneration') {
            setStatus('regenerating', strings().regenerating);
        }
    }

    function confirmRegeneration() {
        const recordId = dialogRecordId;
        if (!recordId || recordId !== state.latestId || state.manualSubmission || state.interactionLocked || !state.lifeRecordsWritable) return;
        const overlay = ensureRegenerationDialog();
        const confirm = overlay && overlay.querySelector('.life-record-regeneration-confirm');
        if (confirm) confirm.disabled = true;
        state.manualSubmission = true;
        state.backendPendingObserved = false;
        operationFocusOrigin = dialogOrigin;
        closeRegenerationDialog(true);
        setStatus('regenerating', strings().regenerating);
        setInteractionLocked(true, 'life_record_regeneration');
        if (typeof window.setGenerationInteractionLock === 'function') {
            window.setGenerationInteractionLock(true, 'life_record_regeneration');
        }
        try {
            if (!window.pyBridge || typeof window.pyBridge.regenerate_latest_life_record !== 'function') throw new Error('bridge_unavailable');
            window.pyBridge.regenerate_latest_life_record(recordId);
        } catch (error) {
            showNotice('generation_failed');
        }
    }

    function finishPendingOperation(restoreFocus = true) {
        if (!state.manualSubmission && !state.interactionLocked) return false;
        state.manualSubmission = false;
        state.backendPendingObserved = false;
        if (typeof window.setGenerationInteractionLock === 'function'
            && typeof window.isGenerationInteractionLocked === 'function'
            && window.isGenerationInteractionLocked()) {
            window.setGenerationInteractionLock(false, 'life_record_regeneration');
        }
        if (state.interactionLocked) {
            setInteractionLocked(false, 'life_record_regeneration');
        }
        if (restoreFocus) restoreOperationFocus();
        return true;
    }

    function setBackendPending(active) {
        if (active && state.manualSubmission) state.backendPendingObserved = true;
        if (!active && state.manualSubmission) finishPendingOperation();
    }

    function showNotice(code) {
        const text = strings();
        const safeCode = String(code || '');
        const rejectedManual = state.manualSubmission && !state.backendPendingObserved;
        if (rejectedManual) finishPendingOperation(false);
        const preserveRecordNotices = {
            regeneration_failed: text.regenerationFailed,
            generation_failed: text.regenerationFailed,
            save_failed: text.regenerationFailed,
            busy: text.busy,
            read_only: text.readOnly,
            session_lease_unavailable: text.readOnly,
            session_tracker_degraded: text.readOnly,
            timezone_unavailable: text.readOnly,
            not_latest: text.notLatest,
            not_found: text.notLatest,
            cancelled: text.cancelled,
            refresh_failed: text.refreshFailed,
            read_error: text.readError,
            world_empty: text.worldEmpty,
            world_unavailable: text.generationFailed,
        };
        if (state.records.length && preserveRecordNotices[safeCode]) {
            setStatus(safeCode, preserveRecordNotices[safeCode]);
            renderRecords();
            if (safeCode === 'world_empty' && list) {
                const settingsButton = textElement('button', 'life-record-state-action', text.openSettings);
                settingsButton.type = 'button';
                settingsButton.setAttribute('aria-label', `${text.worldEmpty} ${text.openSettings}`);
                settingsButton.addEventListener('click', openSettings);
                list.appendChild(settingsButton);
            }
            if (rejectedManual) restoreOperationFocus();
            return;
        }
        const cases = {
            read_error: ['error', text.readError, text.retry, requestSelectedDate],
            invalid_date: ['error', text.invalidDate, '', null],
            world_empty: ['world_empty', text.worldEmpty, text.openSettings, openSettings],
            generation_failed: ['generation_failed', text.generationFailed, '', null],
            save_failed: ['save_failed', text.saveFailed, '', null],
            regeneration_failed: ['regeneration_failed', text.regenerationFailed, '', null],
            busy: ['busy', text.busy, '', null],
            read_only: ['read_only', text.readOnly, '', null],
            session_lease_unavailable: ['read_only', text.readOnly, '', null],
            session_tracker_degraded: ['read_only', text.readOnly, '', null],
            timezone_unavailable: ['read_only', text.readOnly, '', null],
            not_latest: ['not_latest', text.notLatest, '', null],
            not_found: ['not_latest', text.notLatest, '', null],
            cancelled: ['cancelled', text.cancelled, '', null],
            refresh_failed: ['refresh_failed', text.refreshFailed, text.retry, requestSelectedDate],
        };
        const [kind, message, label, action] = cases[safeCode] || ['error', text.unknownError, text.retry, requestSelectedDate];
        setStatus(kind, message);
        renderActionState(kind, message, label, action);
        if (rejectedManual) restoreOperationFocus();
    }

    function requestSelectedDate() {
        if (!isIsoDate(state.selectedDate)) { showNotice('invalid_date'); return false; }
        requestSequence += 1;
        state.requestId = String(requestSequence);
        setStatus('loading', strings().loading);
        if (list) list.replaceChildren();
        if (window.pyBridge && typeof window.pyBridge.request_life_records_for_date === 'function') {
            window.pyBridge.request_life_records_for_date(state.selectedDate, state.requestId);
            return true;
        }
        showNotice('read_error');
        return false;
    }

    function selectDate(value) {
        if (!isIsoDate(value)) { showNotice('invalid_date'); return false; }
        state.selectedDate = value;
        if (dateInput) dateInput.value = value;
        return requestSelectedDate();
    }

    function openPanel() {
        if (!state.selectedDate) state.selectedDate = state.todayIso || localIsoDate(nowProvider());
        state.open = true;
        if (panel) panel.classList.remove('hidden');
        if (trigger) trigger.setAttribute('aria-expanded', 'true');
        if (dateInput) { dateInput.value = state.selectedDate; dateInput.focus(); }
        if (typeof window.setFloatingActionsOpen === 'function') window.setFloatingActionsOpen(false);
        updateLabels();
        requestSelectedDate();
    }

    function closePanel() {
        state.open = false;
        if (panel) panel.classList.add('hidden');
        if (trigger) trigger.setAttribute('aria-expanded', 'false');
        if (floatingActionsToggle) floatingActionsToggle.focus();
        else if (trigger) trigger.focus();
    }

    function validPublicEntry(entry) {
        return Boolean(entry && typeof entry === 'object' && !Array.isArray(entry)
            && typeof entry.started_at === 'string'
            && typeof entry.ended_at === 'string'
            && typeof entry.place === 'string'
            && typeof entry.activity === 'string');
    }

    function validPublicRecord(record) {
        return Boolean(record && typeof record === 'object' && !Array.isArray(record)
            && typeof record.id === 'string'
            && typeof record.inactive_started_at === 'string'
            && typeof record.returned_at === 'string'
            && Array.isArray(record.entries)
            && record.entries.every(validPublicEntry)
            && record.ending_state && typeof record.ending_state === 'object'
            && !Array.isArray(record.ending_state)
            && typeof record.ending_state.place === 'string'
            && typeof record.ending_state.summary === 'string');
    }

    function receive(value) {
        let payload = value;
        if (typeof value === 'string') {
            try { payload = JSON.parse(value); } catch (error) { showNotice('read_error'); return false; }
        }
        if (!payload || typeof payload !== 'object' || Array.isArray(payload)) { showNotice('read_error'); return false; }
        if (Array.isArray(payload.affected_dates)) {
            if (state.open && payload.affected_dates.includes(state.selectedDate)) requestSelectedDate();
            return true;
        }
        if (payload.requested_date !== state.selectedDate || String(payload.request_id || '') !== state.requestId) return false;
        const validRecords = Array.isArray(payload.records) && payload.records.every(validPublicRecord);
        if (payload.status !== 'ready' || !validRecords) {
            showNotice('read_error');
            return false;
        }
        state.language = normalizeLanguage(payload.language);
        state.viewTimezone = typeof payload.view_timezone === 'string' && payload.view_timezone ? payload.view_timezone : 'UTC';
        state.latestId = typeof payload.latest_id === 'string' ? payload.latest_id : null;
        state.lifeRecordsWritable = payload.life_records_writable === true;
        const publicReadOnlyReasons = ['session_lease_unavailable', 'timezone_unavailable', 'session_tracker_degraded'];
        state.readOnlyReason = publicReadOnlyReasons.includes(payload.read_only_reason) ? payload.read_only_reason : '';
        state.records = payload.records.slice();
        updateLabels();
        if (state.records.length) {
            setStatus(state.lifeRecordsWritable ? 'ready' : 'read_only', state.lifeRecordsWritable ? '' : strings().readOnly);
            renderRecords();
        }
        else { setStatus('empty', strings().empty); renderActionState('empty', strings().empty); }
        return true;
    }

    function openSettings() {
        if (window.pyBridge && typeof window.pyBridge.open_settings_dialog_section === 'function') {
            window.pyBridge.open_settings_dialog_section('life_world');
        } else if (window.pyBridge && typeof window.pyBridge.open_settings_dialog === 'function') {
            window.pyBridge.open_settings_dialog();
        }
    }

    if (trigger) trigger.addEventListener('click', () => state.open ? closePanel() : openPanel());
    if (closeButton) closeButton.addEventListener('click', closePanel);
    if (previousButton) previousButton.addEventListener('click', () => selectDate(shiftedIsoDate(state.selectedDate, -1)));
    if (nextButton) nextButton.addEventListener('click', () => selectDate(shiftedIsoDate(state.selectedDate, 1)));
    if (todayButton) todayButton.addEventListener('click', () => selectDate(state.todayIso || localIsoDate(nowProvider())));
    if (dateInput) dateInput.addEventListener('change', () => selectDate(dateInput.value));
    if (panel) panel.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') { event.preventDefault(); closePanel(); }
    });

    updateLabels();
    window.eneLifeRecordPanel = {
        open: openPanel,
        close: closePanel,
        receive,
        showNotice,
        setLanguage(value) {
            state.language = normalizeLanguage(value);
            updateLabels();
            renderRecords();
        },
        setUiContext(value) {
            const source = value && typeof value === 'object' ? value : {};
            if (isIsoDate(source.todayIso)) state.todayIso = source.todayIso;
            if (typeof source.viewTimezone === 'string' && source.viewTimezone) {
                state.viewTimezone = source.viewTimezone;
            }
        },
        setInteractionLocked,
        setBackendPending,
        finishPendingOperation,
        getStageText(stage) {
            if (stage === 'life_record') return strings().preparing;
            if (stage === 'life_record_regeneration') return strings().regenerating;
            return strings().thinking;
        },
        setNowProvider(provider) { if (typeof provider === 'function') nowProvider = provider; },
        getState() { return { ...state, records: state.records.slice() }; },
    };
}());
