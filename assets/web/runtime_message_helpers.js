
// 수동 요약 확인 모달을 연다.
const summaryReviewTopicHints = document.getElementById('summary-review-topic-hints');
const SUMMARY_REVIEW_TOPIC_HINT_FIELDS = [
    'keyword',
    'subject',
    'type',
    'state',
    'text',
    'aliases',
    'retrieval_terms',
    'confidence'
];

function showSummaryConfirm() {
    if (!summaryConfirmOverlay) return;
    summaryConfirmOverlay.classList.remove('hidden');
}

// 수동 요약 확인 모달을 닫는다.
function hideSummaryConfirm() {
    if (!summaryConfirmOverlay) return;
    summaryConfirmOverlay.classList.add('hidden');
}

function normalizeSummaryReviewPayload(payload) {
    let data = payload;
    if (typeof payload === 'string') {
        try {
            data = JSON.parse(payload);
        } catch (error) {
            data = {};
        }
    }
    if (!data || typeof data !== 'object') {
        data = {};
    }
    const meta = data.memory_meta && typeof data.memory_meta === 'object' ? data.memory_meta : {};
    return {
        summary: String(data.summary || ''),
        user_facts: Array.isArray(data.user_facts) ? data.user_facts.map(String) : [],
        ene_facts: Array.isArray(data.ene_facts) ? data.ene_facts.map(String) : [],
        topic_hints: Array.isArray(data.topic_hints) ? data.topic_hints : [],
        memory_meta: Object.assign({}, meta, {
            memory_type: String(meta.memory_type || 'general'),
            importance_reason: String(meta.importance_reason || 'none'),
            confidence: Number.isFinite(Number(meta.confidence)) ? Number(meta.confidence) : 0.5,
            entity_names: Array.isArray(meta.entity_names) ? meta.entity_names.map(String) : []
        })
    };
}

function ensureSummaryReviewSelectOption(select, value) {
    if (!select || !value) return;
    const normalized = String(value);
    const exists = Array.from(select.options).some((option) => option.value === normalized);
    if (exists) return;
    const option = document.createElement('option');
    option.value = normalized;
    option.textContent = normalized;
    select.appendChild(option);
}

function appendSummaryReviewFact(container, fact, groupName) {
    if (!container) return;
    const row = document.createElement('label');
    row.className = 'summary-review-fact';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = true;
    checkbox.name = groupName;
    const text = document.createElement('textarea');
    text.className = 'summary-review-fact-input';
    text.rows = 2;
    text.value = String(fact || '');
    row.appendChild(checkbox);
    row.appendChild(text);
    container.appendChild(row);
    text.focus();
}

function renderSummaryReviewFacts(container, facts, groupName) {
    if (!container) return;
    container.innerHTML = '';
    if (!facts || facts.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'summary-review-empty';
        empty.textContent = '없음';
        container.appendChild(empty);
        return;
    }

    facts.forEach((fact, index) => {
        const row = document.createElement('label');
        row.className = 'summary-review-fact';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = true;
        checkbox.name = groupName;
        checkbox.value = String(index);
        const text = document.createElement('textarea');
        text.className = 'summary-review-fact-input';
        text.rows = 2;
        text.value = fact;
        row.appendChild(checkbox);
        row.appendChild(text);
        container.appendChild(row);
    });
}

function formatSummaryReviewTopicList(value) {
    if (Array.isArray(value)) {
        return value.map((item) => String(item || '').trim()).filter(Boolean).join(', ');
    }
    return String(value || '');
}

function formatSummaryReviewTopicScalar(value) {
    return value === null || value === undefined ? '' : String(value);
}

function parseSummaryReviewTopicList(value) {
    return String(value || '')
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean);
}

function appendSummaryReviewTopicField(grid, fieldName, value) {
    const label = document.createElement('label');
    label.className = 'summary-review-field summary-review-topic-field';
    const name = document.createElement('span');
    name.textContent = fieldName;
    const input = fieldName === 'text' ? document.createElement('textarea') : document.createElement('input');
    input.className = 'summary-review-topic-input';
    input.dataset.topicField = fieldName;
    if (fieldName === 'confidence') {
        input.type = 'number';
        input.min = '0';
        input.max = '1';
        input.step = '0.01';
    } else if (fieldName !== 'text') {
        input.type = 'text';
    }
    if (fieldName === 'text') {
        input.rows = 2;
    }
    input.value = fieldName === 'aliases' || fieldName === 'retrieval_terms'
        ? formatSummaryReviewTopicList(value)
        : formatSummaryReviewTopicScalar(value);
    label.appendChild(name);
    label.appendChild(input);
    grid.appendChild(label);
}

function renderSummaryReviewTopicHints(container, topicHints) {
    if (!container) return;
    container.innerHTML = '';
    if (!Array.isArray(topicHints) || topicHints.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'summary-review-empty';
        empty.textContent = '없음';
        container.appendChild(empty);
        return;
    }

    topicHints.forEach((hint, index) => {
        const normalizedHint = hint && typeof hint === 'object' ? hint : {};
        const card = document.createElement('div');
        card.className = 'summary-review-topic-hint';
        card.dataset.topicHintIndex = String(index);
        const header = document.createElement('div');
        header.className = 'summary-review-topic-hint-header';
        const title = document.createElement('div');
        title.className = 'summary-review-topic-hint-title';
        title.textContent = `#${index + 1}`;
        const deleteButton = document.createElement('button');
        deleteButton.type = 'button';
        deleteButton.className = 'summary-review-topic-hint-delete';
        deleteButton.textContent = '삭제';
        deleteButton.addEventListener('click', () => {
            card.remove();
            if (container.querySelectorAll('.summary-review-topic-hint').length === 0) {
                renderSummaryReviewTopicHints(container, []);
            }
        });
        header.appendChild(title);
        header.appendChild(deleteButton);
        const grid = document.createElement('div');
        grid.className = 'summary-review-topic-grid';
        SUMMARY_REVIEW_TOPIC_HINT_FIELDS.forEach((fieldName) => {
            appendSummaryReviewTopicField(grid, fieldName, normalizedHint[fieldName]);
        });
        card.appendChild(header);
        card.appendChild(grid);
        container.appendChild(card);
    });
}

function readSummaryReviewTopicField(row, fieldName) {
    const input = row.querySelector(`[data-topic-field="${fieldName}"]`);
    return String(input ? input.value : '').trim();
}

function collectSummaryReviewTopicHints(container) {
    if (!container) return [];
    return Array.from(container.querySelectorAll('.summary-review-topic-hint'))
        .map((row) => {
            const index = Number(row.dataset.topicHintIndex);
            const original = currentSummaryReviewPayload
                && Array.isArray(currentSummaryReviewPayload.topic_hints)
                && Number.isInteger(index)
                && currentSummaryReviewPayload.topic_hints[index]
                && typeof currentSummaryReviewPayload.topic_hints[index] === 'object'
                ? currentSummaryReviewPayload.topic_hints[index]
                : {};
            const confidenceText = readSummaryReviewTopicField(row, 'confidence');
            const confidenceValue = confidenceText ? Number(confidenceText) : NaN;
            const originalConfidence = Number(original.confidence);
            const confidence = Number.isFinite(confidenceValue)
                ? Math.max(0, Math.min(1, confidenceValue))
                : (Number.isFinite(originalConfidence) ? Math.max(0, Math.min(1, originalConfidence)) : 0.5);
            return Object.assign({}, original, {
                keyword: readSummaryReviewTopicField(row, 'keyword'),
                subject: readSummaryReviewTopicField(row, 'subject'),
                type: readSummaryReviewTopicField(row, 'type'),
                state: readSummaryReviewTopicField(row, 'state'),
                text: readSummaryReviewTopicField(row, 'text'),
                aliases: parseSummaryReviewTopicList(readSummaryReviewTopicField(row, 'aliases')),
                retrieval_terms: parseSummaryReviewTopicList(readSummaryReviewTopicField(row, 'retrieval_terms')),
                confidence
            });
        });
}

function showSummaryReview(payload) {
    if (!summaryReviewOverlay) return;
    currentSummaryReviewPayload = normalizeSummaryReviewPayload(payload);
    if (summaryReviewTextarea) summaryReviewTextarea.value = currentSummaryReviewPayload.summary;
    ensureSummaryReviewSelectOption(summaryReviewMemoryType, currentSummaryReviewPayload.memory_meta.memory_type);
    ensureSummaryReviewSelectOption(summaryReviewImportanceReason, currentSummaryReviewPayload.memory_meta.importance_reason);
    if (summaryReviewMemoryType) summaryReviewMemoryType.value = currentSummaryReviewPayload.memory_meta.memory_type;
    if (summaryReviewImportanceReason) summaryReviewImportanceReason.value = currentSummaryReviewPayload.memory_meta.importance_reason;
    if (summaryReviewConfidence) summaryReviewConfidence.value = String(currentSummaryReviewPayload.memory_meta.confidence);
    if (summaryReviewEntities) summaryReviewEntities.value = currentSummaryReviewPayload.memory_meta.entity_names.join(', ');
    renderSummaryReviewFacts(summaryReviewUserFacts, currentSummaryReviewPayload.user_facts, 'summary-user-fact');
    renderSummaryReviewFacts(summaryReviewEneFacts, currentSummaryReviewPayload.ene_facts, 'summary-ene-fact');
    renderSummaryReviewTopicHints(summaryReviewTopicHints, currentSummaryReviewPayload.topic_hints);
    summaryReviewOverlay.classList.remove('hidden');
    setSummaryReviewBusy(false);
    if (summaryReviewTextarea) {
        summaryReviewTextarea.focus();
    }
}

function hideSummaryReview() {
    if (!summaryReviewOverlay) return;
    summaryReviewOverlay.classList.add('hidden');
    currentSummaryReviewPayload = null;
    setSummaryReviewBusy(false);
}

function setSummaryReviewBusy(active) {
    summaryReviewBusy = Boolean(active);
    if (!summaryReviewOverlay) return;
    const controls = summaryReviewOverlay.querySelectorAll('textarea, input, select, button');
    controls.forEach((control) => {
        control.disabled = summaryReviewBusy;
    });
}

function collectCheckedSummaryFacts(container) {
    if (!container) return [];
    return Array.from(container.querySelectorAll('.summary-review-fact'))
        .filter((row) => {
            const checkbox = row.querySelector('input[type="checkbox"]');
            return checkbox && checkbox.checked;
        })
        .map((row) => {
            const input = row.querySelector('.summary-review-fact-input');
            return String(input ? input.value : '').trim();
        })
        .filter(Boolean);
}

function collectSummaryReviewPayload() {
    const confidenceValue = Number(summaryReviewConfidence ? summaryReviewConfidence.value : 0.5);
    const confidence = Number.isFinite(confidenceValue) ? Math.max(0, Math.min(1, confidenceValue)) : 0.5;
    const entityNames = String(summaryReviewEntities ? summaryReviewEntities.value : '')
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean);
    const previousMeta = currentSummaryReviewPayload && currentSummaryReviewPayload.memory_meta
        ? currentSummaryReviewPayload.memory_meta
        : {};
    return {
        summary: String(summaryReviewTextarea ? summaryReviewTextarea.value : '').trim(),
        user_facts: collectCheckedSummaryFacts(summaryReviewUserFacts),
        ene_facts: collectCheckedSummaryFacts(summaryReviewEneFacts),
        memory_meta: Object.assign({}, previousMeta, {
            memory_type: String(summaryReviewMemoryType ? summaryReviewMemoryType.value : 'general'),
            importance_reason: String(summaryReviewImportanceReason ? summaryReviewImportanceReason.value : 'none'),
            confidence,
            entity_names: entityNames
        }),
        topic_hints: collectSummaryReviewTopicHints(summaryReviewTopicHints)
    };
}

function showAttachmentDeleteConfirm() {
    if (!attachmentDeleteConfirmOverlay) return;
    if (attachmentDeleteConfirmBody) {
        attachmentDeleteConfirmBody.textContent = ATTACHMENT_DELETE_CONFIRM_BODY;
    }
    attachmentDeleteConfirmOverlay.classList.remove('hidden');
}

function hideAttachmentDeleteConfirm() {
    if (!attachmentDeleteConfirmOverlay) return;
    attachmentDeleteConfirmOverlay.classList.add('hidden');
    pendingAttachmentDeletion = null;
}

function requestAttachmentDeletion(messageDiv, attachmentId) {
    if (!messageDiv || !attachmentId) return;
    pendingAttachmentDeletion = {
        messageDiv,
        attachmentId
    };
    showAttachmentDeleteConfirm();
}

function confirmAttachmentDeletion() {
    if (!pendingAttachmentDeletion) {
        hideAttachmentDeleteConfirm();
        return;
    }

    const { messageDiv, attachmentId } = pendingAttachmentDeletion;
    const attachments = normalizeMessageAttachments(getMessageVisualAttachments(messageDiv));
    const nextAttachments = attachments.map((attachment) => {
        if (attachment.id !== attachmentId) {
            return attachment;
        }
        return {
            ...attachment,
            deleted: true,
            dataUrl: ''
        };
    });

    messageDiv._messageAttachments = nextAttachments;
    renderMessageBubbleSegments(messageDiv, getMessageLogicalText(messageDiv), {
        attachments: nextAttachments,
        immediate: true
    });

    const messageId = getStoredMessageId(messageDiv);
    hideAttachmentDeleteConfirm();

    if (window.pyBridge && window.pyBridge.delete_message_attachment && messageId) {
        dispatchBridgeCall(() => {
            window.pyBridge.delete_message_attachment(messageId, attachmentId);
        }, (error) => {
            console.error('Python bridge attachment delete failed', error);
        });
    }
}

function openImageLightbox(imageUrl, imageName = '') {
    if (!imageLightboxOverlay || !imageLightboxImage || !imageUrl) return;
    imageLightboxImage.src = imageUrl;
    imageLightboxImage.alt = imageName || '확대된 이미지';
    imageLightboxOverlay.classList.remove('hidden');
}

function closeImageLightbox() {
    if (!imageLightboxOverlay || !imageLightboxImage) return;
    imageLightboxOverlay.classList.add('hidden');
    imageLightboxImage.removeAttribute('src');
}

// 토스트 메시지를 생성해 일정 시간 후 자동 제거한다.
function showToast(message, level = 'info') {
    if (!toastContainer || !message) return;
    const toast = document.createElement('div');
    toast.className = `toast-item toast-${level}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(-4px)';
        toast.style.transition = 'opacity 0.16s ease, transform 0.16s ease';
        setTimeout(() => toast.remove(), 180);
    }, 2200);
}
window.showToast = showToast;

function normalizeLogicalMessageText(text) {
    return String(text || '').replace(/\r\n?/g, '\n');
}

function setMessageLogicalText(messageDiv, text) {
    if (!messageDiv) return '';
    const normalizedText = normalizeLogicalMessageText(text);
    messageDiv.dataset.logicalMessageText = normalizedText;
    return normalizedText;
}

function getMessageLogicalText(messageDiv) {
    if (!messageDiv) return '';
    return normalizeLogicalMessageText(messageDiv.dataset.logicalMessageText || '');
}

function normalizeMessageThoughtText(thought) {
    return String(thought || '').replace(/\r\n?/g, '\n').trim();
}

function setMessageThoughtText(messageDiv, thought) {
    if (!messageDiv) return '';
    const normalizedThought = normalizeMessageThoughtText(thought);
    messageDiv.dataset.messageThought = normalizedThought;
    return normalizedThought;
}

function getMessageThoughtText(messageDiv) {
    if (!messageDiv) return '';
    return normalizeMessageThoughtText(messageDiv.dataset.messageThought || '');
}

function getMessageThoughtBody(messageDiv) {
    return messageDiv ? messageDiv.querySelector('.message-thought-body') : null;
}

function toggleMessageThought(messageDiv) {
    const body = getMessageThoughtBody(messageDiv);
    if (!body) {
        return;
    }
    const shouldExpand = body.hidden;
    body.hidden = !shouldExpand;
    const button = messageDiv.querySelector('.message-thought-btn');
    if (button) {
        button.classList.toggle('is-active', shouldExpand);
        button.setAttribute('aria-expanded', String(shouldExpand));
        button.title = shouldExpand ? currentUiStrings.thoughts.hide : currentUiStrings.thoughts.show;
        button.setAttribute('aria-label', shouldExpand ? currentUiStrings.thoughts.hide : currentUiStrings.thoughts.show);
    }
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function createMessageThoughtButton(messageDiv) {
    const normalizedThought = getMessageThoughtText(messageDiv);
    if (!thoughtFeatureEnabled || !normalizedThought) {
        return null;
    }

    const body = getMessageThoughtBody(messageDiv);
    const isExpanded = Boolean(body && !body.hidden);
    const btn = document.createElement('button');
    btn.className = 'message-thought-btn';
    btn.type = 'button';
    btn.innerHTML = createLucideIcon('sparkles');
    btn.title = isExpanded ? currentUiStrings.thoughts.hide : currentUiStrings.thoughts.show;
    btn.setAttribute('aria-label', isExpanded ? currentUiStrings.thoughts.hide : currentUiStrings.thoughts.show);
    btn.setAttribute('aria-expanded', String(isExpanded));
    btn.classList.toggle('is-active', isExpanded);
    btn.addEventListener('click', () => toggleMessageThought(messageDiv));
    return btn;
}

function updateMessageThoughtButtons() {
    if (!chatMessages) {
        return;
    }

    chatMessages.querySelectorAll('.message-thought-btn').forEach((button) => button.remove());
    if (!thoughtFeatureEnabled) {
        return;
    }

    chatMessages.querySelectorAll('.message.assistant').forEach((messageDiv) => {
        const thoughtButton = createMessageThoughtButton(messageDiv);
        if (!thoughtButton) {
            return;
        }
        const assistantRail = ensureMessageMetaRail(
            messageDiv,
            'assistant',
            messageDiv.dataset.messageTimestamp,
        );
        if (!assistantRail) {
            return;
        }
        const rerollAnchor = assistantRail.querySelector('.message-reroll-btn');
        assistantRail.insertBefore(thoughtButton, rerollAnchor);
    });
}

function getMessageBubbleStack(messageDiv) {
    if (!messageDiv) return null;
    let stack = messageDiv.querySelector('.message-bubble-stack');
    if (!stack) {
        stack = document.createElement('div');
        stack.className = 'message-bubble-stack';
    }
    return stack;
}

function normalizeMessageAttachments(attachments) {
    if (!attachments || attachments.length === 0) {
        return [];
    }
    return attachments.map((attachment) => {
        if (typeof attachment === 'string') {
            return { id: createAttachmentId(), category: 'image', name: '이미지', dataUrl: attachment, deleted: false };
        }
        return {
            ...attachment,
            id: attachment && attachment.id ? attachment.id : createAttachmentId(),
            deleted: Boolean(attachment && attachment.deleted),
        };
    });
}

function getMessageVisualAttachments(messageDiv) {
    if (!messageDiv || !Array.isArray(messageDiv._messageAttachments)) {
        return [];
    }
    return messageDiv._messageAttachments;
}

function getStoredMessageId(messageDiv) {
    if (!messageDiv || !messageDiv.dataset) return '';
    return String(messageDiv.dataset.messageId || '').trim();
}

function splitLongMessageLineBySentence(line) {
    const normalizedLine = String(line || '').trim();
    if (!normalizedLine || normalizedLine.length < MESSAGE_VISUAL_SENTENCE_SPLIT_MIN_LENGTH) {
        return [normalizedLine].filter(Boolean);
    }

    const sentenceMatches = normalizedLine.match(/[^.!?。！？]+(?:[.!?。！？]+["')\]]*\s*|$)/g);
    if (!sentenceMatches || sentenceMatches.length <= 1) {
        return [normalizedLine];
    }

    return sentenceMatches
        .map((sentence) => sentence.trim())
        .filter(Boolean);
}

function splitMessageIntoVisualChunks(text) {
    const normalizedText = normalizeLogicalMessageText(text);
    if (!messageSplitEnabled) {
        return normalizedText ? [normalizedText] : [];
    }
    const rawLines = normalizedText.split('\n');
    const chunks = [];

    rawLines.forEach((line) => {
        const trimmedLine = line.trim();
        if (!trimmedLine) {
            return;
        }

        splitLongMessageLineBySentence(trimmedLine).forEach((segment) => {
            if (segment) {
                chunks.push(segment);
            }
        });
    });

    if (chunks.length > 0) {
        return chunks;
    }

    return normalizedText.trim() ? [normalizedText.trim()] : [];
}

function createMessageAttachmentImageBubble(messageDiv, attachment) {
    const bubble = document.createElement('div');
    bubble.className = 'message-bubble message-attachment-image';

    const mediaButton = document.createElement('button');
    mediaButton.className = 'message-attachment-media';
    mediaButton.type = 'button';
    mediaButton.setAttribute('aria-label', `${attachment.name || '첨부 이미지'} 확대 보기`);
    mediaButton.addEventListener('click', () => {
        openImageLightbox(attachment.dataUrl, attachment.name || '첨부 이미지');
    });

    const img = document.createElement('img');
    img.src = attachment.dataUrl;
    img.alt = attachment.name || '첨부 이미지';
    mediaButton.appendChild(img);

    const caption = document.createElement('div');
    caption.className = 'message-attachment-caption';
    caption.textContent = attachment.name || '이미지';

    if (messageDiv && messageDiv.classList.contains('user')) {
        const removeBtn = document.createElement('button');
        removeBtn.className = 'message-attachment-delete-btn';
        removeBtn.type = 'button';
        removeBtn.textContent = '×';
        removeBtn.setAttribute('aria-label', '사진 삭제');
        removeBtn.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            requestAttachmentDeletion(messageDiv, attachment.id);
        });
        mediaButton.appendChild(removeBtn);
    }

    bubble.appendChild(mediaButton);
    bubble.appendChild(caption);
    return bubble;
}

function createMessageAttachmentDeletedBubble() {
    const bubble = document.createElement('div');
    bubble.className = 'message-bubble message-attachment-deleted';
    bubble.textContent = '[사진이 삭제되었습니다.]';
    return bubble;
}

function createMessageAttachmentFileBubble(attachment) {
    const bubble = document.createElement('div');
    bubble.className = 'message-bubble message-attachment-file';

    const extensionBadge = document.createElement('span');
    extensionBadge.className = 'message-attachment-file-badge';
    extensionBadge.textContent = getFileExtension(attachment.name || 'file').toUpperCase() || 'FILE';
    bubble.appendChild(extensionBadge);

    const label = document.createElement('span');
    label.textContent = attachment.name || '첨부 파일';
    bubble.appendChild(label);

    return bubble;
}

function createMessageAttachmentBubbles(messageDiv, attachments) {
    const normalizedAttachments = normalizeMessageAttachments(attachments);
    if (normalizedAttachments.length === 0) {
        return [];
    }

    return normalizedAttachments.map((attachment) => {
        if (attachment.category === 'image' && attachment.deleted) {
            return createMessageAttachmentDeletedBubble();
        }
        if (attachment.category === 'image' && attachment.dataUrl) {
            return createMessageAttachmentImageBubble(messageDiv, attachment);
        }
        return createMessageAttachmentFileBubble(attachment);
    });
}
