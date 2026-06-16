// 이미지 아바타 렌더링 런타임.
const IMAGE_AVATAR_TTS_BOUNCE_PX = 10;
const DEFAULT_IMAGE_AVATAR_PLACEMENT = {
    scale: 1.0,
    xPercent: 50,
    yPercent: 50
};

const imageAvatarState = {
    active: false,
    config: {},
    imageAvatar: {},
    sprite: null,
    errorText: null,
    currentEmotion: 'normal',
    baseX: 0,
    baseY: 0,
    scale: 1.0,
    xPercent: 50,
    yPercent: 50,
    mouthValue: 0,
    bounceOffset: 0,
    boundErrorBaseTextures: new WeakSet()
};

function isImageAvatarMode() {
    const config = window.eneModelConfig || {};
    return String(config.avatarMode || 'live2d').trim().toLowerCase() === 'image';
}

function normalizeImageAvatarEmotion(emotion) {
    const normalized = String(emotion || '').trim().toLowerCase();
    if (normalized) {
        return normalized;
    }
    return 'normal';
}

function getImageAvatarImages() {
    const imageAvatar = imageAvatarState.imageAvatar || {};
    return imageAvatar.images && typeof imageAvatar.images === 'object'
        ? imageAvatar.images
        : {};
}

function getImageAvatarImageForEmotion(emotion) {
    const images = getImageAvatarImages();
    const normalizedEmotion = normalizeImageAvatarEmotion(emotion);
    return images[normalizedEmotion] || images.normal || null;
}

function getImageAvatarImagePath(imageInfo) {
    if (typeof imageInfo === 'string') {
        return imageInfo;
    }
    if (!imageInfo || typeof imageInfo !== 'object') {
        return '';
    }
    return String(imageInfo.path || imageInfo.url || imageInfo.src || '').trim();
}

function normalizeImageAvatarNumber(value, fallback) {
    const numericValue = Number(value);
    return Number.isFinite(numericValue) ? numericValue : fallback;
}

function getImageAvatarPlacementForImage(imageInfo) {
    const imageAvatar = imageAvatarState.imageAvatar || {};
    const placement = (
        imageInfo && typeof imageInfo === 'object' && imageInfo.placement
            ? imageInfo.placement
            : imageAvatar.placement
    ) || DEFAULT_IMAGE_AVATAR_PLACEMENT;

    return {
        scale: normalizeImageAvatarNumber(placement.scale, DEFAULT_IMAGE_AVATAR_PLACEMENT.scale),
        xPercent: normalizeImageAvatarNumber(placement.xPercent, DEFAULT_IMAGE_AVATAR_PLACEMENT.xPercent),
        yPercent: normalizeImageAvatarNumber(placement.yPercent, DEFAULT_IMAGE_AVATAR_PLACEMENT.yPercent)
    };
}

function removeImageAvatarErrorText() {
    if (!imageAvatarState.errorText) {
        return;
    }
    app.stage.removeChild(imageAvatarState.errorText);
    if (typeof imageAvatarState.errorText.destroy === 'function') {
        imageAvatarState.errorText.destroy();
    }
    imageAvatarState.errorText = null;
}

function showImageAvatarError(message) {
    removeImageAvatarErrorText();
    console.warn(message);
    if (typeof PIXI === 'undefined' || !PIXI.Text) {
        return;
    }
    const errorText = new PIXI.Text(message, {
        fontFamily: 'Arial',
        fontSize: 14,
        fill: 0xff0000,
        align: 'center',
        wordWrap: true,
        wordWrapWidth: window.innerWidth - 40
    });
    errorText.x = window.innerWidth / 2;
    errorText.y = window.innerHeight / 2;
    if (errorText.anchor && typeof errorText.anchor.set === 'function') {
        errorText.anchor.set(0.5);
    }
    app.stage.addChild(errorText);
    imageAvatarState.errorText = errorText;
}

function handleImageAvatarTextureError(texture, imagePath, error) {
    if (!imageAvatarState.sprite || imageAvatarState.sprite.texture !== texture) {
        console.warn(`Stale image avatar texture failed to load: ${imagePath}`, error);
        return;
    }
    removeImageAvatarArtifacts();
    const reason = error && error.message ? error.message : String(error || 'unknown');
    showImageAvatarError(`이미지 아바타 로드 실패\n\n경로: ${imagePath}\n에러: ${reason}`);
}

function bindImageAvatarTextureError(texture, imagePath) {
    const baseTexture = texture && texture.baseTexture;
    if (!baseTexture) {
        return false;
    }
    if (imageAvatarState.boundErrorBaseTextures.has(baseTexture)) {
        return false;
    }
    const onError = (error) => handleImageAvatarTextureError(texture, imagePath, error);
    if (typeof baseTexture.once === 'function') {
        baseTexture.once('error', onError);
        imageAvatarState.boundErrorBaseTextures.add(baseTexture);
        return true;
    }
    if (typeof baseTexture.on === 'function') {
        baseTexture.on('error', onError);
        imageAvatarState.boundErrorBaseTextures.add(baseTexture);
        return true;
    }
    return false;
}

function applyImageAvatarPlacement(imageInfo = getImageAvatarImageForEmotion(imageAvatarState.currentEmotion)) {
    const sprite = imageAvatarState.sprite;
    if (!sprite) {
        return;
    }

    const placement = getImageAvatarPlacementForImage(imageInfo);
    imageAvatarState.scale = placement.scale;
    imageAvatarState.xPercent = placement.xPercent;
    imageAvatarState.yPercent = placement.yPercent;
    imageAvatarState.baseX = window.innerWidth * (placement.xPercent / 100);
    imageAvatarState.baseY = window.innerHeight * (placement.yPercent / 100);

    if (sprite.anchor && typeof sprite.anchor.set === 'function') {
        sprite.anchor.set(0.5, 0.5);
    }
    if (sprite.scale && typeof sprite.scale.set === 'function') {
        sprite.scale.set(placement.scale);
    }
    sprite.x = imageAvatarState.baseX;
    sprite.y = imageAvatarState.baseY + imageAvatarState.bounceOffset;
}

function renderImageAvatarEmotion(emotion) {
    const resolvedEmotion = normalizeImageAvatarEmotion(emotion);
    const imageInfo = getImageAvatarImageForEmotion(resolvedEmotion);
    const imagePath = getImageAvatarImagePath(imageInfo);

    imageAvatarState.currentEmotion = imagePath ? resolvedEmotion : 'normal';

    if (!imagePath) {
        removeImageAvatarArtifacts();
        showImageAvatarError('이미지 아바타 이미지를 찾지 못했습니다. normal 이미지를 확인해 주세요.');
        return false;
    }

    try {
        removeImageAvatarErrorText();
        const texture = PIXI.Texture.from(imagePath);
        if (!imageAvatarState.sprite) {
            imageAvatarState.sprite = new PIXI.Sprite(texture);
            app.stage.addChild(imageAvatarState.sprite);
        } else {
            imageAvatarState.sprite.texture = texture;
        }
        bindImageAvatarTextureError(texture, imagePath);
        applyImageAvatarPlacement(imageInfo);
        return true;
    } catch (error) {
        removeImageAvatarArtifacts();
        showImageAvatarError(`이미지 아바타 로드 실패: ${error.message || error}`);
        return false;
    }
}

function applyImageAvatarSettings(config) {
    window.eneModelConfig = { ...(window.eneModelConfig || {}), ...(config || {}) };
    imageAvatarState.config = window.eneModelConfig;
    imageAvatarState.imageAvatar = window.eneModelConfig.imageAvatar || {};
    imageAvatarState.active = isImageAvatarMode();

    if (typeof syncAvailableEmotionsFromConfig === 'function') {
        syncAvailableEmotionsFromConfig();
    }

    if (!imageAvatarState.active) {
        removeImageAvatarArtifacts();
        return false;
    }

    const emotion = imageAvatarState.currentEmotion || 'normal';
    return renderImageAvatarEmotion(emotion);
}

function changeImageAvatarEmotion(emotion) {
    if (!imageAvatarState.active && !isImageAvatarMode()) {
        return false;
    }
    return renderImageAvatarEmotion(emotion);
}

function applyImageAvatarMouthValue(value) {
    const clampedMouthValue = Math.max(0, Math.min(1, normalizeImageAvatarNumber(value, 0)));
    imageAvatarState.mouthValue = clampedMouthValue;
    imageAvatarState.bounceOffset = -clampedMouthValue * IMAGE_AVATAR_TTS_BOUNCE_PX;
    if (imageAvatarState.sprite) {
        imageAvatarState.sprite.y = imageAvatarState.baseY + imageAvatarState.bounceOffset;
    }
}

function removeImageAvatarArtifacts() {
    if (imageAvatarState.sprite) {
        app.stage.removeChild(imageAvatarState.sprite);
        if (typeof imageAvatarState.sprite.destroy === 'function') {
            imageAvatarState.sprite.destroy();
        }
        imageAvatarState.sprite = null;
    }
    removeImageAvatarErrorText();
    imageAvatarState.active = false;
    imageAvatarState.mouthValue = 0;
    imageAvatarState.bounceOffset = 0;
}

window.imageAvatarState = imageAvatarState;
window.isImageAvatarMode = isImageAvatarMode;
window.applyImageAvatarSettings = applyImageAvatarSettings;
window.changeImageAvatarEmotion = changeImageAvatarEmotion;
window.applyImageAvatarMouthValue = applyImageAvatarMouthValue;
window.removeImageAvatarArtifacts = removeImageAvatarArtifacts;
window.applyImageAvatarPlacement = applyImageAvatarPlacement;
window.getImageAvatarImageForEmotion = getImageAvatarImageForEmotion;
