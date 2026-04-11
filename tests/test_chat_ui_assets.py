from pathlib import Path
import re


WEB_DIR = Path(__file__).resolve().parents[1] / "assets" / "web"
STYLE_PATH = WEB_DIR / "style.css"
SCRIPT_PATH = WEB_DIR / "script.js"


def _rule_block(selector: str) -> str:
    css = STYLE_PATH.read_text(encoding="utf-8-sig")
    pattern = rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\n\}}"
    match = re.search(pattern, css, re.DOTALL)
    assert match, f"{selector} 규칙을 찾지 못했습니다."
    return match.group("body")


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8-sig")


def test_chat_container_uses_roomier_bounded_height():
    block = _rule_block("#chat-container")
    assert "overflow: hidden;" in block
    assert "max-height: min(360px, 42vh);" in block


def test_chat_messages_can_shrink_inside_flex_panel():
    block = _rule_block("#chat-messages")
    assert "min-height: 0;" in block


def test_image_preview_stays_reserved_and_keeps_controls_inside():
    preview_block = _rule_block("#image-preview-container")
    remove_button_block = _rule_block(".attachment-preview-item .remove-btn")

    assert "flex-shrink: 0;" in preview_block
    assert "overflow-y: hidden;" in preview_block
    assert "top: 4px;" in remove_button_block
    assert "right: 4px;" in remove_button_block


def test_message_time_meta_rail_aligns_with_bubbles():
    message_block = _rule_block(".message")
    meta_block = _rule_block(".message-meta-rail")
    time_block = _rule_block(".message-time")

    assert "align-items: flex-end;" in message_block
    assert "display: inline-flex;" in meta_block
    assert "align-items: flex-end;" in meta_block
    assert "font-size: 11px;" in time_block
    assert "white-space: nowrap;" in time_block


def test_edit_button_uses_svg_icon_styles():
    block = _rule_block(".message-edit-btn")
    assert "width: 16px;" in block
    assert "height: 16px;" in block
    assert "border-radius: 999px;" in block


def test_reroll_button_uses_svg_icon_styles():
    block = _rule_block(".message-reroll-btn")
    assert "width: 16px;" in block
    assert "height: 16px;" in block
    assert "border-radius: 999px;" in block


def test_loading_indicator_uses_plain_message_row_visuals():
    indicator_block = _rule_block("#loading-indicator")
    typing_text_block = _rule_block(".typing-text")

    assert "display: inline-flex;" in indicator_block
    assert "justify-content: flex-start;" in indicator_block
    assert "gap: 8px;" in indicator_block
    assert "padding-left: 12px;" in indicator_block
    assert "margin-right: auto;" in indicator_block
    assert "align-self: flex-start;" in indicator_block
    assert "width: fit-content;" in indicator_block
    assert "color: var(--ene-chat-panel-text);" in indicator_block
    assert "color: var(--ene-chat-panel-text);" in typing_text_block
    assert "font-size: 14px;" in typing_text_block
    assert "line-height: 1.4;" in typing_text_block
    assert "transform: translateY(4px);" in typing_text_block


def test_token_usage_bubble_is_offset_slightly_lower_from_top_left():
    stack_block = _rule_block("#overlay-notice-stack")
    bubble_block = _rule_block("#token-usage-bubble")
    assert "top: 32px;" in stack_block
    assert "left: 4px;" in stack_block
    assert "position: relative;" in bubble_block


def test_overlay_notice_stack_markup_exists_for_token_and_promise_bubbles():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8-sig")
    assert 'id="overlay-notice-stack"' in html
    assert 'id="token-usage-bubble"' in html
    assert 'id="promise-notice-bubble"' in html


def test_promise_notice_bubble_uses_same_overlay_stack_style():
    stack_block = _rule_block("#overlay-notice-stack")
    notice_block = _rule_block("#promise-notice-bubble")
    hidden_block = _rule_block("#promise-notice-bubble.hidden")

    assert "display: flex;" in stack_block
    assert "flex-direction: column;" in stack_block
    assert "align-items: flex-start;" in stack_block
    assert "gap: 8px;" in stack_block
    assert "position: relative;" in notice_block
    assert "transition: opacity 0.18s ease, transform 0.18s ease;" in notice_block
    assert "pointer-events: none;" in hidden_block


def test_attach_button_centers_within_input_row():
    block = _rule_block("#attach-button")
    assert "align-self: center;" in block


def test_chat_resize_handle_markup_exists_above_messages():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8-sig")
    assert 'id="chat-resize-handle"' in html
    assert '<div id="chat-resize-handle"' in html
    assert html.index('id="chat-resize-handle"') < html.index('id="chat-messages"')


def test_scheduled_promises_menu_markup_exists():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8-sig")
    assert 'id="promise-reminders-floating-btn"' in html
    assert 'id="promise-reminders-panel"' in html
    assert 'id="promise-reminders-close-btn"' in html


def test_chat_resize_handle_uses_vertical_drag_styles():
    block = _rule_block("#chat-resize-handle")
    assert "cursor: ns-resize;" in block
    assert "touch-action: none;" in block
    assert "flex-shrink: 0;" in block


def test_chat_script_defines_typing_effect_speed_guards():
    script = _script_text()
    assert "const MESSAGE_TYPING_BASE_INTERVAL_MS =" in script
    assert "const MESSAGE_TYPING_MAX_DURATION_MS =" in script


def test_chat_script_reuses_typing_renderer_for_new_and_replaced_messages():
    script = _script_text()
    assert "function animateMessageText(" in script
    assert "function renderMessageBubbleSegments(" in script
    assert "animateMessageText(textSpan, segment, { immediate })" in script
    assert "renderMessageBubbleSegments(lastAssistantMessageEl, text" in script


def test_chat_script_creates_split_bubbles_only_when_each_segment_starts_typing():
    script = _script_text()
    assert "animationQueue = animationQueue.then(() => {" in script
    assert "const { bubble, textSpan } = createTextMessageBubble();" in script
    assert "stack.appendChild(bubble);" in script


def test_chat_script_exposes_runtime_typing_config_hook():
    script = _script_text()
    assert "window.setTypingEffectConfig = function" in script
    assert "typingEffectEnabled" in script
    assert "typingEffectSpeed" in script


def test_chat_script_exposes_runtime_message_split_config_hook():
    script = _script_text()
    assert "window.setMessageSplitConfig = function" in script
    assert "messageSplitEnabled" in script
    assert "splitMessageIntoVisualChunks(" in script


def test_chat_script_exposes_builtin_idle_runtime_hook():
    script = _script_text()
    assert "window.setBuiltinIdleMotionEnabled = function" in script
    assert "builtinAutoMotionState.enabled" in script


def test_chat_script_exposes_auto_eye_blink_runtime_hook():
    script = _script_text()
    assert "window.setAutoEyeBlinkEnabled = function" in script
    assert "autoEyeBlinkState.enabled" in script


def test_chat_script_starts_builtin_idle_only_when_enabled():
    script = _script_text()
    assert "if (builtinAutoMotionState.enabled)" in script
    assert "model.motion('Idle');" in script


def test_chat_script_defines_builtin_idle_start_stop_helpers():
    script = _script_text()
    assert "function startBuiltinIdleMotion(" in script
    assert "function stopBuiltinIdleMotion(" in script


def test_chat_script_blocks_motion_manager_idle_group_when_builtin_idle_is_disabled():
    script = _script_text()
    assert "const BUILTIN_IDLE_GROUP_DISABLED =" in script
    assert "motionManager.groups.idle = BUILTIN_IDLE_GROUP_DISABLED;" in script
    assert "motionManager.groups.idle = builtinAutoMotionState.idleGroupName;" in script


def test_chat_script_disables_and_restores_builtin_breath_when_builtin_idle_toggles():
    script = _script_text()
    assert "builtinAutoMotionState.breath = null;" in script
    assert "function syncBuiltinNaturalBreath(" in script
    assert "syncBuiltinAutoMotionComponent(internalModel, 'breath', enabled)" in script


def test_chat_script_runs_idle_motion_without_dynamic_mode_toggle():
    script = _script_text()
    assert "window.setIdleMotionDynamic = function" not in script
    assert "idleMotionDynamicMode" not in script
    assert "const breathWave = Math.sin(idleMotionPhase * 1.1 + 0.35);" in script
    assert "breath: Math.max(-1, Math.min(1, breathWave * idleMotionBreath))" in script
    assert "const IDLE_MOTION_BASE_BREATH = 1.0;" in script


def test_chat_script_disables_and_restores_builtin_physics_when_builtin_idle_toggles():
    script = _script_text()
    assert "builtinAutoMotionState.physics = null;" in script
    assert "function syncBuiltinAutoMotionComponent(" in script
    assert "function syncBuiltinAutoMotionComponents(" in script
    assert "internalModel[propertyName] = null;" in script
    assert "internalModel[propertyName] = builtinAutoMotionState[propertyName];" in script
    assert "syncBuiltinAutoMotionComponent(internalModel, 'physics', enabled)" in script


def test_chat_script_captures_and_toggles_builtin_eye_blink_separately():
    script = _script_text()
    assert "builtinInstance: null," in script
    assert "function captureBuiltinEyeBlinkInstance(" in script
    assert "function syncAutoEyeBlinkMode(" in script
    assert "internalModel.eyeBlink = autoEyeBlinkState.builtinInstance;" in script
    assert "internalModel.eyeBlink = null;" in script


def test_chat_script_defines_fallback_auto_eye_blink_runtime():
    script = _script_text()
    assert "function createAutoEyeBlinkRuntimeState()" in script
    assert "function scheduleNextAutoEyeBlink(" in script
    assert "function updateAutoEyeBlinkRuntime(" in script
    assert "function applyAutoEyeBlinkToCoreModel(" in script
    assert "setParameterValueById('ParamEyeLOpen', openValue)" in script
    assert "setParameterValueById('ParamEyeROpen', openValue)" in script


def test_chat_script_applies_idle_breath_param_when_model_supports_it():
    script = _script_text()
    assert "breath: hasParam('ParamBreath')" in script
    assert "function applyIdleBreathParam(coreModel, idleOffsets = null)" in script
    assert "coreModel.setParameterValueById('ParamBreath', idleBreath);" in script
    assert "applyIdleBreathParam(coreModel, patOffsetsApplied);" in script
    assert "applyIdleBreathParam(coreModel, idleOffsets);" in script


def test_chat_script_blocks_fallback_eye_blink_when_eye_closing_state_is_active():
    script = _script_text()
    assert "function isEyeCloseExpressionActive(sample)" in script
    assert "function shouldSuspendAutoEyeBlink(sample, hasHeadPatEffect)" in script
    assert "sample.fromWeight > 0.001 && resolveExpressionEmotion(sample.fromExpression.emotion) === 'eyeclose';" in script
    assert "return sample.toWeight > 0.001 && resolveExpressionEmotion(sample.toExpression.emotion) === 'eyeclose';" in script


def test_chat_script_allows_expression_transition_duration_override():
    script = _script_text()
    assert "async function changeExpression(emotion, options = {})" in script
    assert "const durationMs = Number.isFinite(options.durationMs)" in script


def test_chat_script_uses_head_pat_fade_durations_for_expression_transitions():
    script = _script_text()
    assert "changeExpression(activeEmotion, { durationMs: headPatFadeInMs })" in script
    assert "changeExpression(endEmotion, { durationMs: headPatFadeOutMs })" in script


def test_chat_script_applies_expression_layers_inside_model_update_cycle():
    script = _script_text()
    assert "function applyExpressionLayer(coreModel, expression, weight)" in script
    assert "coreModel.addParameterValueById(param.id, param.value, weight);" in script
    assert "coreModel.multiplyParameterValueById(param.id, param.value, weight);" in script
    assert "coreModel.setParameterValueById(param.id, param.value, weight);" in script
    assert "function attachExpressionUpdateHook(model)" in script
    assert "internalModel.on('beforeModelUpdate', expressionRuntimeState.updateHook);" in script


def test_chat_script_loads_expression_definitions_with_blend_modes():
    script = _script_text()
    assert "const expressionRuntimeState = {" in script
    assert "definitionCache: new Map()," in script
    assert "function normalizeExpressionBlend(blend)" in script
    assert "blend: normalizeExpressionBlend(param.Blend)" in script
    assert "async function loadExpressionDefinition(emotion)" in script
    assert "const cached = expressionRuntimeState.definitionCache.get(expressionPath);" in script


def test_chat_script_overlaps_expression_fade_in_and_fade_out_weights():
    script = _script_text()
    assert "const fadeOutWeight = fromExpression ? (1 - Math.pow(progress, 3)) : 0;" in script
    assert "const fadeInWeight = 1 - Math.pow(1 - progress, 3);" in script
    assert "fromWeight: fadeOutWeight," in script
    assert "toWeight: fadeInWeight," in script


def test_chat_script_skips_head_pat_eye_override_when_active_expression_already_closes_eyes():
    script = _script_text()
    assert "function shouldUseHeadPatEyeCloseOverride()" in script
    assert "return resolveExpressionEmotion(headPatActiveEmotion) !== 'eyeclose';" in script
    assert "function shouldApplyHeadPatEyeOverrideNow(hasHeadPatEffect)" in script
    assert "return hasHeadPatEffect && patBlendMode !== 'out' && shouldUseHeadPatEyeCloseOverride();" in script
    assert "const shouldApplyHeadPatEyeOverride = shouldApplyHeadPatEyeOverrideNow(hasHeadPatEffect);" in script


def test_chat_script_extracts_expression_transition_duration_and_state_helpers():
    script = _script_text()
    assert "function createEmptyExpressionTransition()" in script
    assert "function resolveExpressionTransitionDuration(resolvedEmotion, requestedDurationMs)" in script
    assert "function setExpressionTransition(nextExpression, durationMs)" in script
    assert "expressionRuntimeState.transition = {" in script


def test_chat_script_stops_head_pat_eye_override_during_fade_out_expression_transition():
    script = _script_text()
    assert "if (shouldApplyHeadPatEyeOverride) {" in script
    assert "applyHeadPatEyeCloseOverride(coreModel, patBlend);" in script


def test_message_bubble_stack_supports_visual_multi_bubble_layout():
    stack_block = _rule_block(".message-bubble-stack")
    user_stack_block = _rule_block(".message.user .message-bubble-stack")
    assistant_stack_block = _rule_block(".message.assistant .message-bubble-stack")

    assert "display: flex;" in stack_block
    assert "flex-direction: column;" in stack_block
    assert "max-width: 70%;" in stack_block
    assert "align-items: flex-end;" in user_stack_block
    assert "align-items: flex-start;" in assistant_stack_block


def test_chat_script_keeps_visual_split_messages_as_single_logical_message():
    script = _script_text()
    assert "function splitMessageIntoVisualChunks(" in script
    assert "messageDiv.dataset.logicalMessageText" in script
    assert "function renderMessageBubbleSegments(" in script
    assert "splitMessageIntoVisualChunks(text)" in script


def test_chat_script_routes_recent_user_edit_through_logical_message_container():
    script = _script_text()
    assert "openInlineEdit(lastUserMessageEl);" in script
    assert "function getMessageLogicalText(" in script


def test_chat_script_exposes_chat_panel_height_restore_and_drag_persistence():
    script = _script_text()
    assert "const chatResizeHandle = document.getElementById('chat-resize-handle');" in script
    assert "function applyChatPanelHeight(height, { persist = false } = {})" in script
    assert "window.setChatPanelHeight = function setChatPanelHeight(height)" in script
    assert "window.pyBridge.save_chat_panel_height(String(nextHeight));" in script
    assert "chatResizeHandle.addEventListener('pointerdown'" in script


def test_chat_script_exposes_promise_panel_runtime_hooks():
    script = _script_text()
    assert "function getVisiblePromiseReminderItems()" in script
    assert "function formatPromiseReminderClock(" in script
    assert "function setPromiseRemindersPanelOpen(open)" in script
    assert "window.setPromiseReminderItems = function" in script
    assert "window.showPromiseReminderNotice = function" in script
    assert "window.setInterval(() => {" in script


def test_chat_script_binds_close_button_for_promise_panel():
    script = _script_text()
    assert "const promiseRemindersCloseButton = document.getElementById('promise-reminders-close-btn');" in script
    assert "promiseRemindersCloseButton.addEventListener('click'" in script
    assert "setPromiseRemindersPanelOpen(false);" in script


def test_chat_script_routes_promise_notice_through_overlay_stack():
    script = _script_text()
    assert "const overlayNoticeStack = document.getElementById('overlay-notice-stack');" in script
    assert "const promiseNoticeBubble = document.getElementById('promise-notice-bubble');" in script
    assert "let promiseNoticeBubbleTimer = null;" in script
    assert "function showPromiseNoticeBubble(message)" in script
    assert "function hidePromiseNoticeBubble()" in script
    assert "window.showPromiseReminderNotice = function showPromiseReminderNotice(message)" in script
    assert "showPromiseNoticeBubble(text);" in script


def test_script_exposes_apply_mouth_pose_hook():
    script = _script_text()
    assert "function applyMouthPose(" in script
    assert "window.pyBridge.mouth_pose_update" in script


def test_script_guards_missing_model_parameters_for_mouth_pose():
    script = _script_text()
    assert "function setModelParameterValue(" in script
    assert "ParamMouthOpenY" in script
    assert "ParamJawOpen" in script
    assert "ParamMouthForm" in script
    assert "ParamMouthFunnel" in script
    assert "ParamMouthPuckerWiden" in script


def test_message_attachment_image_bubble_styles_support_hover_delete_and_deleted_placeholder():
    image_block = _rule_block(".message-attachment-image")
    media_block = _rule_block(".message-attachment-media")
    delete_button_block = _rule_block(".message-attachment-delete-btn")
    delete_hover_block = _rule_block(".message.user .message-attachment-media:hover .message-attachment-delete-btn")
    caption_block = _rule_block(".message-attachment-caption")
    deleted_block = _rule_block(".message-attachment-deleted")

    assert "overflow: hidden;" in image_block
    assert "cursor: zoom-in;" in media_block
    assert "opacity: 0;" in delete_button_block
    assert "opacity: 1;" in delete_hover_block
    assert "font-size: 14px;" in caption_block
    assert "padding: 10px 14px;" in caption_block
    assert "background:" in deleted_block
    assert "border:" in deleted_block


def test_attachment_delete_confirm_body_keeps_multiline_copy():
    confirm_body_block = _rule_block("#attachment-delete-confirm-body")
    assert "white-space: pre-line;" in confirm_body_block


def test_chat_script_routes_attachment_delete_through_confirm_modal():
    script = _script_text()
    assert "function requestAttachmentDeletion(" in script
    assert "function confirmAttachmentDeletion()" in script
    assert "window.pyBridge.delete_message_attachment(" in script
    assert "지운 사진은 컨텍스트에 포함되지 않습니다.\\n정말 지우시겠습니까?" in script


def test_chat_script_opens_image_lightbox_from_image_area_only():
    script = _script_text()
    assert "function openImageLightbox(" in script
    assert "function closeImageLightbox()" in script
    assert "mediaButton.addEventListener('click'" in script
    assert "imgWrapper.appendChild(removeBtn);" not in script
