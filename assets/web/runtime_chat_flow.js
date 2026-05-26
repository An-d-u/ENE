
// UI가 먼저 그려진 뒤 Python 브리지 호출이 실행되도록 한 프레임 뒤로 넘긴다.
function dispatchBridgeCall(task, onError) {
    const scheduleFrame = window.requestAnimationFrame
        ? window.requestAnimationFrame.bind(window)
        : (callback) => window.setTimeout(callback, 16);

    scheduleFrame(() => {
        window.setTimeout(() => {
            try {
                task();
            } catch (error) {
                if (typeof onError === 'function') {
                    onError(error);
                    return;
                }
                throw error;
            }
        }, 0);
    });
}

/**
 * 첨부 선택 창 열기.
 */
attachButton.addEventListener('click', () => {
    imageInput.click();
});

/**
 * 선택한 첨부 파일을 읽어 미리보기 목록에 추가한다.
 */
imageInput.addEventListener('change', async (e) => {
    const files = Array.from(e.target.files);

    for (const file of files) {
        const category = classifyAttachment(file);
        if (!category) {
            alert('현재는 이미지, TXT, MD, PDF, DOCX 파일만 첨부할 수 있어요.');
            continue;
        }
        if (attachedAttachments.length >= MAX_ATTACHMENT_COUNT) {
            alert('첨부 파일은 최대 5개까지 첨부할 수 있어요.');
            break;
        }

        try {
            const dataUrl = await readFileAsDataUrl(file);
            const attachment = {
                id: createAttachmentId(),
                dataUrl,
                name: file.name,
                type: file.type || inferMimeTypeFromName(file.name),
                category,
                tokenEstimate: null,
                width: 0,
                height: 0,
                status: 'pending',
                error: ''
            };

            attachedAttachments.push(attachment);
            updateAttachmentPreview();
            requestAttachmentPreviewMetadata();
        } catch (error) {
            console.error('Failed to read attachment', error);
            alert(`첨부 파일을 읽는 중 문제가 생겼어요: ${file.name}`);
        }
    }
    imageInput.value = '';
});

/**
 * 첨부 미리보기 영역을 다시 렌더링한다.
 */
// 첨부한 이미지/문서 프리뷰 목록을 다시 그린다.
function updateAttachmentPreview() {
    console.log("[Preview] Updating preview, attachments:", attachedAttachments.length);

    if (!imagePreviewContainer) {
        console.error("[Preview] imagePreviewContainer is null!");
        return;
    }

    imagePreviewContainer.innerHTML = '';

    attachedAttachments.forEach((attachment, index) => {
        console.log("[Preview] Adding attachment:", attachment.name);

        const item = document.createElement('div');
        item.className = 'attachment-preview-item';

        if (attachment.category === 'image') {
            const imgEl = document.createElement('img');
            imgEl.className = 'attachment-preview-thumb';
            imgEl.src = attachment.dataUrl;
            item.appendChild(imgEl);
        } else {
            const docEl = document.createElement('div');
            docEl.className = 'attachment-preview-doc';
            docEl.textContent = getFileExtension(attachment.name).toUpperCase() || 'FILE';
            item.appendChild(docEl);
        }

        const meta = document.createElement('div');
        meta.className = 'attachment-preview-meta';

        const nameEl = document.createElement('div');
        nameEl.className = 'attachment-preview-name';
        nameEl.textContent = attachment.name;

        const subtitleEl = document.createElement('div');
        subtitleEl.className = 'attachment-preview-subtitle';
        subtitleEl.textContent = formatAttachmentSubtitle(attachment);

        const tokenEl = document.createElement('div');
        tokenEl.className = 'attachment-preview-token';
        if (attachment.status === 'error') {
            tokenEl.classList.add('is-error');
        }
        tokenEl.textContent = formatAttachmentTokenText(attachment);

        meta.appendChild(nameEl);
        meta.appendChild(subtitleEl);
        meta.appendChild(tokenEl);

        const removeBtn = document.createElement('button');
        removeBtn.className = 'remove-btn';
        removeBtn.textContent = '✕';
        removeBtn.onclick = () => {
            attachedAttachments.splice(index, 1);
            updateAttachmentPreview();
        };

        item.appendChild(meta);
        item.appendChild(removeBtn);
        imagePreviewContainer.appendChild(item);
    });
    if (attachedAttachments.length > 0) {
        imagePreviewContainer.style.display = 'flex';
    } else {
        imagePreviewContainer.style.display = 'none';
    }

    console.log("[Preview] Preview container children:", imagePreviewContainer.children.length);
}


/**
 * 입력창/첨부 파일을 Python 브리지로 전송한다.
 */
// 입력창 텍스트/첨부를 브리지로 보내고 전송 상태를 초기화한다.
function sendMessage() {
    if (isRequestPending) return;

    const message = chatInput.value.trim();

    if (!message && attachedAttachments.length === 0) return;
    const clientMessageId = `message-${createAttachmentId()}`;
    const pendingAttachments = attachedAttachments.map((attachment) => ({
        id: attachment.id,
        dataUrl: attachment.dataUrl,
        name: attachment.name,
        type: attachment.type,
        category: attachment.category,
        messageId: clientMessageId
    }));

    const hasBridge = !!window.pyBridge;
    const canSendWithAttachments = hasBridge && typeof window.pyBridge.send_to_ai_with_attachments === 'function';
    const canSendText = hasBridge && typeof window.pyBridge.send_to_ai === 'function';
    const canDispatchMessage = pendingAttachments.length > 0 ? canSendWithAttachments : canSendText;
    if (!canDispatchMessage) {
        console.error("Python bridge send route is not available");
        addMessage("연결 오류가 발생했어요.", 'assistant', [], new Date(), { excludeFromReroll: true });
        setRequestPending(false);
        shouldReplaceNextAssistant = false;
        return;
    }

    addMessage(message || '(첨부)', 'user', pendingAttachments, new Date(), { messageId: clientMessageId });
    chatInput.value = '';
    autoResizeTextarea();

    shouldReplaceNextAssistant = false;
    setRequestPending(true);

    dispatchBridgeCall(() => {
        if (pendingAttachments.length > 0) {
            window.pyBridge.send_to_ai_with_attachments(message, JSON.stringify(pendingAttachments));
        } else {
            window.pyBridge.send_to_ai(message);
        }
    }, (error) => {
        console.error("Python bridge dispatch failed", error);
        addMessage("연결 오류가 발생했어요.", 'assistant', [], new Date(), { excludeFromReroll: true });
        setRequestPending(false);
        shouldReplaceNextAssistant = false;
    });
    attachedAttachments = [];
    updateAttachmentPreview();
}

// Python 전역 PTT가 호출하는 텍스트 전송 진입점.
function submitVoiceText(text) {
    if (isRequestPending) return;

    const message = (text || '').trim();
    if (!message) return;

    addMessage(message, 'user', [], new Date());
    if (window.pyBridge && window.pyBridge.send_to_ai) {
        shouldReplaceNextAssistant = false;
        setRequestPending(true);
        dispatchBridgeCall(() => {
            window.pyBridge.send_to_ai(message);
        }, (error) => {
            console.error("Python bridge dispatch failed", error);
            addMessage("연결 오류가 발생했어요.", 'assistant', [], new Date(), { excludeFromReroll: true });
            setRequestPending(false);
            shouldReplaceNextAssistant = false;
        });
        return;
    }

    console.error("Python bridge not connected");
    addMessage("연결 오류가 발생했어요.", 'assistant', [], new Date(), { excludeFromReroll: true });
    setRequestPending(false);
    shouldReplaceNextAssistant = false;
}
window.submitVoiceText = submitVoiceText;

/**
 * 입력창 높이를 내용에 맞게 자동 조절한다.
 */
// 입력창 textarea 높이를 내용에 맞게 자동 조절한다.
function autoResizeTextarea() {
    chatInput.style.height = 'auto';
    chatInput.style.height = chatInput.scrollHeight + 'px';
}

if (chatResizeHandle) {
    chatResizeHandle.addEventListener('pointerdown', onChatResizePointerDown);
    chatResizeHandle.addEventListener('pointermove', onChatResizePointerMove);
    chatResizeHandle.addEventListener('pointerup', onChatResizePointerUp);
    chatResizeHandle.addEventListener('pointercancel', () => finishChatPanelResize(null, { persist: false }));
}

sendButton.addEventListener('click', sendMessage);
if (obsRefreshBtn) {
    obsRefreshBtn.addEventListener('click', () => {
        if (window.pyBridge && window.pyBridge.refresh_obs_tree) {
            window.pyBridge.refresh_obs_tree();
        } else {
            requestObsTree();
        }
    });
}

if (moodToggleButton) {
    moodToggleButton.addEventListener('click', () => {
        setMoodPanelOpen(!moodPanelOpen);
        setFloatingActionsOpen(false);
    });
}

if (obsNoteButton) {
    obsNoteButton.addEventListener('click', () => {
        if (window.pyBridge && window.pyBridge.toggle_obs_panel) {
            window.pyBridge.toggle_obs_panel();
        }
        setFloatingActionsOpen(false);
    });
}

if (moodCollapseButton) {
    moodCollapseButton.addEventListener('click', () => setMoodPanelOpen(false));
}

if (manualSummarizeButton) {
    manualSummarizeButton.addEventListener('click', () => {
        requestManualSummary();
        setFloatingActionsOpen(false);
    });
}

if (promiseRemindersButton) {
    promiseRemindersButton.addEventListener('click', () => {
        if (window.pyBridge && window.pyBridge.request_promise_items) {
            window.pyBridge.request_promise_items();
        }
        const nextOpen = promiseRemindersPanel ? promiseRemindersPanel.classList.contains('hidden') : false;
        setGoalPanelOpen(false);
        setPromiseRemindersPanelOpen(nextOpen);
        setFloatingActionsOpen(false);
    });
}

if (goalButton) {
    goalButton.addEventListener('click', () => {
        if (window.pyBridge && window.pyBridge.request_goal_items) {
            window.pyBridge.request_goal_items();
        }
        setPromiseRemindersPanelOpen(false);
        setGoalPanelOpen(!goalPanelOpen);
        setFloatingActionsOpen(false);
    });
}

if (promiseRemindersCloseButton) {
    promiseRemindersCloseButton.addEventListener('click', () => {
        setPromiseRemindersPanelOpen(false);
    });
}

if (goalPanelCloseButton) {
    goalPanelCloseButton.addEventListener('click', () => {
        setGoalPanelOpen(false);
    });
}

if (settingsFloatingButton) {
    settingsFloatingButton.innerHTML = createLucideIcon('settings');
    settingsFloatingButton.addEventListener('click', () => {
        if (window.pyBridge && window.pyBridge.open_settings_dialog) {
            window.pyBridge.open_settings_dialog();
        }
        setFloatingActionsOpen(false);
    });
}

if (floatingActionsToggle) {
    floatingActionsToggle.addEventListener('click', (e) => {
        e.stopPropagation();
        setFloatingActionsOpen(!floatingActionsOpen);
    });
}

if (floatingActionsMenu) {
    floatingActionsMenu.addEventListener('click', (e) => {
        e.stopPropagation();
    });
}

if (summaryConfirmNoButton) {
    summaryConfirmNoButton.addEventListener('click', hideSummaryConfirm);
}

if (summaryConfirmYesButton) {
    summaryConfirmYesButton.addEventListener('click', () => {
        hideSummaryConfirm();
        if (!isManualSummaryBridgeAvailable()) return;
        if (isRequestPending) return;
        window.pyBridge.summarize_now();
    });
}

if (summaryConfirmOverlay) {
    summaryConfirmOverlay.addEventListener('click', (e) => {
        if (e.target === summaryConfirmOverlay) {
            hideSummaryConfirm();
        }
    });
}

if (attachmentDeleteConfirmNoButton) {
    attachmentDeleteConfirmNoButton.addEventListener('click', hideAttachmentDeleteConfirm);
}

if (attachmentDeleteConfirmYesButton) {
    attachmentDeleteConfirmYesButton.addEventListener('click', confirmAttachmentDeletion);
}

if (attachmentDeleteConfirmOverlay) {
    attachmentDeleteConfirmOverlay.addEventListener('click', (e) => {
        if (e.target === attachmentDeleteConfirmOverlay) {
            hideAttachmentDeleteConfirm();
        }
    });
}

if (imageLightboxClose) {
    imageLightboxClose.addEventListener('click', closeImageLightbox);
}

if (imageLightboxOverlay) {
    imageLightboxOverlay.addEventListener('click', (e) => {
        if (e.target === imageLightboxOverlay) {
            closeImageLightbox();
        }
    });
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && imageLightboxOverlay && !imageLightboxOverlay.classList.contains('hidden')) {
        closeImageLightbox();
        return;
    }
    if (e.key === 'Escape' && attachmentDeleteConfirmOverlay && !attachmentDeleteConfirmOverlay.classList.contains('hidden')) {
        hideAttachmentDeleteConfirm();
        return;
    }
    if (e.key === 'Escape' && summaryConfirmOverlay && !summaryConfirmOverlay.classList.contains('hidden')) {
        hideSummaryConfirm();
        return;
    }
    if (e.key === 'Escape' && floatingActionsOpen) {
        setFloatingActionsOpen(false);
    }
});

document.addEventListener('click', (e) => {
    if (!floatingActionsOpen || !floatingActionsRoot) return;
    if (floatingActionsRoot.contains(e.target)) return;
    setFloatingActionsOpen(false);
});

setFloatingActionsOpen(false);
chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});
chatInput.addEventListener('input', autoResizeTextarea);

/**
 * 입력창 붙여넣기 이벤트에서 이미지 데이터를 추출해 첨부한다.
 */
chatInput.addEventListener('paste', (e) => {
    const items = (e.clipboardData || e.originalEvent.clipboardData).items;

    let hasImage = false;

    for (const item of items) {
        if (item.type.indexOf('image') === 0) {
            hasImage = true;
            const blob = item.getAsFile();
            if (attachedAttachments.length >= MAX_ATTACHMENT_COUNT) {
                alert('첨부 파일은 최대 5개까지 첨부할 수 있어요.');
                return;
            }

            const reader = new FileReader();
            reader.onload = (event) => {
                const imageData = {
                    id: createAttachmentId(),
                    dataUrl: event.target.result,
                    name: "pasted_image.png",
                    type: item.type,
                    category: 'image',
                    tokenEstimate: null,
                    width: 0,
                    height: 0,
                    status: 'pending',
                    error: ''
                };

                attachedAttachments.push(imageData);
                updateAttachmentPreview();
                requestAttachmentPreviewMetadata();
            };
            reader.readAsDataURL(blob);
        }
    }
    if (hasImage) {
    }
});

updateRerollButtonState();
