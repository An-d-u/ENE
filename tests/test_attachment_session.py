from src.core.attachment_session import AttachmentSession


def test_attachment_session_reuses_cached_items_and_prepares_only_missing():
    session = AttachmentSession()
    prepared_calls = []
    session.cache_prepared_attachments(
        [
            {
                "id": "cached",
                "name": "cached.png",
                "dataUrl": "data:image/png;base64,cached",
                "category": "image",
                "status": "ready",
            }
        ]
    )

    def prepare(items):
        prepared_calls.append(items)
        return [
            {
                "id": "fresh",
                "name": "fresh.png",
                "dataUrl": "data:image/png;base64,fresh",
                "category": "image",
                "status": "ready",
            }
        ]

    resolved = session.resolve_prepared_attachments(
        [
            {"id": "cached", "dataUrl": "data:image/png;base64,cached"},
            {"id": "fresh", "dataUrl": "data:image/png;base64,fresh"},
        ],
        prepare,
    )

    assert [item["id"] for item in resolved] == ["cached", "fresh"]
    assert prepared_calls == [[{"id": "fresh", "dataUrl": "data:image/png;base64,fresh"}]]


def test_attachment_session_upserts_documents_by_name():
    session = AttachmentSession()

    session.upsert_session_documents(
        [
            {
                "name": "Plan.md",
                "type": "text/markdown",
                "category": "document",
                "status": "ready",
                "tokenEstimate": 12,
                "extractedText": "first",
            }
        ]
    )
    session.upsert_session_documents(
        [
            {
                "name": "plan.md",
                "type": "text/markdown",
                "category": "document",
                "status": "ready",
                "tokenEstimate": 20,
                "extractedText": "updated",
            },
            {
                "name": "skip.png",
                "category": "image",
                "status": "ready",
            },
        ]
    )

    assert session.session_attachment_documents == [
        {
            "name": "plan.md",
            "type": "text/markdown",
            "category": "document",
            "tokenEstimate": 20,
            "extractedText": "updated",
            "_name_key": "plan.md",
        }
    ]
