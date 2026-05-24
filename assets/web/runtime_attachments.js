
function createAttachmentId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
        return window.crypto.randomUUID();
    }
    return `attachment-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function getFileExtension(name) {
    const normalized = String(name || '').trim();
    const index = normalized.lastIndexOf('.');
    if (index < 0) return '';
    return normalized.slice(index + 1).toLowerCase();
}

function inferMimeTypeFromName(name) {
    const extension = getFileExtension(name);
    if (extension === 'txt') return 'text/plain';
    if (extension === 'md') return 'text/markdown';
    if (extension === 'pdf') return 'application/pdf';
    if (extension === 'docx') return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    return 'application/octet-stream';
}

function classifyAttachment(fileLike) {
    const mimeType = String(fileLike?.type || '').toLowerCase();
    const extension = getFileExtension(fileLike?.name || '');
    if (mimeType.startsWith('image/')) return 'image';
    if (mimeType.startsWith('text/')) return 'document';
    if (extension && SUPPORTED_DOCUMENT_EXTENSIONS.has(extension)) return 'document';
    if (mimeType === 'application/pdf') return 'document';
    if (mimeType === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') return 'document';
    return '';
}

function formatAttachmentSubtitle(attachment) {
    if (attachment.category === 'image') {
        if (attachment.width > 0 && attachment.height > 0) {
            return `이미지 ${attachment.width}×${attachment.height}`;
        }
        return '이미지';
    }

    const extension = getFileExtension(attachment.name);
    if (extension === 'pdf') return 'PDF 문서';
    if (extension === 'docx') return 'DOCX 문서';
    if (extension === 'md') return '마크다운 문서';
    if (extension === 'txt') return '텍스트 문서';
    return '문서';
}

function formatAttachmentTokenText(attachment) {
    if (attachment.status === 'error') {
        return attachment.error || '분석에 실패했어요.';
    }
    if (typeof attachment.tokenEstimate === 'number' && attachment.tokenEstimate >= 0) {
        return `추정 ${attachment.tokenEstimate.toLocaleString('ko-KR')} 토큰`;
    }
    return '토큰 계산 중...';
}

function readFileAsDataUrl(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (event) => resolve(String(event?.target?.result || ''));
        reader.onerror = () => reject(reader.error || new Error('파일을 읽지 못했어요.'));
        reader.readAsDataURL(file);
    });
}

function requestAttachmentPreviewMetadata() {
    if (!window.pyBridge || !window.pyBridge.preview_attachments || attachedAttachments.length === 0) {
        return;
    }
    const payload = attachedAttachments.map((attachment) => ({
        id: attachment.id,
        name: attachment.name,
        type: attachment.type,
        dataUrl: attachment.dataUrl
    }));
    window.pyBridge.preview_attachments(JSON.stringify(payload));
}

function applyAttachmentPreviewMetadata(value) {
    let parsed = [];
    try {
        parsed = typeof value === 'string' ? JSON.parse(value) : value;
    } catch (error) {
        console.error('Failed to parse attachment preview payload', error);
        return;
    }

    if (!Array.isArray(parsed)) return;

    parsed.forEach((meta) => {
        const current = attachedAttachments.find((attachment) => attachment.id === meta.id);
        if (!current) return;
        current.category = meta.category || current.category;
        current.tokenEstimate = Number.isFinite(Number(meta.tokenEstimate)) ? Number(meta.tokenEstimate) : current.tokenEstimate;
        current.width = Number.isFinite(Number(meta.width)) ? Number(meta.width) : current.width;
        current.height = Number.isFinite(Number(meta.height)) ? Number(meta.height) : current.height;
        current.status = meta.status || current.status;
        current.error = meta.error || '';
        current.type = meta.type || current.type;
    });

    updateAttachmentPreview();
}
