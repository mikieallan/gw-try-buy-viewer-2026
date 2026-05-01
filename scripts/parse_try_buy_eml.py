#!/usr/bin/env python3
"""One-off pipeline for Try & Buy FAQ wine extraction and enrichment."""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import time
from dataclasses import asdict, dataclass, field, fields
from email import policy
from email.parser import BytesParser
from html import unescape
from pathlib import Path
from typing import Callable
from urllib.parse import quote_plus
from urllib.request import Request, urlopen


CATEGORY_NAMES = {
    "Canadian Cuties",
    "Salty & Savoury",
    "Everyday Bangers",
    "Plush & Textured",
    "Light & Lifted",
    "Freaky Faves",
    "Classic Stars",
}

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Checked first; longer / more specific needles must appear before shorter ones.
MANUAL_VIVINO_OVERRIDES_ORDERED: list[tuple[str, str]] = [
    ("tsolikouri targameuli", "https://www.vivino.com/w/9125605"),
    ("trail estate supersonic", "https://www.vivino.com/w/8341468"),
    ("scout riesling", "https://www.vivino.com/w/7983362"),
    ("pearl morissette roselana", "https://www.vivino.com/w/5517526"),
    ("dagnin cuvee blanche", "https://www.vivino.com/w/6967112"),
    ("pascal clement guettottes", "https://www.vivino.com/w/6064747"),
    ("thibault ducroux morgon", "https://www.vivino.com/w/9984641"),
    ("marco ferrari rosso di valtellina", "https://www.vivino.com/w/9652598"),
    ("adernats bombolla", "https://www.vivino.com/w/13724574"),
    ("ori marani exile", "https://www.vivino.com/w/6385789"),
    ("villa picta lambrusco mantovano", "https://www.vivino.com/w/5459641"),
    ("korenika moskon tris", "https://www.vivino.com/w/5692421"),
    ("selene primeur", "https://www.vivino.com/w/3921987"),
    ("illumi nat", "https://www.vivino.com/w/9455813"),
    ("la villana fuoriluogo", "https://www.vivino.com/w/12637323"),
    ("lune qui nous sourit", "https://www.vivino.com/w/8499732"),
    ("wein goutte newstalgia", "https://www.vivino.com/w/13447160"),
    ("bruno duchene la lune rouge", "https://www.vivino.com/w/1294307"),
    ("metodo interrotto rose", "https://www.vivino.com/w/5388594"),
    ("charlotte dalton love you", "https://www.vivino.com/w/4796769"),
    ("laurent saillard blank", "https://www.vivino.com/w/6100853"),
    ("calvez bobinet piak", "https://www.vivino.com/w/9683341"),
    ("cantina furlani maddie", "https://www.vivino.com/w/10095246"),
    ("envinate lousas", "https://www.vivino.com/w/2402855"),
    ("pardas rupestris", "https://www.vivino.com/w/1265605"),
    ("gut oggau winifred", "https://www.vivino.com/w/2440063"),
    ("guimaro mencia joven", "https://www.vivino.com/w/2383519"),
    ("azores verdelho o original", "https://www.vivino.com/w/3529565"),
    ("clai baracija", "https://www.vivino.com/w/7235957"),
    ("cinque campi bora lunga", "https://www.vivino.com/w/4164637"),
    ("collecapretta rosso da tavola", "https://www.vivino.com/w/1422173"),
    ("src etna rosso", "https://www.vivino.com/w/4115015"),
    ("dzelshavi", "https://www.vivino.com/w/7126453"),
    ("thymiopoulos xinomavro nature", "https://www.vivino.com/w/2536737"),
    ("bernard ott fass 4", "https://www.vivino.com/w/92157"),
]

NOT_ON_VIVINO_PHRASES: frozenset[str] = frozenset(
    {
        "khush khush raho",
        "ontario house vingt cinq",
        "drinks farm caravaggio",
        "raver dave s cab franc",
        "raver dave",
        "villa picta sognare sognare",
        "badenhorst papegaai",
        "para rex",
        "marto x volo volare",
        "chinati vergano dry vermouth",
    }
)


@dataclass
class WineRecord:
    category: str
    raw_wine_line: str
    grape_witches_url: str
    normalized_name: str
    producer: str | None = None
    cuvee: str | None = None
    vintage: str | None = None
    grapes: str | None = None
    region_country: str | None = None
    gw_title: str | None = None
    gw_winery_display: str | None = None
    gw_wine_display: str | None = None
    gw_grape_display: str | None = None
    gw_region_display: str | None = None
    gw_description: str | None = None
    gw_thumbnail_url: str | None = None
    gw_price: str | None = None
    gw_source_excerpt: str | None = None
    vivino_rating: float | None = None
    vivino_num_ratings: int | None = None
    vivino_url: str | None = None
    vivino_confidence: str | None = None
    vivino_match_reason: str | None = None
    vivino_candidates: list[dict] = field(default_factory=list)
    needs_review: bool = False


def normalize_text(text: str) -> str:
    text = unescape(text)
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _jsonld_collect_product_descriptions(node: object, out: list[str]) -> None:
    if isinstance(node, dict):
        types = node.get("@type")
        type_names: set[str] = set()
        if isinstance(types, str):
            type_names.add(types.lower())
        elif isinstance(types, list):
            for t in types:
                if isinstance(t, str):
                    type_names.add(t.lower())
        if "product" in type_names:
            desc = node.get("description")
            if isinstance(desc, str) and desc.strip():
                out.append(desc)
        for val in node.values():
            _jsonld_collect_product_descriptions(val, out)
    elif isinstance(node, list):
        for item in node:
            _jsonld_collect_product_descriptions(item, out)


def extract_product_description_from_jsonld(html: str) -> str | None:
    """Best-effort full product copy from schema.org JSON-LD (Shopify exposes this)."""
    best: str | None = None
    for m in re.finditer(
        r'<script type="application/ld\+json">(.*?)</script>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    ):
        raw = m.group(1).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        found: list[str] = []
        _jsonld_collect_product_descriptions(data, found)
        for d in found:
            if best is None or len(d) > len(best):
                best = d
    return best


def normalize_price(raw_price: str) -> str:
    value = normalize_text(raw_price).replace("$", "").replace(",", "")
    if re.fullmatch(r"\d+", value):
        as_int = int(value)
        # Shopify pages often expose integer cents in metadata.
        if as_int >= 1000:
            return f"${as_int / 100:.2f}"
        return f"${as_int:.2f}"
    if re.fullmatch(r"\d+\.\d{1,2}", value):
        return f"${float(value):.2f}"
    return f"${value}"


def parse_gw_product_title(title: str | None) -> dict[str, str | None]:
    """Split Grape Witches-style titles: Winery + 'Wine' + grapes + region."""
    if not title:
        return {
            "winery": None,
            "wine": None,
            "grapes": None,
            "region": None,
        }
    t = normalize_text(title)
    m = re.match(r"^(.+?)\s+'([^']+)'\s+(.+)$", t)
    if not m:
        return {
            "winery": None,
            "wine": None,
            "grapes": None,
            "region": None,
        }
    winery = m.group(1).strip()
    wine = m.group(2).strip()
    rest = m.group(3).strip()
    if "," in rest:
        parts = [p.strip() for p in rest.split(",") if p.strip()]
        if len(parts) >= 2:
            grapes = ", ".join(parts[:-1])
            region = parts[-1]
        elif len(parts) == 1:
            grapes, region = parts[0], None
        else:
            grapes, region = rest, None
    else:
        words = rest.split()
        if len(words) >= 2:
            region = words[-1]
            grapes = " ".join(words[:-1])
        else:
            grapes, region = rest, None
    return {
        "winery": winery,
        "wine": wine,
        "grapes": grapes,
        "region": region,
    }


def normalize_multiline_text(text: str) -> str:
    text = unescape(text)
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(lines)


def parse_eml_plaintext(eml_path: Path) -> str:
    with eml_path.open("rb") as f:
        msg = BytesParser(policy=policy.default).parse(f)
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return normalize_multiline_text(part.get_content())
    return normalize_multiline_text(msg.get_content())


def split_wine_section(plain_text: str) -> list[str]:
    if "WINE LIST" not in plain_text:
        return []
    start_match = re.search(r"\*?\s*WINE LIST\s*\*?", plain_text)
    if not start_match:
        return []
    section = plain_text[start_match.end() :]
    section = section.split("Website", 1)[0]
    return [line.strip() for line in section.splitlines() if line.strip()]


def extract_wines_from_tokens(tokens: list[str]) -> list[WineRecord]:
    records: list[WineRecord] = []
    category = ""
    pending_line = ""
    i = 0
    while i < len(tokens):
        token = tokens[i]
        clean_token = token.strip().strip("*").strip()
        if clean_token in CATEGORY_NAMES:
            category = clean_token
            i += 1
            continue

        url_chunk = token
        if "<https://grapewitches.com/products/" in token and ">" not in token:
            j = i + 1
            while j < len(tokens) and ">" not in url_chunk:
                url_chunk += tokens[j]
                j += 1
            i = j - 1

        url_match = re.search(r"<\s*(https://grapewitches\.com/products/[^>]+)\s*>", url_chunk)
        if not url_match:
            url_match = re.search(r"(https://grapewitches\.com/products/[^\s>]+)", url_chunk)
        if url_match:
            url = re.sub(r"\s+", "", url_match.group(1))
            prefix = re.sub(r"<\s*https://grapewitches\.com/products/[^>]+\s*>", "", url_chunk).strip()
            line = normalize_text(f"{pending_line} {prefix}".strip())
            pending_line = ""
            if not line or not category:
                i += 1
                continue
            parsed = parse_wine_line(line)
            records.append(
                WineRecord(
                    category=category,
                    raw_wine_line=line,
                    grape_witches_url=url,
                    normalized_name=parsed["normalized_name"],
                    producer=parsed["producer"],
                    cuvee=parsed["cuvee"],
                    vintage=parsed["vintage"],
                    grapes=parsed["grapes"],
                    region_country=parsed["region_country"],
                )
            )
            i += 1
            continue
        pending_line = f"{pending_line} {clean_token}".strip()
        i += 1
    return records


def parse_wine_line(raw_line: str) -> dict:
    line = normalize_text(raw_line)
    producer, rest = (line.split(",", 1) + [""])[:2]
    producer = producer.strip()
    rest = rest.strip()
    vintage_match = re.search(r"\b(19|20)\d{2}\b", line)
    vintage = vintage_match.group(0) if vintage_match else None
    segments = [s.strip() for s in rest.split(",") if s.strip()]
    cuvee = segments[0] if segments else None
    grapes = segments[1] if len(segments) > 1 else None
    region_country = ", ".join(segments[2:]) if len(segments) > 2 else None
    normalized_name = " ".join(part for part in [producer, cuvee] if part)
    return {
        "producer": producer or None,
        "cuvee": cuvee,
        "grapes": grapes,
        "region_country": region_country,
        "vintage": vintage,
        "normalized_name": normalize_text(normalized_name),
    }


def fetch_url(url: str, delay_ms: int = 900, timeout: int = 20) -> str:
    jitter = random.randint(0, 250)
    time.sleep((delay_ms + jitter) / 1000.0)
    req = Request(url=url, headers={"User-Agent": UA})
    with urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def extract_gw_meta(html: str) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    title = None
    desc = None
    thumbnail = None
    price = None
    excerpt = None
    title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
    if title_match:
        title = normalize_text(title_match.group(1))
    og_desc = None
    desc_match = re.search(r'<meta property="og:description" content="([^"]+)"', html)
    if desc_match:
        og_desc = normalize_text(desc_match.group(1))
    ld_raw = extract_product_description_from_jsonld(html)
    ld_desc = None
    if ld_raw:
        ld_desc = normalize_text(re.sub(r"<[^>]+>", " ", ld_raw))
    image_match = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    if image_match:
        thumbnail = normalize_text(image_match.group(1))
    price_meta_match = re.search(r'<meta property="product:price:amount" content="([^"]+)"', html)
    if price_meta_match:
        price = normalize_price(price_meta_match.group(1))
    if not price:
        json_price_match = re.search(r'"price"\s*:\s*"?(?P<price>[0-9]+(?:\.[0-9]{1,2})?)"?', html)
        if json_price_match:
            price = normalize_price(json_price_match.group("price"))
    body_match = re.search(
        r'<div[^>]*class="[^"]*product__description[^"]*"[^>]*>(.*?)</div>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    body_excerpt = None
    if body_match:
        body_excerpt = normalize_text(re.sub(r"<[^>]+>", " ", body_match.group(1)))

    if ld_desc and body_excerpt:
        desc = ld_desc if len(ld_desc) >= len(body_excerpt) else body_excerpt
    elif ld_desc:
        desc = ld_desc
    elif body_excerpt:
        desc = body_excerpt
    else:
        desc = og_desc

    excerpt = body_excerpt or ld_desc
    return title, desc, thumbnail, price, excerpt


def search_vivino_candidates(record: WineRecord, fetcher: Callable[[str], str], max_pages: int = 3) -> list[str]:
    forced_url = override_vivino_url(record)
    if forced_url:
        return [forced_url]
    if max_pages <= 0:
        return []
    search_terms = build_vivino_queries(record)
    urls: list[str] = []
    for term in search_terms[:max_pages]:
        query = quote_plus(term)
        search_url = f"https://www.vivino.com/search/wines?q={query}"
        try:
            html = fetcher(search_url)
        except Exception:
            continue
        for path in re.findall(r"/w/[0-9]+", html):
            clean = f"https://www.vivino.com{path}"
            if clean not in urls:
                urls.append(clean)
        for path in re.findall(r"/[a-z]{2}/[^\"'\s]+/w/[0-9]+", html):
            normalized = f"https://www.vivino.com/w/{path.rsplit('/w/', 1)[-1]}"
            if normalized not in urls:
                urls.append(normalized)
        # Fallback for absolute links when present
        for match in re.findall(r'https?://www\.vivino\.com/w/[0-9]+', html):
            clean = match.rstrip('",)')
            if clean not in urls:
                urls.append(clean)
    return urls[:10]


def parse_vivino_page(html: str) -> tuple[float | None, int | None, str | None]:
    rating = None
    count = None
    title = None
    jsonld_match = re.search(
        r'<script type="application/ld\+json">(.*?)</script>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if jsonld_match:
        blob = jsonld_match.group(1)
        rating_match = re.search(r'"ratingValue"\s*:\s*"?(?P<rating>[0-9.]+)"?', blob)
        count_match = re.search(r'"ratingCount"\s*:\s*"?(?P<count>\d+)"?', blob)
        name_match = re.search(r'"name"\s*:\s*"(?P<name>[^"]+)"', blob)
        if rating_match:
            rating = float(rating_match.group("rating"))
        if count_match:
            count = int(count_match.group("count"))
        if name_match:
            title = normalize_text(name_match.group("name"))
    return rating, count, title


def tokenize(value: str | None) -> set[str]:
    if not value:
        return set()
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def compact_query(value: str | None) -> str:
    if not value:
        return ""
    value = normalize_text(value.lower())
    value = re.sub(r"[^a-z0-9\s-]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def build_vivino_queries(record: WineRecord) -> list[str]:
    slug = ""
    slug_match = re.search(r"/products/([^/?#]+)", record.grape_witches_url)
    if slug_match:
        slug = slug_match.group(1).replace("-", " ")

    query_candidates = [
        record.gw_title,
        record.normalized_name,
        f"{record.producer or ''} {record.cuvee or ''}",
        f"{record.producer or ''} {record.gw_title or ''}",
        f"{record.producer or ''} {record.grapes or ''}",
        record.cuvee,
        slug,
        record.producer,
    ]
    queries: list[str] = []
    for item in query_candidates:
        q = compact_query(item)
        if q and q not in queries:
            queries.append(q)
    return queries


def override_vivino_url(record: WineRecord) -> str | None:
    searchable = " ".join(
        compact_query(v)
        for v in [record.normalized_name, record.gw_title, record.producer, record.cuvee]
        if v
    )
    for needle, url in MANUAL_VIVINO_OVERRIDES_ORDERED:
        if needle in searchable:
            return url
    return None


def is_not_on_vivino(record: WineRecord) -> bool:
    searchable = " ".join(
        compact_query(v)
        for v in [record.normalized_name, record.gw_title, record.producer, record.cuvee]
        if v
    )
    return any(phrase in searchable for phrase in NOT_ON_VIVINO_PHRASES)


def score_candidate(record: WineRecord, candidate_title: str | None) -> tuple[float, str]:
    if not candidate_title:
        return 0.0, "No title parsed from candidate."
    producer_tokens = tokenize(record.producer)
    cuvee_tokens = tokenize(record.cuvee)
    title_hint_tokens = tokenize(record.gw_title) | tokenize(record.normalized_name)
    title_tokens = tokenize(candidate_title)
    producer_overlap = len(producer_tokens & title_tokens) / max(len(producer_tokens), 1)
    cuvee_overlap = len(cuvee_tokens & title_tokens) / max(len(cuvee_tokens), 1)
    title_hint_overlap = len(title_hint_tokens & title_tokens) / max(len(title_hint_tokens), 1)
    score = (producer_overlap * 0.45) + (cuvee_overlap * 0.35) + (title_hint_overlap * 0.20)
    reason = (
        f"producer_overlap={producer_overlap:.2f}; "
        f"cuvee_overlap={cuvee_overlap:.2f}; "
        f"title_hint_overlap={title_hint_overlap:.2f}; title='{candidate_title}'"
    )
    return score, reason


def confidence_from_score(score: float) -> str:
    if score >= 0.82:
        return "high"
    if score >= 0.58:
        return "medium"
    return "low"


def wine_records_from_enriched_json(path: Path) -> list[WineRecord]:
    """Rebuild pipeline records from a prior JSON export (for re-enrichment without the .eml)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Expected a JSON array in {path}")
    names = {f.name for f in fields(WineRecord)}
    out: list[WineRecord] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kwargs = {k: item[k] for k in names if k in item}
        out.append(WineRecord(**kwargs))
    return out


def enrich_records(records: list[WineRecord], fetcher: Callable[[str], str], delay_ms: int, max_pages: int) -> None:
    for record in records:
        record.vivino_candidates = []
        try:
            gw_html = fetcher(record.grape_witches_url)
            title, desc, thumbnail, price, excerpt = extract_gw_meta(gw_html)
            record.gw_title = title
            parsed_title = parse_gw_product_title(title)
            record.gw_winery_display = parsed_title["winery"]
            record.gw_wine_display = parsed_title["wine"]
            record.gw_grape_display = parsed_title["grapes"]
            record.gw_region_display = parsed_title["region"]
            record.gw_description = desc
            record.gw_thumbnail_url = thumbnail
            record.gw_price = price
            record.gw_source_excerpt = excerpt
        except Exception as exc:
            record.gw_source_excerpt = f"Failed to fetch Grape Witches page: {exc}"

        if is_not_on_vivino(record):
            record.vivino_rating = None
            record.vivino_num_ratings = None
            record.vivino_url = None
            record.vivino_confidence = None
            record.vivino_match_reason = "Not listed on Vivino (manual list)."
            record.vivino_candidates = []
            record.needs_review = False
            time.sleep((delay_ms + random.randint(0, 150)) / 1000.0)
            continue

        best_score = -1.0
        best_reason = ""
        best_candidate: dict | None = None
        for candidate_url in search_vivino_candidates(record, fetcher, max_pages=max_pages):
            candidate = {"url": candidate_url}
            try:
                page_html = fetcher(candidate_url)
                rating, num_ratings, title = parse_vivino_page(page_html)
                score, reason = score_candidate(record, title)
                candidate.update(
                    {
                        "title": title,
                        "rating": rating,
                        "num_ratings": num_ratings,
                        "score": round(score, 4),
                        "reason": reason,
                    }
                )
                if score > best_score and rating is not None:
                    best_score = score
                    best_reason = reason
                    best_candidate = candidate
            except Exception as exc:
                candidate.update({"score": 0.0, "reason": f"Fetch failed: {exc}"})
            record.vivino_candidates.append(candidate)

        if best_candidate:
            confidence = confidence_from_score(best_score)
            record.vivino_rating = best_candidate.get("rating")
            record.vivino_num_ratings = best_candidate.get("num_ratings")
            record.vivino_url = best_candidate.get("url")
            record.vivino_confidence = confidence
            record.vivino_match_reason = best_reason
            record.needs_review = confidence != "high"
        else:
            record.needs_review = True
            record.vivino_match_reason = "No candidate with parsed rating."

        time.sleep((delay_ms + random.randint(0, 150)) / 1000.0)


def write_outputs(records: list[WineRecord], out_json: Path, out_csv: Path) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_json.open("w", encoding="utf-8") as jf:
        json.dump([asdict(r) for r in records], jf, indent=2, ensure_ascii=False)
    with out_csv.open("w", encoding="utf-8", newline="") as cf:
        writer = csv.DictWriter(
            cf,
            fieldnames=[
                "category",
                "normalized_name",
                "grape_witches_url",
                "gw_title",
                "gw_winery_display",
                "gw_wine_display",
                "gw_grape_display",
                "gw_region_display",
                "gw_description",
                "gw_thumbnail_url",
                "gw_price",
                "vivino_rating",
                "vivino_num_ratings",
                "vivino_url",
                "vivino_confidence",
                "vivino_match_reason",
                "needs_review",
            ],
        )
        writer.writeheader()
        for rec in records:
            writer.writerow(
                {
                    "category": rec.category,
                    "normalized_name": rec.normalized_name,
                    "grape_witches_url": rec.grape_witches_url,
                    "gw_title": rec.gw_title,
                    "gw_winery_display": rec.gw_winery_display,
                    "gw_wine_display": rec.gw_wine_display,
                    "gw_grape_display": rec.gw_grape_display,
                    "gw_region_display": rec.gw_region_display,
                    "gw_description": rec.gw_description,
                    "gw_thumbnail_url": rec.gw_thumbnail_url,
                    "gw_price": rec.gw_price,
                    "vivino_rating": rec.vivino_rating,
                    "vivino_num_ratings": rec.vivino_num_ratings,
                    "vivino_url": rec.vivino_url,
                    "vivino_confidence": rec.vivino_confidence,
                    "vivino_match_reason": rec.vivino_match_reason,
                    "needs_review": rec.needs_review,
                }
            )


def print_dry_run_summary(records: list[WineRecord]) -> None:
    counts = {"high": 0, "medium": 0, "low": 0, "none": 0}
    for rec in records:
        if rec.vivino_confidence is None:
            counts["none"] += 1
        else:
            counts[rec.vivino_confidence] += 1
    print("Dry-run confidence distribution:", counts)
    print("Ambiguous wines:")
    for rec in records:
        if rec.needs_review:
            print(f"- {rec.normalized_name}: {rec.vivino_match_reason}")


def run_pipeline(args: argparse.Namespace) -> int:
    if args.from_json:
        records = wine_records_from_enriched_json(Path(args.from_json))
    else:
        eml_path = Path(args.input_eml)
        plain_text = parse_eml_plaintext(eml_path)
        tokens = split_wine_section(plain_text)
        records = extract_wines_from_tokens(tokens)
    enrich_records(records, lambda u: fetch_url(u, delay_ms=args.delay_ms), args.delay_ms, args.max_pages)
    if args.dry_run:
        print_dry_run_summary(records)
        return 0
    write_outputs(records, Path(args.output_json), Path(args.output_csv))
    print(f"Wrote {len(records)} wines to {args.output_json} and {args.output_csv}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse Try & Buy FAQ .eml and enrich wine details.")
    parser.add_argument(
        "--input-eml",
        help="Path to the Try & Buy FAQ .eml file (required unless --from-json is set).",
    )
    parser.add_argument(
        "--from-json",
        metavar="PATH",
        help="Re-enrich wines from an existing try_buy_wines_enriched.json (skips .eml parsing).",
    )
    parser.add_argument(
        "--output-json",
        default="data/try_buy_wines_enriched.json",
        help="JSON output path.",
    )
    parser.add_argument(
        "--output-csv",
        default="data/try_buy_wines_review.csv",
        help="CSV review output path.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Run extraction and scoring without output writes.")
    parser.add_argument("--max-pages", type=int, default=3, help="Maximum search query permutations for Vivino.")
    parser.add_argument("--delay-ms", type=int, default=900, help="Base delay between requests in milliseconds.")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    if bool(args.from_json) == bool(args.input_eml):
        build_parser().error("Specify exactly one of: --input-eml or --from-json")
    raise SystemExit(run_pipeline(args))
