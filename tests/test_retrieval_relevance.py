from app.retrieval.relevance import select_relevant_candidates


def test_relevance_filters_weak_candidates_and_enforces_top_k() -> None:
    candidates = [
        {
            "id": "relevant",
            "service": "gmail",
            "title": "Quantum ML internship research",
            "snippet": "Quantum computing and machine learning research role",
            "score": 0.82,
        },
        {
            "id": "weak-resume",
            "service": "gmail",
            "title": "Resume",
            "snippet": "General software internship application",
            "score": 0.31,
        },
        {
            "id": "unrelated-course",
            "service": "google_drive",
            "title": "Course schedule",
            "snippet": "Weekly lectures and assignments",
            "score": 0.28,
        },
    ]

    selected = select_relevant_candidates(
        candidates,
        "quantum computing research",
        top_k=2,
        requested_services={"gmail", "google_drive"},
    )
    assert [item["id"] for item in selected] == ["relevant"]


def test_relevance_deduplicates_gmail_threads() -> None:
    candidates = [
        {
            "id": "message-new",
            "service": "gmail",
            "title": "Quantum research update",
            "snippet": "quantum computing research",
            "score": 0.90,
            "metadata": {"thread_id": "thread-1"},
        },
        {
            "id": "message-old",
            "service": "gmail",
            "title": "Re: Quantum research update",
            "snippet": "quantum computing research",
            "score": 0.80,
            "metadata": {"thread_id": "thread-1"},
        },
        {
            "id": "drive-match",
            "service": "google_drive",
            "title": "Quantum computing notes",
            "snippet": "research notes",
            "score": 0.75,
        },
    ]

    selected = select_relevant_candidates(
        candidates,
        "quantum computing research",
        top_k=5,
    )
    assert [item["id"] for item in selected] == ["message-new", "drive-match"]


def test_explicit_service_filter_is_applied_before_ranking() -> None:
    candidates = [
        {
            "id": "calendar",
            "service": "google_calendar",
            "title": "Quantum research meeting",
            "snippet": "quantum computing",
            "score": 0.99,
        },
        {
            "id": "drive",
            "service": "google_drive",
            "title": "Quantum research",
            "snippet": "quantum computing",
            "score": 0.75,
        },
    ]
    selected = select_relevant_candidates(
        candidates,
        "quantum computing research",
        top_k=5,
        requested_services={"gmail", "google_drive"},
    )
    assert [item["id"] for item in selected] == ["drive"]


def test_indexed_chunk_text_contributes_to_contextual_relevance() -> None:
    class Candidate:
        id = "indexed-email"
        external_resource_id = "indexed-email"
        service = "gmail"
        title = "Research discussion"
        chunk_text = "QML and distributed quantum computing experiment results"
        score = 0.62
        metadata = {"thread_id": "thread-1"}

    selected = select_relevant_candidates(
        [Candidate()],
        "distributed quantum computing QML",
        top_k=5,
        requested_services={"gmail"},
    )

    assert selected and selected[0].external_resource_id == "indexed-email"
