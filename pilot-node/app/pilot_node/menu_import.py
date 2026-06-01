from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Iterable

from p4p_core import (
    MenuImportPreviewCandidate,
    MenuImportPreviewRequest,
    MenuImportPreviewResponse,
    MenuItem,
    utc_now,
)

try:
    import rapidocr
    from rapidocr import RapidOCR
except ImportError:  # pragma: no cover - exercised via availability checks
    RapidOCR = None
    rapidocr = None

_LEADING_NUMBER_RE = re.compile(r"^\s*(?:nr\.?\s*)?(?P<number>\d{1,3})[\s.)-]*", re.IGNORECASE)
_LEADING_ITEM_CODE_RE = re.compile(r"^\s*(?:nr\.?\s*)?(?:\d{1,3}[A-Za-zÆØÅæøå]{1,2})\s+", re.IGNORECASE)
_PRICE_RE = re.compile(
    r"(?P<price>\d{1,4}(?:[.,]\d{2})?|\d{1,4},-)\s*(?:kr\b|dkk\b|eur\b)?\s*$",
    re.IGNORECASE,
)
_NON_ITEM_HINT_RE = re.compile(
    r"\b(levering|delivery|minimum|min\.|åbningstid|opening|telefon|phone|adresse|address|bestil|order online|vælg mellem|vaelg mellem|choose between)\b",
    re.IGNORECASE,
)
_CAMEL_CASE_SPLIT_RE = re.compile(r"(?<=[a-zæøå])(?=[A-ZÆØÅ])")
_MEASUREMENT_UNIT_RE = re.compile(r"^(?:cm|cl|ml|dl|l|lt|g|kg|stk|pz|pc|pcs|pezzi?)$", re.IGNORECASE)
_SIZE_PREFIX_RE = re.compile(r"^\s*\d+\s*(?:cm|cl|ml|dl|l|lt|g|kg)\b", re.IGNORECASE)
_PAREN_ONLY_RE = re.compile(r"^\([^)]{1,24}\)$")
_MODIFIER_ONLY_RE = re.compile(r"^(?:rosso|bianco|piccante|mild|stærk|stark|extra|ekstra)$", re.IGNORECASE)


def _slugify(text: str) -> str:
    normalized = (
        text.lower()
        .replace("æ", "ae")
        .replace("ø", "oe")
        .replace("å", "aa")
        .replace("&", " og ")
    )
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized.strip("-")


def _category_from_name(name: str, *, had_number_prefix: bool) -> str:
    lowered = name.lower()
    if "durum" in lowered:
        return "durum"
    if "pita" in lowered:
        return "pita"
    if "burger" in lowered:
        return "burger"
    if "salat" in lowered or "salad" in lowered:
        return "salad"
    if "pasta" in lowered:
        return "pasta"
    if any(word in lowered for word in ("drink", "cola", "fanta", "sprite", "limonata", "chinotto", "soda", "water", "vand")):
        return "drink"
    if "pizza" in lowered:
        return "pizza"
    if "kebab" in lowered:
        return "kebab"
    if had_number_prefix:
        return "pizza"
    return "main"


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _parse_price_minor_units(price_text: str) -> int | None:
    normalized = price_text.strip().lower()
    normalized = normalized.replace("dkk", "").replace("kr", "").strip()
    if normalized.endswith(",-"):
        normalized = normalized[:-2]
    normalized = normalized.strip()
    if not normalized:
        return None
    if "," in normalized or "." in normalized:
        sanitized = normalized.replace(",", ".")
        try:
            value = float(sanitized)
        except ValueError:
            return None
        return int(round(value * 100))
    if not normalized.isdigit():
        return None
    return int(normalized) * 100


def _confidence_for_line(*, had_number_prefix: bool, price_text: str, name: str) -> str:
    if had_number_prefix and re.fullmatch(r"\d{1,4}(?:[.,]\d{2})?|\d{1,4},-", price_text.strip()):
        return "high"
    if len(name.split()) >= 2:
        return "medium"
    return "low"


def _iter_candidate_lines(raw_text: str) -> Iterable[str]:
    for raw_line in raw_text.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line:
            continue
        yield line


def _local_model_paths() -> dict[str, Path]:
    if rapidocr is None:
        raise RuntimeError(
            "Local image OCR dependencies are not installed. Install pilot-node/requirements-ocr.txt."
        )
    model_root = Path(rapidocr.__file__).resolve().parent / "models"
    paths = {
        "det": model_root / "ch_PP-OCRv4_det_infer.onnx",
        "cls": model_root / "ch_ppocr_mobile_v2.0_cls_infer.onnx",
        "rec": model_root / "ch_PP-OCRv4_rec_infer.onnx",
        "keys": model_root / "ppocr_keys_v1.txt",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise RuntimeError(
            "Local OCR models are missing. Expected built-in RapidOCR model files at: "
            + ", ".join(missing)
        )
    return paths


@lru_cache(maxsize=1)
def _ocr_engine() -> RapidOCR:
    if RapidOCR is None:
        raise RuntimeError(
            "Local image OCR dependencies are not installed. Install pilot-node/requirements-ocr.txt."
        )
    model_paths = _local_model_paths()
    return RapidOCR(
        params={
            "Global.log_level": "warning",
            "Det.model_path": str(model_paths["det"]),
            "Cls.model_path": str(model_paths["cls"]),
            "Rec.model_path": str(model_paths["rec"]),
            "Rec.rec_keys_path": str(model_paths["keys"]),
        }
    )


def _normalize_ocr_fragment(text: str) -> str:
    normalized = " ".join(text.strip().split())
    normalized = normalized.replace("·", " ")
    return normalized.strip()


def _humanize_item_name(text: str) -> str:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return ""
    normalized = _CAMEL_CASE_SPLIT_RE.sub(" ", normalized)
    normalized = re.sub(r"(?<=[A-Za-zÆØÅæøå])(?=\d)", " ", normalized)
    normalized = re.sub(r"(?<=\d)(?=[A-Za-zÆØÅæøå])", " ", normalized)
    normalized = re.sub(r"\s*/\s*", " / ", normalized)
    normalized = re.sub(r"(?<=\))(?=[A-Za-zÆØÅæøå])", " ", normalized)
    normalized = re.sub(r"(?<=[A-Za-zÆØÅæøå])\(", " (", normalized)
    normalized = re.sub(r"\)\s*(?=\()", ") ", normalized)
    replacements = (
        (r"\bcocacolazero\b", "cocacola zero"),
        (r"\bverdurepastellate\b", "verdure pastellate"),
        (r"\braguemozzarella\b", "rague mozzarella"),
        (r"\bmozzarellafiordi\b", "mozzarella fiori di"),
    )
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s{2,}", " ", normalized)
    return normalized.strip()


def _should_ignore_name(name: str, *, had_number_prefix: bool, source_line: str) -> bool:
    stripped = name.strip()
    stripped_no_parens = stripped.strip("()[]{} ").lower()
    letters_only = re.sub(r"[^A-Za-zÆØÅæøå]+", "", stripped_no_parens)
    if not stripped_no_parens:
        return True
    if _PAREN_ONLY_RE.fullmatch(stripped):
        return True
    if _MODIFIER_ONLY_RE.fullmatch(stripped_no_parens):
        return True
    if _MEASUREMENT_UNIT_RE.fullmatch(stripped_no_parens):
        return True
    if _SIZE_PREFIX_RE.match(source_line) and (not letters_only or _MEASUREMENT_UNIT_RE.fullmatch(stripped_no_parens)):
        return True
    if had_number_prefix and len(letters_only) <= 2:
        return True
    return False


def _join_ocr_line(parts: list[str]) -> str:
    line = " ".join(part for part in parts if part)
    line = re.sub(r"\s+([,.:;!?])", r"\1", line)
    line = re.sub(r"(?<=\d)\s*kr\b", " kr", line, flags=re.IGNORECASE)
    return line.strip()


def _looks_like_section_header(text: str) -> bool:
    candidate = _LEADING_NUMBER_RE.sub("", text).strip()
    if not candidate:
        return False
    letters_only = re.sub(r"[^A-Za-zÆØÅæøå]+", "", candidate)
    return bool(letters_only) and candidate == candidate.upper()


def _looks_like_description(text: str) -> bool:
    lowered = text.lower()
    if "," in text:
        return True
    if len(text.split()) >= 5:
        return True
    if any(
        hint in lowered
        for hint in ("dressing", "tomat", "salat", "agurk", "skinke", "pepperoni", "kebab,")
    ):
        return True
    return False


def _is_price_token(text: str) -> bool:
    return _PRICE_RE.fullmatch(text.strip()) is not None


def _is_bare_integer_token(text: str) -> bool:
    return re.fullmatch(r"\d{1,4}", text.strip()) is not None


def _token_has_nearby_name_to_right(
    token: dict[str, float | str], tokens: list[dict[str, float | str]]
) -> bool:
    for other in tokens:
        if other is token:
            continue
        other_text = str(other["text"])
        if re.search(r"[A-Za-zÆØÅæøå]", other_text) is None:
            continue
        horizontal_gap = float(other["left"]) - float(token["right"])
        if horizontal_gap <= -24:
            continue
        if horizontal_gap > 260:
            continue
        row_gap = abs(float(other["center_y"]) - float(token["center_y"]))
        row_tolerance = max(18.0, float(token["height"]), float(other["height"])) * 1.15
        if row_gap > row_tolerance:
            continue
        return True
    return False


def _is_candidate_price_token(
    token: dict[str, float | str], tokens: list[dict[str, float | str]]
) -> bool:
    text = str(token["text"]).strip()
    if not _is_price_token(text):
        return False
    if _is_bare_integer_token(text) and _token_has_nearby_name_to_right(token, tokens):
        return False
    return True


def _is_item_name_token(text: str) -> bool:
    if _is_price_token(text):
        return False
    if _NON_ITEM_HINT_RE.search(text):
        return False
    if _looks_like_section_header(text):
        return False
    if _looks_like_description(text):
        return False
    if re.search(r"[A-Za-zÆØÅæøå]", text) is None:
        return False
    return len(text.split()) <= 4 or _LEADING_NUMBER_RE.match(text) is not None


def _price_lane_groups(price_tokens: list[dict[str, float | str]]) -> list[dict[str, object]]:
    if not price_tokens:
        return []
    ordered = sorted(price_tokens, key=lambda token: float(token["left"]))
    groups: list[list[dict[str, float | str]]] = [[ordered[0]]]
    for token in ordered[1:]:
        if float(token["left"]) - float(groups[-1][-1]["left"]) > 250:
            groups.append([token])
        else:
            groups[-1].append(token)
    lanes: list[dict[str, object]] = []
    for group in groups:
        anchors = [float(token["left"]) for token in group]
        lanes.append(
            {
                "anchor": _median(anchors),
                "tokens": group,
            }
        )
    lanes.sort(key=lambda lane: float(lane["anchor"]))
    return lanes


def _expected_price_lane(
    name_token: dict[str, float | str], lanes: list[dict[str, object]]
) -> dict[str, object] | None:
    if not lanes:
        return None
    right_edge = float(name_token["right"])
    future_lanes = [lane for lane in lanes if float(lane["anchor"]) > right_edge - 40.0]
    if future_lanes:
        return min(future_lanes, key=lambda lane: float(lane["anchor"]) - right_edge)
    return None


def _lane_specific_center_gap_limit(
    *,
    name_token: dict[str, float | str],
    lane: dict[str, object],
    lanes: list[dict[str, object]],
    horizontal_gap: float,
) -> float:
    base_limit = max(42.0, float(name_token["height"]) * 1.8)
    is_rightmost_lane = bool(lanes) and lane is lanes[-1]
    if is_rightmost_lane and horizontal_gap > 300.0:
        return max(base_limit, 120.0)
    return base_limit


def _pair_item_names_with_prices(tokens: list[dict[str, float | str]]) -> list[str]:
    price_tokens = [token for token in tokens if _is_candidate_price_token(token, tokens)]
    name_tokens = [token for token in tokens if _is_item_name_token(str(token["text"]))]
    lanes = _price_lane_groups(price_tokens)
    used_price_ids: set[int] = set()
    paired_lines: list[str] = []

    for name_token in sorted(name_tokens, key=lambda token: (float(token["top"]), float(token["left"]))):
        lane = _expected_price_lane(name_token, lanes)
        if lane is None:
            continue
        best_price = None
        best_score = None
        for price_token in lane["tokens"]:
            if id(price_token) in used_price_ids:
                continue
            if float(name_token["left"]) > float(price_token["left"]):
                continue
            horizontal_gap = float(price_token["left"]) - float(name_token["right"])
            if horizontal_gap < -20:
                continue
            center_gap = abs(float(price_token["center_y"]) - float(name_token["center_y"]))
            center_gap_limit = _lane_specific_center_gap_limit(
                name_token=name_token,
                lane=lane,
                lanes=lanes,
                horizontal_gap=horizontal_gap,
            )
            if center_gap > center_gap_limit:
                continue
            if float(price_token["top"]) < float(name_token["top"]) - 18:
                continue
            if float(price_token["top"]) > float(name_token["bottom"]) + 85:
                continue
            score = center_gap * 4.0 + max(0.0, horizontal_gap) * 0.02
            if best_score is None or score < best_score:
                best_price = price_token
                best_score = score
        if best_price is None:
            continue
        used_price_ids.add(id(best_price))
        paired_lines.append(
            _join_ocr_line([str(name_token["text"]), str(best_price["text"])])
        )

    return paired_lines


def _ocr_lines_from_image_bytes(image_bytes: bytes) -> tuple[list[str], list[str]]:
    if not image_bytes:
        raise ValueError("Image body is empty.")

    output = _ocr_engine()(image_bytes)
    if output.boxes is None or output.txts is None or output.scores is None:
        return [], ["No OCR text was detected in the uploaded image."]

    tokens: list[dict[str, float | str]] = []
    for box, text, score in zip(output.boxes, output.txts, output.scores):
        normalized = _normalize_ocr_fragment(text)
        if not normalized:
            continue
        top = min(float(point[1]) for point in box)
        bottom = max(float(point[1]) for point in box)
        left = min(float(point[0]) for point in box)
        tokens.append(
            {
                "text": normalized,
                "score": float(score),
                "center_y": (top + bottom) / 2.0,
                "left": left,
                "right": max(float(point[0]) for point in box),
                "top": top,
                "bottom": bottom,
                "height": max(1.0, bottom - top),
            }
        )

    if not tokens:
        return [], ["No OCR text was detected in the uploaded image."]

    lines = _pair_item_names_with_prices(tokens)
    low_confidence_count = 0
    for token in tokens:
        if float(token["score"]) < 0.75:
            low_confidence_count += 1

    warnings: list[str] = []
    if low_confidence_count:
        warnings.append(
            f"{low_confidence_count} OCR token(s) included lower-confidence text. Review names and prices before save."
        )
    if not lines:
        warnings.append("No name-and-price pairs were recovered from the OCR image.")
    return lines, warnings


def preview_menu_import(request: MenuImportPreviewRequest) -> MenuImportPreviewResponse:
    candidates: list[MenuImportPreviewCandidate] = []
    ignored_lines: list[str] = []
    warnings: list[str] = [
        "Draft preview only. Review every imported line before updating the catalog.",
        "OCR or scanned menu text is not catalog truth in P4P.",
    ]
    seen_ids: set[str] = set()

    for line in _iter_candidate_lines(request.raw_text):
        if _NON_ITEM_HINT_RE.search(line):
            ignored_lines.append(line)
            continue

        price_match = _PRICE_RE.search(line)
        if price_match is None:
            ignored_lines.append(line)
            continue

        had_number_prefix = False
        name_part = line[:price_match.start()].strip(" .-")
        item_code_match = _LEADING_ITEM_CODE_RE.match(name_part)
        if item_code_match is not None:
            had_number_prefix = True
            name_part = name_part[item_code_match.end():].strip(" .-")
        else:
            number_match = _LEADING_NUMBER_RE.match(name_part)
            if number_match is not None:
                had_number_prefix = True
                name_part = name_part[number_match.end():].strip(" .-")
        if not name_part:
            ignored_lines.append(line)
            continue
        name_part = _humanize_item_name(name_part)
        if not name_part:
            ignored_lines.append(line)
            continue
        if _should_ignore_name(name_part, had_number_prefix=had_number_prefix, source_line=line):
            ignored_lines.append(line)
            continue

        price_text = price_match.group("price")
        price_minor = _parse_price_minor_units(price_text)
        if price_minor is None or price_minor <= 0:
            ignored_lines.append(line)
            continue

        item_id = _slugify(name_part)
        if not item_id:
            ignored_lines.append(line)
            continue
        base_item_id = item_id
        duplicate_counter = 2
        while item_id in seen_ids:
            item_id = f"{base_item_id}-{duplicate_counter}"
            duplicate_counter += 1
        seen_ids.add(item_id)

        candidates.append(
            MenuImportPreviewCandidate(
                item=MenuItem(
                    id=item_id,
                    name=name_part,
                    description="",
                    price=price_minor,
                    category=_category_from_name(name_part, had_number_prefix=had_number_prefix),
                    active=True,
                    image_url=None,
                ),
                source_line=line,
                source_price_text=price_text,
                confidence=_confidence_for_line(
                    had_number_prefix=had_number_prefix,
                    price_text=price_text,
                    name=name_part,
                ),
            )
        )

    if not candidates:
        warnings.append("No importable menu lines were found. Try cleaner OCR text or shorter menu sections.")

    if any(candidate.item.category == "pizza" for candidate in candidates):
        warnings.append("Some categories were guessed from numbered pizza-style lines. Review category labels before save.")

    return MenuImportPreviewResponse(
        source_name=request.source_name.strip(),
        parsed_at=utc_now(),
        candidates=candidates,
        ignored_lines=ignored_lines,
        warnings=warnings,
    )


def preview_menu_import_from_image(*, image_bytes: bytes, source_name: str = "") -> MenuImportPreviewResponse:
    ocr_lines, ocr_warnings = _ocr_lines_from_image_bytes(image_bytes)
    raw_text = "\n".join(ocr_lines)
    preview = preview_menu_import(MenuImportPreviewRequest(raw_text=raw_text, source_name=source_name))
    warnings = list(preview.warnings)
    warnings.extend(ocr_warnings)
    warnings.append("Image OCR is approximate. Review every item name, category, and price before updating the catalog.")
    return MenuImportPreviewResponse(
        source_kind="ocr_image",
        source_name=preview.source_name,
        parsed_at=preview.parsed_at,
        candidates=preview.candidates,
        ignored_lines=preview.ignored_lines,
        warnings=warnings,
        extracted_text=raw_text,
        ocr_line_count=len(ocr_lines),
    )


__all__ = ["preview_menu_import", "preview_menu_import_from_image"]
