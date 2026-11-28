// 대화 포즈는 모델의 대기 모션·호흡·물리를 계산하기 전에 ENE 트래킹 자세에 합성한다.
window.eneResponseMotion = (() => {
    // 대화가 고른 제스처의 의미를 유지하면서 성격에 맞는 변형을 사용한다.
    const gestureVariants = {
        restrained: {nod: 'short-ack', surprise: 'small-surprise'},
        gentle: {bow: 'lean-in', shake: 'gentle-no', tilt: 'thoughtful-tilt'},
    };
    const repeatScales = [1, .9, .8];
    let config = {mode: 'classic'};
    let bank = null, loading = null;
    let active = null, roll = null, idleReturn = 1;

    function usesPose() {
        return config.mode === 'accent';
    }

    function reset() {
        active = null;
        roll = null;
        idleReturn = 1;
    }

    async function configure(next) {
        if (config.mode !== next.mode) {
            window.cancelPendingResponseGesture?.();
            reset();
        }
        config = next;
        if (!config.enabled) active = null;
        if (active) active.clip = null;
        // 감정 동작을 꺼도 응답 제스처에는 같은 파일의 곡선이 필요하다.
        if (!usesPose() || bank) return;
        if (!loading) {
            loading = fetch('motions/response-accent.json').then(response => {
                if (!response.ok) throw new Error('대화 모션 파일을 열 수 없습니다.');
                return response.json();
            }).then(data => { bank = data; }).catch(error => {
                console.warn('대화 모션을 불러오지 못했습니다.', error);
            }).finally(() => { loading = null; });
        }
        await loading;
    }

    function start(expression) {
        const name = String(expression ?? '').trim().toLowerCase();
        active = usesPose() && config.enabled && name ? {name, startMs: performance.now(), weight: 1} : null;
    }

    function resolveEmotionClip(name) {
        // 직접 지정한 표정은 파일명을 그대로 구별한다. 구분 기호를 무시하는 규칙은 자동 연결에만 쓴다.
        const overrides = config.emotionOverrides ?? {};
        let emotion = Object.hasOwn(overrides, name) ? overrides[name] : null;
        if (emotion === 'none') return null;
        if (typeof emotion !== 'string' || !Object.hasOwn(bank.emotions, emotion + '.standard')) {
            const key = name.normalize('NFKC').toLowerCase().replace(/[\s_-]+/g, '');
            if (!Object.hasOwn(bank.aliases, key)) return null;
            emotion = bank.aliases[key];
        }
        return bank.emotions[emotion + '.' + config.preset] ?? bank.emotions[emotion + '.standard'];
    }

    // Cubism 제한 베지어에서는 제어점의 시간이 구간을 3등분한다.
    function sampleCurve(points, seconds) {
        let fromTime = points[0], from = points[1];
        for (let i = 2; i < points.length;) {
            const kind = points[i++];
            const end = kind === 1 ? i + 4 : i;
            const toTime = points[end], to = points[end + 1];
            if (seconds < toTime) {
                if (kind === 2) return from;
                if (kind === 3) return to;
                const t = Math.max(0, (seconds - fromTime) / (toTime - fromTime));
                if (kind === 0) return from + (to - from) * t;
                const u = 1 - t;
                return u ** 3 * from + 3 * u * u * t * points[i + 1] + 3 * u * t * t * points[i + 3] + t ** 3 * to;
            }
            fromTime = toTime;
            from = to;
            i = end + 2;
        }
        return from;
    }

    function sampleClip(clip, seconds, scale) {
        const offsets = {};
        for (const [axis, points] of Object.entries(clip.tracks)) {
            offsets[axis] = (sampleCurve(points, seconds) - points[1]) * scale;
        }
        return offsets;
    }

    function scaleAxes(offsets, head = 1, body = 1) {
        for (const axis of Object.keys(offsets)) {
            if (axis.startsWith('angle')) offsets[axis] *= head;
            if (axis.startsWith('body')) offsets[axis] *= body;
        }
        return offsets;
    }

    function emotionOffsets(now, dtMs) {
        if (!active || !bank) return null;
        const clip = active.clip ??= resolveEmotionClip(active.name);
        const age = Math.max(0, (now - active.startMs) / 1000);
        if (!clip || age >= clip.duration) {
            active = null;
            return null;
        }
        const responding = activeGestureKey && !IDLE_SYNTHETIC_GESTURES.includes(activeGestureKey);
        const target = responding ? (config.overlapPercent ?? 28) / 100 : 1;
        active.weight += (target - active.weight) * (1 - Math.exp(-dtMs / 120));
        const tail = easeGestureInOut((clip.duration - age) / .30);
        return scaleAxes(sampleClip(clip, age, .57 * active.weight * tail), config.head, config.body);
    }

    function gestureClip(key) {
        if (!usesPose() || !bank) return null;
        return bank.gestures[gestureVariants[config.preset]?.[key] ?? key] ?? null;
    }

    function gestureOffsets(clip, progress) {
        return sampleClip(clip, progress * clip.duration, .7);
    }

    function scaleGesture(offsets) {
        scaleAxes(offsets, config.gestureHead, config.gestureBody);
        if (usesPose()) offsets.bodyZ = 0;
    }

    function idleWeight(paused, dtMs) {
        if (!usesPose()) return paused ? 0 : 1;
        idleReturn = paused ? 0 : Math.min(1, idleReturn + dtMs / 1000);
        return easeGestureInOut(idleReturn);
    }

    // 물리나 모델 내장 모션도 몸 전체를 기울일 수 있어 그리기 직전에 중립값을 복원한다.
    function render(core) {
        if (!usesPose()) return;
        if (roll?.core !== core) {
            const id = detectTrackingParams(core).bodyAngleZ;
            const index = readLive2DParameterIds(core).indexOf(id);
            const neutral = index < 0 ? 0 : readLive2DParameterIndexedValue(core, id,
                ['getParameterDefaultValue'], ['defaultValues', 'defaults', 'parameterDefaultValues'], 0);
            roll = {core, id: index < 0 ? null : id, neutral};
        }
        if (roll.id) core.setParameterValueById(roll.id, roll.neutral);
    }

    function echoLimit() {
        return usesPose() ? Math.max(0, Math.min(3, Math.trunc(config.repeatLimit) || 0)) : null;
    }

    function echoScale(index) {
        return usesPose() ? repeatScales[index] ?? null : null;
    }

    return {configure, start, reset, usesPose, render, emotionOffsets, idleWeight,
        gestureClip, gestureOffsets, scaleGesture, echoLimit, echoScale};
})();
