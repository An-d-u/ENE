
// ==========================================
// QWebChannel 브리지 연결
// ==========================================
if (typeof QWebChannel !== 'undefined') {
    new QWebChannel(qt.webChannelTransport, function (channel) {
        window.pyBridge = channel.objects.bridge;
        console.log("QWebChannel bridge connected");
        updateRerollButtonState();
        if (window.pyBridge.attachment_preview_ready) {
            window.pyBridge.attachment_preview_ready.connect(function (value) {
                applyAttachmentPreviewMetadata(value);
            });
        }
        if (window.pyBridge.token_usage_ready) {
            window.pyBridge.token_usage_ready.connect(function (value) {
                showTokenUsageBubble(value);
            });
        }
        if (window.pyBridge.promise_notice) {
            window.pyBridge.promise_notice.connect(function (message) {
                window.showPromiseReminderNotice(message);
            });
        }
        if (window.pyBridge.promise_items_updated) {
            window.pyBridge.promise_items_updated.connect(function (value) {
                window.setPromiseReminderItems(value);
            });
        }
        if (window.pyBridge.request_promise_items) {
            window.pyBridge.request_promise_items();
        }
        if (window.pyBridge.goal_items_updated) {
            window.pyBridge.goal_items_updated.connect(function (value) {
                window.setGoalItems(value);
            });
        }
        if (window.pyBridge.request_goal_items) {
            window.pyBridge.request_goal_items();
        }
        if (window.pyBridge.request_pending_changed) {
            window.pyBridge.request_pending_changed.connect(function (active) {
                setRequestPending(Boolean(active));
            });
        }
        window.pyBridge.message_received.connect(function (text, emotion, thought) {
            console.log(`Received from Python: "${text}" [${emotion}]`);
            setRequestPending(false);
            const receivedAt = new Date();
            if (shouldReplaceNextAssistant) {
                const replaced = replaceLastAssistantMessage(text, receivedAt, thought || '');
                if (!replaced) {
                    addMessage(text, 'assistant', [], receivedAt, { thought: thought || '' });
                }
            } else {
                addMessage(text, 'assistant', [], receivedAt, { thought: thought || '' });
            }
            shouldReplaceNextAssistant = false;
            updateRerollButtonState();
            cancelPendingPatEmotionRestore();
            baseEmotionTag = (typeof emotion === 'string' && emotion.trim()) ? emotion.trim() : 'normal';
            changeExpression(emotion);
        });
        window.pyBridge.expression_changed.connect(function (emotion) {
            console.log(`Expression changed: ${emotion}`);
            cancelPendingPatEmotionRestore();
            baseEmotionTag = (typeof emotion === 'string' && emotion.trim()) ? emotion.trim() : 'normal';
            changeExpression(emotion);
        });
        if (window.pyBridge.lip_sync_update) {
            window.pyBridge.lip_sync_update.connect(function (mouthValue) {
                setMouthOpen(mouthValue);
            });
            console.log("Lip sync signal connected");
        }
        if (window.pyBridge.mouth_pose_update) {
            window.pyBridge.mouth_pose_update.connect(function (payload) {
                try {
                    const pose = (typeof payload === 'string') ? JSON.parse(payload) : payload;
                    applyMouthPose(pose);
                } catch (e) {
                    console.warn("Failed to parse mouth pose payload:", e);
                }
            });
            console.log("Mouth pose signal connected");
        }

        if (window.pyBridge.reroll_state_changed) {
            window.pyBridge.reroll_state_changed.connect(function (active) {
                shouldReplaceNextAssistant = Boolean(active);
                setRequestPending(Boolean(active));
            });
        }

        if (window.pyBridge.summary_notice) {
            window.pyBridge.summary_notice.connect(function (message, level) {
                const normalizedLevel = (typeof level === 'string' && level.trim()) ? level.trim().toLowerCase() : 'info';
                showToast(message, normalizedLevel);
                updateRerollButtonState();
            });
        }

        if (window.pyBridge.obs_tree_updated) {
            window.pyBridge.obs_tree_updated.connect(function (value) {
                try {
                    const parsed = typeof value === 'string' ? JSON.parse(value) : value;
                    renderObsTree(parsed);
                } catch (e) {
                    renderObsTree({ ok: false, error: `트리 파싱 실패: ${e}` });
                }
            });
        }

        if (window.pyBridge.mood_changed) {
            window.pyBridge.mood_changed.connect(function (label, valence, energy, bond, stress, temporaryState) {
                updateMoodWidget(label, temporaryState, valence, energy, bond, stress);
            });
        }

        if (typeof window.pyBridge.get_mood_snapshot_json === 'function') {
            const applyMoodSnapshot = (value) => {
                if (!value) return;
                let snapshot = null;
                try {
                    if (typeof value === 'string') {
                        snapshot = JSON.parse(value);
                    } else if (typeof value === 'object') {
                        snapshot = value;
                    } else {
                        snapshot = JSON.parse(String(value));
                    }
                } catch (e) {
                    console.warn("Failed to initialize mood widget:", e);
                    return;
                }

                if (!snapshot) return;
                updateMoodWidget(
                    snapshot.current_mood,
                    snapshot.temporary_state,
                    snapshot.valence,
                    snapshot.energy,
                    snapshot.bond,
                    snapshot.stress
                );
            };

            try {
                window.pyBridge.get_mood_snapshot_json(function (value) {
                    applyMoodSnapshot(value);
                });
            } catch (e) {
                console.warn("Failed to initialize mood widget:", e);
            }
        }

    });
} else {
    console.warn("QWebChannel not available - running in standalone mode");
    renderObsTree({ ok: false, error: "QWebChannel 연결 없음" });
}
