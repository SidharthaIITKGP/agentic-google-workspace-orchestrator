def chunk_text(text: str, target_size: int = 850, overlap: int = 100) -> list[str]:
    """Split text deterministically on nearby whitespace with bounded overlap."""
    cleaned = " ".join(text.split())
    if not cleaned:
        return []
    if target_size < 200:
        raise ValueError("target_size must be at least 200")
    if overlap < 0 or overlap >= target_size:
        raise ValueError("overlap must be non-negative and smaller than target_size")
    if len(cleaned) <= target_size:
        return [cleaned]

    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        proposed_end = min(start + target_size, len(cleaned))
        end = proposed_end
        if proposed_end < len(cleaned):
            boundary = cleaned.rfind(" ", start + target_size // 2, proposed_end + 1)
            if boundary > start:
                end = boundary
        chunks.append(cleaned[start:end].strip())
        if end == len(cleaned):
            break
        next_start = max(0, end - overlap)
        boundary = cleaned.find(" ", next_start, end)
        start = boundary + 1 if boundary != -1 else next_start
    return chunks
