/**
 * Live2D 모델 렌더링 스크립트
 * Pixi.js와 pixi-live2d-display를 사용하여 Live2D 모델 로드
 */

// 디버그 로그
console.log("=== Live2D script loaded ===");
console.log("Window location:", window.location.href);

// Pixi.js 및 Live2D 라이브러리 확인
console.log("PIXI available:", typeof PIXI !== 'undefined');
console.log("Live2DCubismCore available:", typeof Live2DCubismCore !== 'undefined');
console.log("PIXI.live2d available:", typeof PIXI !== 'undefined' && typeof PIXI.live2d !== 'undefined');

// PIXI가 없으면 중단
if (typeof PIXI === 'undefined') {
    console.error("CRITICAL: PIXI.js is not loaded!");
    document.body.innerHTML = '<div style="color: red; font-family: Arial; text-align: center; margin-top: 50px; font-size: 18px;">PIXI.js 로드 실패<br><br>페이지를 새로고침해 주세요.</div>';
    throw new Error("PIXI.js not loaded");
}

// PIXI.live2d가 없으면 중단
if (typeof PIXI.live2d === 'undefined') {
    console.error("CRITICAL: PIXI.live2d is not available!");
    console.log("Available PIXI properties:", Object.keys(PIXI));
    document.body.innerHTML = '<div style="color: red; font-family: Arial; text-align: center; margin-top: 50px; font-size: 16px;">' +
        'pixi-live2d-display 라이브러리 로드 실패<br><br>' +
        '사용 가능한 PIXI: ' + Object.keys(PIXI).slice(0, 10).join(', ') + '...<br><br>' +
        '페이지를 새로고침해 주세요.</div>';
    throw new Error("PIXI.live2d not available");
}

console.log("✓ All libraries loaded successfully");

// Pixi 앱 초기화
const app = new PIXI.Application({
    view: document.getElementById('live2d-canvas'),
    transparent: true,
    backgroundAlpha: 0,
    resizeTo: window,
    antialias: true
});

console.log("Pixi app initialized");
console.log("Canvas size:", window.innerWidth, "x", window.innerHeight);

// 모델 경로 (상대 경로로 설정)
const modelPath = '../live2d_models/jksalt/jksalt.model3.json';

// 절대 경로 계산 (디버깅용)
const baseUrl = window.location.href.substring(0, window.location.href.lastIndexOf('/'));
const absoluteModelPath = new URL(modelPath, baseUrl + '/').href;
console.log("Model path (relative):", modelPath);
console.log("Model path (absolute):", absoluteModelPath);

// Live2D 모델 로드
async function loadModel() {
    try {
        console.log(`\n=== Loading model ===`);
        console.log(`Path: ${modelPath}`);

        // pixi-live2d-display 사용
        console.log("Calling PIXI.live2d.Live2DModel.from()...");
        const model = await PIXI.live2d.Live2DModel.from(modelPath);

        console.log("✓ Model loaded successfully!");
        console.log("Model size:", model.width, "x", model.height);

        // 모델을 전역 변수에 저장 (Python에서 접근 가능하게)
        window.live2dModel = model;

        // 모델을 스테이지에 추가
        app.stage.addChild(model);

        // 앵커 설정 (중심 기준)
        model.anchor.set(0.5, 0.5);

        // 기본 크기 및 위치 (Python 설정으로 덮어씌워질 예정)
        const scaleX = window.innerWidth / model.width;
        const scaleY = window.innerHeight / model.height;
        const scale = Math.min(scaleX, scaleY) * 0.8;  // 80% 크기로

        model.scale.set(scale);
        model.x = window.innerWidth / 2;
        model.y = window.innerHeight / 2;

        console.log(`Model positioned at (${model.x}, ${model.y}) with scale ${scale}`);


        // 자동 모션 재생 (있는 경우)
        if (model.internalModel && model.internalModel.motionManager) {
            console.log("Motion manager available");
            try {
                model.motion('Idle');
                console.log("Idle motion started");
            } catch (e) {
                console.warn("Failed to start Idle motion:", e);
            }
        } else {
            console.log("No motion manager found");
        }

        // 눈 깜빡임 (존재하는 경우)
        if (model.internalModel && model.internalModel.eyeBlink) {
            console.log("Eye blink enabled");
        }

        // 전역 참조 저장
        window.live2dModel = model;

        console.log("=== Model setup complete ===\n");

    } catch (error) {
        console.error("❌ Failed to load Live2D model");
        console.error("Error:", error);
        console.error("Error type:", error.constructor.name);
        console.error("Error message:", error.message);
        if (error.stack) {
            console.error("Stack trace:", error.stack);
        }

        // 에러 메시지 표시
        const errorText = new PIXI.Text(
            `Live2D 모델 로드 실패\n\n` +
            `에러: ${error.message}\n\n` +
            `경로: ${modelPath}\n` +
            `절대경로: ${absoluteModelPath}\n\n` +
            `콘솔을 확인하세요 (F12)`,
            {
                fontFamily: 'Arial',
                fontSize: 14,
                fill: 0xff0000,
                align: 'center',
                wordWrap: true,
                wordWrapWidth: window.innerWidth - 40
            }
        );
        errorText.x = window.innerWidth / 2;
        errorText.y = window.innerHeight / 2;
        errorText.anchor.set(0.5);
        app.stage.addChild(errorText);
    }
}

// 윈도우 리사이즈 처리
window.addEventListener('resize', () => {
    if (window.live2dModel) {
        const model = window.live2dModel;

        const scaleX = window.innerWidth / model.width;
        const scaleY = window.innerHeight / model.height;
        const scale = Math.min(scaleX, scaleY) * 0.8;

        model.scale.set(scale);
        model.x = window.innerWidth / 2;
        model.y = window.innerHeight / 2;

        console.log("Window resized, model repositioned");
    }
});

// 모델 로드 시작
console.log("\n=== Starting model load ===");
loadModel();

// ==========================================
// 마우스 트래킹 기능
// ==========================================

// 현재 마우스 위치 (정규화된 값: -1 ~ 1)
let currentMouseX = 0;
let currentMouseY = 0;

// 목표 마우스 위치 (부드러운 전환을 위한 중간값)
let targetMouseX = 0;
let targetMouseY = 0;

// 마우스 트래킹 활성화 여부
let mouseTrackingEnabled = true;

/**
 * Python에서 호출: 전역 마우스 위치 업데이트
 * @param {number} mouseX - 캔버스 내 마우스 X 좌표 (픽셀)
 * @param {number} mouseY - 캔버스 내 마우스 Y 좌표 (픽셀)
 */
window.updateMousePosition = function (mouseX, mouseY) {
    if (!mouseTrackingEnabled) return;

    const model = window.live2dModel;
    if (!model) return;

    // 캔버스 크기
    const canvasWidth = window.innerWidth;
    const canvasHeight = window.innerHeight;

    // 모델의 위치 (중심점)
    const modelX = model.x;
    const modelY = model.y;

    // 모델 기준 상대 위치 계산
    const relativeX = mouseX - modelX;
    const relativeY = mouseY - modelY;

    // 정규화 (-1 ~ 1 범위로)
    // 화면 크기의 50%를 기준으로 정규화 (너무 과장되지 않게)
    const normalizedX = (relativeX / (canvasWidth * 0.5));

    // Y축은 오프셋을 추가하여 기본 시선이 정면을 향하도록 조정
    // 마우스가 모델 위치보다 아래에 있을 때 약간 위쪽으로 오프셋
    const normalizedY = (relativeY / (canvasHeight * 0.5)) - 0.3;  // -0.3 오프셋 추가

    // 범위 제한 (-1.5 ~ 1.5로 약간 여유를 둠)
    targetMouseX = Math.max(-1.5, Math.min(1.5, normalizedX));
    targetMouseY = Math.max(-1.5, Math.min(1.5, normalizedY));
};

/**
 * 마우스 트래킹 ON/OFF
 * @param {boolean} enabled 
 */
window.setMouseTrackingEnabled = function (enabled) {
    mouseTrackingEnabled = enabled;
    console.log("Mouse tracking:", enabled ? "enabled" : "disabled");

    // 비활성화 시 원위치로
    if (!enabled) {
        targetMouseX = 0;
        targetMouseY = 0;
        currentMouseX = 0;
        currentMouseY = 0;

        // 파라미터 즉시 초기화
        const model = window.live2dModel;
        if (model && model.internalModel) {
            try {
                model.internalModel.coreModel.setParameterValueById('ParamAngleX', 0);
                model.internalModel.coreModel.setParameterValueById('ParamAngleY', 0);
                model.internalModel.coreModel.setParameterValueById('ParamBodyAngleX', 0);
                model.internalModel.coreModel.setParameterValueById('ParamEyeBallX', 0);
                model.internalModel.coreModel.setParameterValueById('ParamEyeBallY', 0);
            } catch (e) {
                // 파라미터 없어도 무시
            }
        }
    }
};

// 애니메이션 루프: 부드러운 전환 및 모델 업데이트
function updateMouseTracking() {
    const model = window.live2dModel;
    if (!model || !mouseTrackingEnabled) {
        requestAnimationFrame(updateMouseTracking);
        return;
    }

    // 부드러운 감쇠 (Damping) - 20% 씩 목표값에 가까워짐
    const dampingFactor = 0.2;
    currentMouseX += (targetMouseX - currentMouseX) * dampingFactor;
    currentMouseY += (targetMouseY - currentMouseY) * dampingFactor;

    // Live2D 파라미터 업데이트
    if (model.internalModel) {
        try {
            // Cubism SDK의 파라미터 ID
            // 일반적인 파라미터: ParamAngleX, ParamAngleY, ParamBodyAngleX 등

            // 얼굴 각도 (좌우) - 범위 축소
            const angleXParam = model.internalModel.coreModel.getParameterIndex('ParamAngleX');
            if (angleXParam >= 0) {
                // -15 ~ 15도 범위로 매핑 (자연스러운 움직임)
                model.internalModel.coreModel.setParameterValueById(
                    'ParamAngleX',
                    currentMouseX * 15
                );
            }

            // 얼굴 각도 (상하) - Y축 반전 및 범위 조정
            const angleYParam = model.internalModel.coreModel.getParameterIndex('ParamAngleY');
            if (angleYParam >= 0) {
                // -15 ~ 15도 범위로 매핑, Y축 반전 (위쪽이 양수)
                model.internalModel.coreModel.setParameterValueById(
                    'ParamAngleY',
                    -currentMouseY * 15
                );
            }

            // 몸 각도 (좌우) - 더 작은 범위로 자연스럽게
            const bodyAngleXParam = model.internalModel.coreModel.getParameterIndex('ParamBodyAngleX');
            if (bodyAngleXParam >= 0) {
                // -5 ~ 5도 범위로 매핑 (얼굴보다 덜 움직임)
                model.internalModel.coreModel.setParameterValueById(
                    'ParamBodyAngleX',
                    currentMouseX * 5
                );
            }

            // 눈동자 위치 (있다면) - 범위 축소
            const eyeBallXParam = model.internalModel.coreModel.getParameterIndex('ParamEyeBallX');
            if (eyeBallXParam >= 0) {
                model.internalModel.coreModel.setParameterValueById(
                    'ParamEyeBallX',
                    currentMouseX * 0.8
                );
            }

            const eyeBallYParam = model.internalModel.coreModel.getParameterIndex('ParamEyeBallY');
            if (eyeBallYParam >= 0) {
                // Y축 반전
                model.internalModel.coreModel.setParameterValueById(
                    'ParamEyeBallY',
                    -currentMouseY * 0.8
                );
            }

        } catch (e) {
            // 파라미터가 없어도 에러 무시 (모델마다 다름)
        }
    }

    requestAnimationFrame(updateMouseTracking);
}

// 마우스 트래킹 시작
requestAnimationFrame(updateMouseTracking);
console.log("Mouse tracking initialized");

// ==========================================
// 표정 시스템
// ==========================================

// 표정 매핑
const EMOTIONS = {
    'angry': 'angry',
    'confused': 'confused',
    'dizzy': 'dizzy',
    'excited': 'excited',
    'joy': 'joy',
    'love': 'love',
    'pathetic': 'pathetic',
    'pervert': 'pervert',
    'sad': 'sad',
    'shy': 'shy',
    'smile': 'smile',
    'smug': 'smug',
    'sulk': 'sulk',
    'teary': 'teary'
};

/**
 * 표정 변경 함수
 * @param {string} emotion - 감정 이름
 */
// 현재 표정 애니메이션 상태
let currentExpressionAnimation = null;
// 이전 표정의 파라미터 ID 목록
let previousExpressionParams = [];

async function changeExpression(emotion) {
    const model = window.live2dModel;
    if (!model) {
        console.warn("Model not loaded, cannot change expression");
        return;
    }

    if (!EMOTIONS[emotion]) {
        console.warn(`Unknown emotion: ${emotion}`);
        return;
    }

    try {
        // 표정 파일 경로
        const expressionPath = `../live2d_models/jksalt/emotions/${EMOTIONS[emotion]}.exp3.json`;
        console.log(`Changing expression to: ${emotion} (${expressionPath})`);

        // Live2D 표정 적용
        if (model.internalModel && model.internalModel.coreModel) {
            // exp3.json 파일 로드
            const response = await fetch(expressionPath);
            const expressionData = await response.json();

            // 이전 애니메이션 취소
            if (currentExpressionAnimation) {
                cancelAnimationFrame(currentExpressionAnimation);
            }

            // 현재 파라미터 값 저장 및 목표값 설정
            const startValues = {};
            const targetValues = {};

            // 이전 표정의 파라미터를 0으로 리셋
            previousExpressionParams.forEach(paramId => {
                try {
                    const currentValue = model.internalModel.coreModel.getParameterValueById(paramId);
                    startValues[paramId] = currentValue;
                    targetValues[paramId] = 0; // 이전 표정 파라미터는 0으로
                } catch (e) {
                    // 파라미터가 없을 수 있음
                }
            });

            // 새 표정의 파라미터 설정
            const newExpressionParams = [];
            expressionData.Parameters.forEach(param => {
                try {
                    const currentValue = model.internalModel.coreModel.getParameterValueById(param.Id);
                    startValues[param.Id] = currentValue;
                    targetValues[param.Id] = param.Value;
                    newExpressionParams.push(param.Id);
                } catch (e) {
                    console.warn(`Failed to get parameter ${param.Id}:`, e);
                }
            });

            // 이전 표정 파라미터 목록 업데이트
            previousExpressionParams = newExpressionParams;

            // 애니메이션 설정
            const duration = 500; // 0.5초
            const startTime = Date.now();

            // 애니메이션 함수
            function animate() {
                const elapsed = Date.now() - startTime;
                const progress = Math.min(elapsed / duration, 1.0);

                // Ease-out 곡선 적용
                const eased = 1 - Math.pow(1 - progress, 3);

                // 모든 파라미터 보간 (이전 표정 리셋 + 새 표정 적용)
                Object.keys(targetValues).forEach(paramId => {
                    try {
                        const start = startValues[paramId] || 0;
                        const target = targetValues[paramId];
                        const value = start + (target - start) * eased;

                        model.internalModel.coreModel.setParameterValueById(
                            paramId,
                            value
                        );
                    } catch (e) {
                        // 무시
                    }
                });

                // 애니메이션 계속 또는 종료
                if (progress < 1.0) {
                    currentExpressionAnimation = requestAnimationFrame(animate);
                } else {
                    currentExpressionAnimation = null;
                    console.log(`Expression animation complete: ${emotion}`);
                }
            }

            // 애니메이션 시작
            animate();

            console.log(`Expression changing to: ${emotion}`);
        }
    } catch (error) {
        console.error(`Failed to load expression ${emotion}:`, error);
    }
}

// ==========================================
// 채팅 시스템
// ==========================================

const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const sendButton = document.getElementById('send-button');
const attachButton = document.getElementById('attach-button');
const imageInput = document.getElementById('image-input');
const imagePreviewContainer = document.getElementById('image-preview-container');
const loadingIndicator = document.getElementById('loading-indicator');

// 첨부된 이미지 경로 목록
let attachedImages = [];

/**
 * 로딩 인디케이터 표시/숨김
 * @param {boolean} show - true면 표시, false면 숨김
 */
function showLoadingIndicator(show) {
    if (loadingIndicator) {
        loadingIndicator.style.display = show ? 'flex' : 'none';
        // 로딩 표시 시 채팅창 스크롤
        if (show) {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    }
}

/**
 * 메시지를 채팅창에 추가
 * @param {string} text - 메시지 텍스트
 * @param {string} role - 'user' 또는 'assistant'
 * @param {Array} images - 이미지 URL 배열 (옵션)
 */
function addMessage(text, role, images = []) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';

    // 이미지가 있으면 먼저 표시
    if (images && images.length > 0) {
        const imagesDiv = document.createElement('div');
        imagesDiv.style.display = 'flex';
        imagesDiv.style.gap = '4px';
        imagesDiv.style.marginBottom = '8px';
        imagesDiv.style.flexWrap = 'wrap';

        images.forEach(imgSrc => {
            const img = document.createElement('img');
            img.src = imgSrc;
            img.style.maxWidth = '100px';
            img.style.maxHeight = '100px';
            img.style.borderRadius = '8px';
            img.style.objectFit = 'cover';
            imagesDiv.appendChild(img);
        });

        bubble.appendChild(imagesDiv);
    }

    // 텍스트 추가
    const textSpan = document.createElement('span');
    textSpan.textContent = text;
    bubble.appendChild(textSpan);

    messageDiv.appendChild(bubble);
    chatMessages.appendChild(messageDiv);

    // 스크롤을 맨 아래로
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

/**
 * 이미지 첨부 버튼 클릭
 */
attachButton.addEventListener('click', () => {
    imageInput.click();
});

/**
 * 이미지 선택 시
 */
imageInput.addEventListener('change', (e) => {
    const files = Array.from(e.target.files);

    files.forEach(file => {
        if (!file.type.startsWith('image/')) return;

        // 최대 5개 제한
        if (attachedImages.length >= 5) {
            alert('이미지는 최대 5개까지 첨부할 수 있어요.');
            return;
        }

        const reader = new FileReader();
        reader.onload = (event) => {
            const imageData = {
                dataUrl: event.target.result,
                name: file.name,
                type: file.type
            };

            attachedImages.push(imageData);
            updateImagePreview();
        };
        reader.readAsDataURL(file);
    });

    // 입력 초기화 (같은 파일 다시 선택 가능하게)
    imageInput.value = '';
});

/**
 * 이미지 미리보기 업데이트
 */
function updateImagePreview() {
    console.log("[Preview] Updating preview, images:", attachedImages.length);

    if (!imagePreviewContainer) {
        console.error("[Preview] imagePreviewContainer is null!");
        return;
    }

    imagePreviewContainer.innerHTML = '';

    attachedImages.forEach((img, index) => {
        console.log("[Preview] Adding image:", img.name);

        const item = document.createElement('div');
        item.className = 'image-preview-item';

        const imgEl = document.createElement('img');
        imgEl.src = img.dataUrl;

        const removeBtn = document.createElement('button');
        removeBtn.className = 'remove-btn';
        removeBtn.textContent = '×';
        removeBtn.onclick = () => {
            attachedImages.splice(index, 1);
            updateImagePreview();
        };

        item.appendChild(imgEl);
        item.appendChild(removeBtn);
        imagePreviewContainer.appendChild(item);
    });

    // 강제로 display 설정
    if (attachedImages.length > 0) {
        imagePreviewContainer.style.display = 'flex';
    } else {
        imagePreviewContainer.style.display = 'none';
    }

    console.log("[Preview] Preview container children:", imagePreviewContainer.children.length);
}


/**
 * 사용자 메시지 전송
 */
function sendMessage() {
    const message = chatInput.value.trim();

    if (!message && attachedImages.length === 0) return;

    // 사용자 메시지 표시 (이미지 포함)
    const imageUrls = attachedImages.map(img => img.dataUrl);
    addMessage(message || '(이미지)', 'user', imageUrls);

    // 입력창 초기화
    chatInput.value = '';

    // Python으로 메시지 전송
    if (window.pyBridge) {
        // 로딩 인디케이터 표시
        showLoadingIndicator(true);

        if (attachedImages.length > 0) {
            // 이미지와 함께 전송
            const imageDataList = JSON.stringify(attachedImages.map(img => ({
                dataUrl: img.dataUrl,
                name: img.name,
                type: img.type
            })));
            window.pyBridge.send_to_ai_with_images(message, imageDataList);
        } else {
            // 텍스트만 전송
            window.pyBridge.send_to_ai(message);
        }
    } else {
        console.error("Python bridge not connected");
        addMessage("연결 오류가 발생했어요.", 'assistant');
    }

    // 첨부 이미지 초기화
    attachedImages = [];
    updateImagePreview();
}

// 전송 버튼 클릭
sendButton.addEventListener('click', sendMessage);

// Enter 키로 전송
chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

/**
 * 붙여넣기(Ctrl+V) 이벤트 처리
 */
chatInput.addEventListener('paste', (e) => {
    const items = (e.clipboardData || e.originalEvent.clipboardData).items;

    let hasImage = false;

    for (const item of items) {
        if (item.type.indexOf('image') === 0) {
            hasImage = true;
            const blob = item.getAsFile();

            // 최대 개수 체크
            if (attachedImages.length >= 5) {
                alert('이미지는 최대 5개까지 첨부할 수 있어요.');
                return;
            }

            const reader = new FileReader();
            reader.onload = (event) => {
                const imageData = {
                    dataUrl: event.target.result,
                    name: "pasted_image.png", // 임의의 이름
                    type: item.type
                };

                attachedImages.push(imageData);
                updateImagePreview();
            };
            reader.readAsDataURL(blob);
        }
    }

    // 이미지가 있으면 붙여넣기 후에도 포커스 유지
    if (hasImage) {
        // 텍스트 붙여넣기도 동시에 될 수 있으므로 기본 동작은 막지 않음
        // (단, 이미지 파일만 있는 경우 텍스트 입력창에 이상한 문자열이 들어가는 건 막고 싶다면 preventDefault 고려)
    }
});

// ==========================================
// QWebChannel 브릿지 연결
// ==========================================

// QWebChannel 초기화
if (typeof QWebChannel !== 'undefined') {
    new QWebChannel(qt.webChannelTransport, function (channel) {
        window.pyBridge = channel.objects.bridge;
        console.log("QWebChannel bridge connected");

        // Python에서 메시지 수신
        window.pyBridge.message_received.connect(function (text, emotion) {
            console.log(`Received from Python: "${text}" [${emotion}]`);

            // 로딩 인디케이터 숨김
            showLoadingIndicator(false);

            // 메시지 표시
            addMessage(text, 'assistant');

            // 표정 변경
            changeExpression(emotion);
        });

        // 표정 변경 시그널 연결
        window.pyBridge.expression_changed.connect(function (emotion) {
            console.log(`Expression changed: ${emotion}`);
            changeExpression(emotion);
        });

        // 립싱크 시그널 연결
        if (window.pyBridge.lip_sync_update) {
            window.pyBridge.lip_sync_update.connect(function (mouthValue) {
                setMouthOpen(mouthValue);
            });
            console.log("Lip sync signal connected");
        }
    });
} else {
    console.warn("QWebChannel not available - running in standalone mode");
}

// ==========================================
// 립싱크 제어
// ==========================================

/**
 * Live2D 모델의 입 벌림 정도 설정
 * @param {number} value - 입 벌림 값 (0.0 ~ 1.0)
 */
function setMouthOpen(value) {
    const model = window.live2dModel;
    if (!model || !model.internalModel) {
        return;
    }

    try {
        // ParamMouthOpenY 파라미터 설정
        const core = model.internalModel.coreModel;
        if (core && typeof core.setParameterValueById === 'function') {
            core.setParameterValueById('ParamMouthOpenY', value);
        } else if (model.internalModel.setParameterValueById) {
            model.internalModel.setParameterValueById('ParamMouthOpenY', value);
        }
    } catch (e) {
        // 파라미터가 없을 수 있음 (모델마다 다름)
        // 첫 호출에만 경고
        if (!window._mouthOpenWarned) {
            console.warn("ParamMouthOpenY not available:", e);
            window._mouthOpenWarned = true;
        }
    }
}

// 전역으로 노출 (Python에서도 호출 가능하게)
window.setMouthOpen = setMouthOpen;

console.log("=== Chat and expression system initialized ===");
console.log("=== Lip sync system ready ===");
