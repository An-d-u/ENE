(() => {
    'use strict';

    const node = name => document.getElementById('screen-share-' + name);
    const panel = node('panel');
    const question = node('question');
    const observe = node('observe');
    const labels = {
        ko: {
            title: '화면 공유', button: '화면 공유', close: '닫기', stop: '공유 종료', active: '창 공유 중',
            question: '질문할 때 창 보기', observe: '창의 변화를 보고 먼저 말하기',
            questionShort: '질문', observeShort: '관찰', local: '이 PC에서 처리', remote: '외부 서버로 전송',
            choose: '기능을 켜면 공유할 창을 선택합니다.', unavailable: '현재 창 공유를 사용할 수 없습니다.',
            captureError: '선택한 창을 캡처할 수 없습니다.'
        },
        en: {
            title: 'Share window', button: 'Share', close: 'Close', stop: 'Stop sharing', active: 'Sharing window',
            question: 'See the window when I ask', observe: 'Comment on changes in the window',
            questionShort: 'Questions', observeShort: 'Observation', local: 'Processed on this PC', remote: 'Sent to an external server',
            choose: 'Turn on an option to choose a window to share.', unavailable: 'Window sharing is unavailable.',
            captureError: 'The selected window could not be captured.'
        },
        ja: {
            title: 'ウィンドウ共有', button: '共有', close: '閉じる', stop: '共有を停止', active: 'ウィンドウを共有中',
            question: '質問するときにウィンドウを見る', observe: 'ウィンドウの変化を見て話しかける',
            questionShort: '質問', observeShort: '観察', local: 'このPCで処理', remote: '外部サーバーに送信',
            choose: '機能をオンにして共有するウィンドウを選んでください。', unavailable: '現在ウィンドウを共有できません。',
            captureError: '選択したウィンドウを取得できません。'
        }
    };
    let text;
    let bridge = null;
    let state = {};
    let waiting = false;
    let failed = false;
    let returnFocus;

    function render() {
        const active = state.question || state.observe;
        const destination = typeof state.remote === 'boolean' && state.model
            ? [state.remote ? text.remote : text.local, state.model].join(' · ') : '';
        const available = !!(bridge && state.available && destination && !failed);
        const modes = [state.question && text.questionShort, state.observe && text.observeShort].filter(Boolean);
        question.checked = !!state.question;
        observe.checked = !!state.observe;
        question.disabled = observe.disabled = !available || waiting;
        node('destination').textContent = destination;
        let status = text.unavailable;
        if (available) status = active ? state.title : text.choose;
        if (state.error) status = text.captureError;
        node('status').textContent = status;
        node('stop').hidden = !active;
        node('indicator').hidden = !active;
        node('window').textContent = active ? state.title : '';
        node('detail').textContent = [...modes, destination].filter(Boolean).join(' · ');
        node('button').classList.toggle('is-sharing', !!active);
    }

    function setLanguage(language) {
        text = labels[language] || labels.en;
        node('button').title = text.title;
        node('button-label').textContent = text.button;
        node('button').setAttribute('aria-label', text.title);
        node('floating-btn').textContent = node('title').textContent = text.title;
        node('close').setAttribute('aria-label', text.close);
        node('question-label').textContent = text.question;
        node('observe-label').textContent = text.observe;
        node('stop').textContent = node('overlay-stop').textContent = text.stop;
        node('active').textContent = text.active;
        render();
    }

    function receive(raw) {
        waiting = false;
        let next;
        try { next = JSON.parse(raw); } catch (_) { /* 잘못된 상태로 기존 공유 표시를 지우지 않는다. */ }
        failed = !next || typeof next.available !== 'boolean'
            || typeof next.question !== 'boolean' || typeof next.observe !== 'boolean';
        if (!failed) {
            if (next.error && next.error !== state.error && !panel.open) window.showToast?.(text.captureError, 'error');
            state = next;
        }
        render();
    }

    function connect(nextBridge) {
        state = {};
        waiting = failed = false;
        bridge = typeof nextBridge?.get_screen_share_state === 'function'
            && typeof nextBridge.configure_screen_share === 'function'
            && typeof nextBridge.stop_screen_share === 'function'
            && typeof nextBridge.screen_share_state_changed?.connect === 'function' ? nextBridge : null;
        render();
        if (!bridge) return;
        let receivedSignal = false;
        bridge.screen_share_state_changed.connect(raw => {
            if (bridge !== nextBridge) return;
            receivedSignal = true;
            receive(raw);
        });
        bridge.get_screen_share_state(raw => {
            if (bridge === nextBridge && !receivedSignal) receive(raw);
        });
    }

    function configure() {
        const enableQuestion = question.checked;
        const enableObserve = observe.checked;
        waiting = true;
        // 창 선택 결과가 도착하기 전에는 기존 동의 상태를 표시한다.
        render();
        bridge.configure_screen_share(enableQuestion, enableObserve);
    }

    function open(focusTarget) {
        returnFocus = focusTarget;
        panel.showModal();
    }

    node('button').addEventListener('click', () => open(node('button')));
    node('floating-btn').addEventListener('click', () => {
        setFloatingActionsOpen(false);
        open(document.getElementById('floating-actions-toggle'));
    });
    node('close').addEventListener('click', () => panel.close());
    panel.addEventListener('close', () => returnFocus?.focus());
    question.addEventListener('change', configure);
    observe.addEventListener('change', configure);
    node('stop').addEventListener('click', () => bridge?.stop_screen_share());
    node('overlay-stop').addEventListener('click', () => bridge?.stop_screen_share());
    window.eneScreenShare = {connect, setLanguage};
    setLanguage(document.documentElement?.lang || 'ko');
})();
