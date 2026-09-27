/** 실제 Pixi Application과 WebGL만 사용한다. SDK·모델·개인 자료는 읽지 않는다. */
(() => {
    const output = document.getElementById('probe-result');
    const canvas = document.getElementById('live2d-canvas');
    const check = (condition, code) => { if (!condition) throw new Error(code); };
    const Application = PIXI.Application;
    let character = null, initialWidth, initialHeight, resizeCount = 0;
    let maxTransitionPixels = 0;
    if (!PIXI.utils.isWebGLSupported()) {
        output.textContent = JSON.stringify({status:'unavailable', code:'webgl_unavailable'});
        return;
    }
    try {
        for (const axis of ['width','height']) {
            const property = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, axis);
            Object.defineProperty(canvas, axis, {configurable:true,
                get() { return property.get.call(canvas); },
                set(value) {
                    property.set.call(canvas, value);
                    maxTransitionPixels = Math.max(maxTransitionPixels, canvas.width * canvas.height);
                    const gl = app?.renderer?.gl;
                    if (gl) maxTransitionPixels = Math.max(maxTransitionPixels, gl.drawingBufferWidth * gl.drawingBufferHeight);
                }});
        }
        // 실제 생성자·resize를 그대로 호출하며 초기 버퍼와 호출 횟수만 관찰한다.
        PIXI.Application = class extends Application {
            constructor(options) {
                super(options);
                initialWidth = this.view.width; initialHeight = this.view.height;
                const resize = this.renderer.resize.bind(this.renderer);
                this.renderer.resize = (...args) => { resizeCount++; return resize(...args); };
            }
        };
        character = window.createCharacter({kind:'phone',
            assetUrl() { throw new Error('unexpected_asset_read'); },
            emitInput(value) { check(value.type !== 'error', 'host_error'); }}, canvas);
        check(initialWidth === 1 && initialHeight === 1, 'initial_buffer');
        const renderer = app.renderer, gl = renderer.gl;
        const limits = readPhoneRenderLimits(renderer);
        check(limits.valid, 'gpu_limits');
        const expected = calculatePhoneRenderSize(innerWidth, innerHeight, devicePixelRatio, limits);
        const graphic = new PIXI.Graphics().beginFill(0x2266ee).drawRect(0,0,40,40).endFill();
        app.stage.addChild(graphic);
        renderer.render(app.stage);
        const rect = canvas.getBoundingClientRect();
        check(canvas.width === expected.bufferWidth && canvas.height === expected.bufferHeight, 'canvas_buffer');
        check(gl.drawingBufferWidth === canvas.width && gl.drawingBufferHeight === canvas.height, 'gl_buffer');
        check(Math.abs(rect.width - innerWidth) <= .5 / renderer.resolution + .02 &&
            Math.abs(rect.height - innerHeight) <= .5 / renderer.resolution + .02, 'css_size');
        check(Math.abs(renderer.screen.width - rect.width) < .02 &&
            Math.abs(renderer.screen.height - rect.height) < .02, 'logical_screen');
        const before = resizeCount;
        check(character.applyPresentation({visible:true,placement:{scale:6,xPercent:-300,yPercent:400}}), 'expanded_placement');
        window.dispatchEvent(new Event('resize'));
        window.dispatchEvent(new Event('resize'));
        check(resizeCount === before && before === 1, 'duplicate_resize');
        check(canvas.width === expected.bufferWidth && canvas.height === expected.bufferHeight, 'zoom_buffer');
        const glError = gl.getError();
        check(glError === gl.NO_ERROR, 'gl_error');
        const result = {status:'passed',dpr:devicePixelRatio,
            logicalWidth:innerWidth,logicalHeight:innerHeight,resolution:renderer.resolution,
            bufferWidth:canvas.width,bufferHeight:canvas.height,
            drawingBufferWidth:gl.drawingBufferWidth,drawingBufferHeight:gl.drawingBufferHeight,
            cssWidth:rect.width,cssHeight:rect.height,maxWidth:limits.width,maxHeight:limits.height,
            initialWidth,initialHeight,resizeCount,glError};
        // 표시 크기만 합성 회전시킨다. 버퍼 크기 쓰기와 WebGL 렌더러는 실제 구현 그대로다.
        let viewportWidth = innerWidth, viewportHeight = innerHeight;
        Object.defineProperty(window, 'innerWidth', {configurable:true,get:()=>viewportWidth});
        Object.defineProperty(window, 'innerHeight', {configurable:true,get:()=>viewportHeight});
        for (const [width,height] of [[1000,2000],[2000,1000],[400,600]]) {
            viewportWidth = width; viewportHeight = height;
            window.dispatchEvent(new Event('resize'));
            renderer.render(app.stage);
            check(gl.getError() === gl.NO_ERROR, 'transition_gl_error');
        }
        check(maxTransitionPixels <= 4194304, 'transition_pixel_budget');
        output.textContent = JSON.stringify({...result,maxTransitionPixels});
    } catch (_) {
        output.textContent = JSON.stringify({status:'failed',code:'renderer_check_failed'});
    } finally {
        character?.dispose();
        PIXI.Application = Application;
    }
})();
