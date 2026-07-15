from __future__ import annotations

SEPARATORS = " ，,。.!！?？、；;：:\n\t"


def important_terms(text: str) -> list[str]:
    normalized = text
    for separator in SEPARATORS:
        normalized = normalized.replace(separator, " ")
    return [part.strip() for part in normalized.split(" ") if len(part.strip()) >= 2]


def text_supports_claim(body: str, claim: str) -> bool:
    terms = important_terms(claim)
    if not terms:
        return False
    if any(term in body for term in terms):
        return True
    return any(_cjk_rewrite_supported(body, term) for term in terms)


def cjk_fragments(text: str, min_length: int = 2) -> list[str]:
    fragments: list[str] = []
    current = ""
    for character in text:
        if is_cjk(character):
            current += character
        else:
            if len(current) >= min_length:
                fragments.append(current)
            current = ""
    if len(current) >= min_length:
        fragments.append(current)
    return fragments


def is_cjk(character: str) -> bool:
    return "\u4e00" <= character <= "\u9fff"


def _cjk_rewrite_supported(body: str, claim: str) -> bool:
    claim_chars = [character for character in claim if is_cjk(character)]
    if len(claim_chars) < 6:
        return False
    body_chars = {character for character in body if is_cjk(character)}
    unique_claim_chars = set(claim_chars)
    if not unique_claim_chars:
        return False

    coverage = len(unique_claim_chars & body_chars) / len(unique_claim_chars)
    if coverage < 0.55:
        return False

    anchors = _matched_cjk_windows(body, "".join(claim_chars), size=2)
    return len(anchors) >= 2


def _matched_cjk_windows(body: str, claim: str, size: int) -> set[str]:
    if len(claim) < size:
        return set()
    return {
        claim[index : index + size]
        for index in range(len(claim) - size + 1)
        if claim[index : index + size] in body
    }
