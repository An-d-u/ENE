(() => {
    'use strict';

    const node = name => document.getElementById('screen-share-' + name);
    const panel = node('panel');
    const indicator = node('indicator');
    const info = node('info');
    const question = node('question');
    const observe = node('observe');
    const labels = {
        ko: {
            title: '화면 공유', close: '닫기', stop: '공유 종료', active: '화면 공유 중',
            badge: '공유 중', details: '화면 공유 중, 상세 보기', source: '공유 대상', modes: '사용 중', receiver: '이미지 처리',
            question: '질문할 때 화면 보기', observe: '화면의 변화를 보고 먼저 말하기',
            questionShort: '질문', observeShort: '관찰', local: '이 PC에서 처리', remote: '외부 서버로 전송',
            choose: '기능을 켠 뒤 모니터를 한 대 이상 선택하거나 창 하나를 고르세요.', unavailable: '현재 화면 공유를 사용할 수 없습니다.',
            captureError: '선택한 화면을 캡처할 수 없습니다.'
        },
        en: {
            title: 'Share screen', close: 'Close', stop: 'Stop sharing', active: 'Sharing screen',
            badge: 'Sharing', details: 'Screen sharing active, show details', source: 'Sharing', modes: 'In use', receiver: 'Image processing',
            question: 'See the screen when I ask', observe: 'Comment on changes on screen',
            questionShort: 'Questions', observeShort: 'Observation', local: 'Processed on this PC', remote: 'Sent to an external server',
            choose: 'Turn on an option, then choose one or more monitors or a single window.', unavailable: 'Screen sharing is unavailable.',
            captureError: 'The selected screen could not be captured.'
        },
        ja: {
            title: '画面共有', close: '閉じる', stop: '共有を停止', active: '画面を共有中',
            badge: '共有中', details: '画面を共有中、詳細を表示', source: '共有対象', modes: '使用中', receiver: '画像の処理先',
            question: '質問するときに画面を見る', observe: '画面の変化を見て話しかける',
            questionShort: '質問', observeShort: '観察', local: 'このPCで処理', remote: '外部サーバーに送信',
            choose: '機能をオンにして、モニターを1台以上、またはウィンドウを1つ選んでください。', unavailable: '現在画面を共有できません。',
            captureError: '選択した共有対象をキャプチャできません。'
        }
    };
    let text;
    let bridge = null;
    let state = {};
    let waiting = false;
    let failed = false;

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
        if (!active && !indicator.hidden) {
            const hadFocus = document.activeElement === indicator || info.contains(document.activeElement);
            info.hidePopover?.();
            if (hadFocus) document.getElementById('floating-actions-toggle').focus();
        }
        indicator.hidden = !active;
        node('window').textContent = active ? state.title : '';
        node('modes').textContent = modes.join(' · ');
        node('receiver').textContent = active ? destination : '';
    }

    function setLanguage(language) {
        text = labels[language] || labels.en;
        node('floating-btn').textContent = node('title').textContent = text.title;
        node('close').setAttribute('aria-label', text.close);
        node('info-close').setAttribute('aria-label', text.close);
        indicator.title = text.badge;
        indicator.setAttribute('aria-label', text.details);
        node('source-label').textContent = text.source;
        node('modes-label').textContent = text.modes;
        node('receiver-label').textContent = text.receiver;
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
        // 선택 결과가 도착하기 전에는 기존 공유 상태를 표시한다.
        render();
        bridge.configure_screen_share(enableQuestion, enableObserve);
    }

    node('floating-btn').addEventListener('click', () => {
        setFloatingActionsOpen(false);
        panel.showModal();
    });
    node('close').addEventListener('click', () => panel.close());
    panel.addEventListener('close', () => document.getElementById('floating-actions-toggle').focus());
    question.addEventListener('change', configure);
    observe.addEventListener('change', configure);
    node('stop').addEventListener('click', () => bridge?.stop_screen_share());
    node('overlay-stop').addEventListener('click', () => bridge?.stop_screen_share());
    window.eneScreenShare = {connect, setLanguage};
    setLanguage(document.documentElement?.lang || 'ko');
})();
