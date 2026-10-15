#!/usr/bin/env python3
"""Noxtify — AMOLED desktop music client for Linux/Arch, Python + PyQt6."""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import unicodedata
import uuid
import weakref
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests
from PyQt6.QtCore import Qt, QThread, QTimer, QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot, QSize, QUrl
from PyQt6.QtGui import QFont, QImage, QPixmap, QKeySequence, QShortcut, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton, QLineEdit,
    QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget, QScrollArea,
    QListWidget, QListWidgetItem, QSlider, QSpacerItem, QSizePolicy, QMessageBox,
    QInputDialog, QMenu,
)

APP_NAME = "Noxtify"
APP_VERSION = "0.6.0"
# Keep the legacy data directory so users upgrading from Nox Music retain playlists and history.
APP_DIR = Path.home() / ".local" / "share" / "nox-music"
APP_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = APP_DIR / "state.json"
IPC_FILE = f"/tmp/noxtify-mpv-{os.getuid()}.sock"

BG = "#000000"
PANEL = "#080808"
SURFACE = "#121212"
SURFACE_HOVER = "#1d1d1d"
TEXT = "#f7f7f7"
MUTED = "#a3a3a3"
GREEN = "#1ed760"
BORDER = "#252525"

STYLE = f"""
* {{ font-family: 'Noto Sans', 'Inter', sans-serif; color: {TEXT}; }}
QMainWindow, QWidget#root, QWidget#content, QStackedWidget, QScrollArea,
QScrollArea > QWidget > QWidget {{ background: {BG}; border: 0; }}
QWidget#sidebar {{ background: #050505; border-right: 1px solid #161616; }}
QFrame#topbar, QFrame#playerbar {{ background: {BG}; border: 0; }}
QLabel {{ background: transparent; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#heroTitle {{ font-size: 30px; font-weight: 800; }}
QLabel#sectionTitle {{ font-size: 21px; font-weight: 800; }}
QLabel#brand {{ color: {GREEN}; font-size: 25px; font-weight: 900; }}
QPushButton {{ background: transparent; border: 0; border-radius: 7px; padding: 9px 11px; text-align: left; }}
QPushButton:hover {{ background: {SURFACE_HOVER}; }}
QPushButton#nav {{ color: #b8b8b8; font-size: 13px; font-weight: 650; padding: 12px 13px; }}
QPushButton#nav:checked {{ color: {TEXT}; background: #181818; }}
QPushButton#playlistNav {{ color: #b7b7b7; font-size: 12px; font-weight: 600; padding: 7px 8px; border-radius: 5px; }}
QPushButton#playlistNav:hover {{ color: white; background: #151515; }}
QPushButton#playlistNav:checked {{ color: white; background: #191919; }}
QPushButton#greenButton {{ background: {GREEN}; color: #000; border-radius: 20px; padding: 9px 18px; font-weight: 800; }}
QPushButton#greenButton:hover {{ background: #54ed86; }}
QPushButton#roundButton {{ background: #161616; border: 1px solid #282828; border-radius: 18px; min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; padding: 0; text-align: center; }}
QPushButton#roundButton:hover {{ background: #242424; }}
QPushButton#playButton {{ background: {GREEN}; color: #000; border-radius: 25px; min-width: 48px; max-width: 48px; min-height: 48px; max-height: 48px; padding: 0; text-align: center; font-size: 20px; font-weight: 900; }}
QLineEdit {{ background: #151515; border: 1px solid #222; border-radius: 20px; padding: 11px 16px; selection-background-color: {GREEN}; color: white; }}
QLineEdit:focus {{ border: 1px solid #555; }}
QSlider::groove:horizontal {{ background: #454545; height: 4px; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {GREEN}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #fff; width: 10px; height: 10px; margin: -3px 0; border-radius: 5px; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #343434; min-height: 22px; border-radius: 4px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QListWidget {{ background: transparent; border: 0; outline: 0; }}
QListWidget::item {{ padding: 10px; border-radius: 6px; }}
QListWidget::item:selected {{ background: #222; }}
QFrame#trackRow {{ background: transparent; border-radius: 7px; }}
QFrame#trackRow:hover {{ background: #161616; }}
QFrame#mixCard {{ background: #151515; border-radius: 6px; }}
QFrame#mixCard:hover {{ background: #242424; }}
QFrame#recommendationCard {{ background: #0d0d0d; border-radius: 8px; }}
QFrame#recommendationCard:hover {{ background: #191919; }}
QFrame#artCard {{ background: #101010; border-radius: 9px; }}
QLabel#trackTitle {{ font-size: 13px; font-weight: 700; }}
QLabel#trackArtist {{ color: {MUTED}; font-size: 11px; }}
QLabel#recommendationTitle {{ font-size: 12px; font-weight: 750; }}
QPushButton#artistLink {{ color: {MUTED}; background: transparent; border: 0; border-radius: 0; padding: 0; font-size: 11px; text-align: left; }}
QPushButton#artistLink:hover {{ color: {GREEN}; text-decoration: underline; }}
QLabel#lyricsLine {{ color: #565656; font-size: 20px; font-weight: 700; padding: 7px 24px; }}
QLabel#lyricsActive {{ color: white; font-size: 27px; font-weight: 900; padding: 9px 24px; }}
QLabel#status {{ color: {MUTED}; font-size: 11px; }}
"""


def fmt_time(seconds: Any) -> str:
    try:
        sec = max(0, int(float(seconds)))
        return f"{sec // 60}:{sec % 60:02d}"
    except (TypeError, ValueError):
        return "0:00"


def parse_lrc(text: str) -> list[tuple[float, str]]:
    """Parse LRC timestamp lines into (seconds, lyric) pairs."""
    result: list[tuple[float, str]] = []
    stamp = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]")
    for raw in text.splitlines():
        matches = list(stamp.finditer(raw))
        lyric = stamp.sub("", raw).strip()
        for match in matches:
            fraction_text = match.group(3) or "0"
            fraction = int(fraction_text) / (10 ** len(fraction_text))
            result.append((int(match.group(1)) * 60 + int(match.group(2)) + fraction, lyric))
    return sorted(result, key=lambda item: item[0])


def _normalise_search_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _token_match_strength(token: str, candidates: list[str]) -> float:
    """Return the best normalized token match, allowing small spelling differences."""
    best = 0.0
    for candidate in candidates:
        if token == candidate:
            return 1.0
        if min(len(token), len(candidate)) < 4:
            continue
        length_ratio = min(len(token), len(candidate)) / max(len(token), len(candidate))
        if length_ratio < 0.68:
            continue
        if token.startswith(candidate) or candidate.startswith(token):
            best = max(best, 0.82)
            continue
        ratio = SequenceMatcher(None, token, candidate).ratio()
        if ratio >= 0.80:
            best = max(best, ratio * 0.78)
    return best


def query_match_coverage(query: str, track: dict[str, Any]) -> float:
    """Measure how much of a query appears across a track's title and artist."""
    tokens = _normalise_search_text(query).split()
    if not tokens:
        return 0.0
    title_tokens = _normalise_search_text(track.get("title", "")).split()
    artist_tokens = _normalise_search_text(track.get("artist", "")).split()
    values = [max(_token_match_strength(token, title_tokens), _token_match_strength(token, artist_tokens)) for token in tokens]
    return sum(values) / len(values)


def is_relevant_search_result(query: str, track: dict[str, Any]) -> bool:
    """Reject unrelated results while accepting artist-only and title-only queries."""
    tokens = _normalise_search_text(query).split()
    if not tokens:
        return False
    title_tokens = _normalise_search_text(track.get("title", "")).split()
    artist_tokens = _normalise_search_text(track.get("artist", "")).split()
    title = " ".join(title_tokens)
    artist = " ".join(artist_tokens)
    q = " ".join(tokens)

    if q == title or q == artist or (len(q) >= 4 and (q in title or q in artist)):
        return True
    if len(tokens) == 1:
        token = tokens[0]
        if len(token) <= 3:
            return token in title_tokens or token in artist_tokens
        return max(_token_match_strength(token, title_tokens), _token_match_strength(token, artist_tokens)) >= 0.72

    strengths = [max(_token_match_strength(token, title_tokens), _token_match_strength(token, artist_tokens)) for token in tokens]
    matched = sum(value >= 0.68 for value in strengths)
    minimum_matched = max(2, (len(tokens) * 2 + 2) // 3)
    coverage = sum(strengths) / len(strengths)
    return matched >= minimum_matched and coverage >= 0.66


def search_relevance(query: str, track: dict[str, Any]) -> float:
    """Rank matches like a music search: exact title/artist first, then token coverage."""
    q = _normalise_search_text(query)
    title = _normalise_search_text(track.get("title", ""))
    artist = _normalise_search_text(track.get("artist", ""))
    album = _normalise_search_text(track.get("album", ""))
    if not q:
        return 0.0

    score = 0.0
    if q == artist:
        score += 180.0
    elif len(q) >= 4 and q in artist:
        score += 145.0
    if q == title:
        score += 190.0
    elif len(q) >= 4 and q in title:
        score += 150.0
    if q and q == album:
        score += 40.0

    tokens = q.split()
    title_tokens = title.split()
    artist_tokens = artist.split()
    album_tokens = album.split()
    if not tokens:
        return score

    token_points = 0.0
    matched = 0
    for token in tokens:
        title_match = _token_match_strength(token, title_tokens)
        artist_match = _token_match_strength(token, artist_tokens)
        album_match = _token_match_strength(token, album_tokens)
        best = max(title_match, artist_match)
        if best >= 0.68:
            matched += 1
        # Artist match has slightly greater weight for artist-name searches; title remains strong.
        token_points += max(title_match * 29.0, artist_match * 34.0, album_match * 5.0)

    coverage = query_match_coverage(query, track)
    score += token_points / len(tokens)
    score += coverage * 58.0
    score -= (1.0 - coverage) * 48.0
    if matched == len(tokens):
        score += 30.0
    if len(tokens) > 1 and " ".join(tokens) in title:
        score += 45.0
    return score


STYLE_PROFILES: list[dict[str, Any]] = [
    {"id": "funk_br", "name": "Funk brasileiro", "query": "funk brasileiro músicas populares", "keywords": ["funk", "mandelao", "automotivo", "montagem", "mc ryan", "mc ig", "mc hariel", "mc cabelinho", "mc kevin", "mc livinho", "dj arana", "kondzilla", "lil ze", "bruxaria"]},
    {"id": "rap_trap", "name": "Rap & trap", "query": "rap brasileiro trap hits", "keywords": ["rap", "trap", "drill", "hip hop", "hip-hop", "veigh", "teto", "kayblack", "matue", "sidoka", "froid", "eminem", "kendrick", "travis scott", "lil peep", "tyler the creator"]},
    {"id": "pop", "name": "Pop", "query": "pop hits músicas populares", "keywords": ["pop", "billie eilish", "taylor swift", "dua lipa", "ariana grande", "olivia rodrigo", "lady gaga", "bruno mars", "the weeknd", "justin bieber"]},
    {"id": "rock", "name": "Rock alternativo", "query": "rock alternativo hits", "keywords": ["rock", "metal", "nirvana", "deftones", "radiohead", "linkin park", "slipknot", "metallica", "system of a down", "paramore", "foo fighters", "my chemical romance", "green day"]},
    {"id": "indie_lofi", "name": "Indie & lo-fi", "query": "indie pop lo fi playlists", "keywords": ["indie", "lofi", "lo-fi", "shoegaze", "clairo", "beabadoobee", "cigarettes after sex", "mitski", "the neighbourhood", "girl in red", "men i trust", "mac demarco"]},
    {"id": "mpb", "name": "MPB & acústico", "query": "MPB brasileira acústico", "keywords": ["mpb", "caetano", "gilberto gil", "marisa monte", "djavan", "liniker", "rubel", "ana frango eletrico", "chico buarque", "elis regina", "tim maia"]},
    {"id": "pagode", "name": "Pagode & samba", "query": "pagode samba brasileiro", "keywords": ["pagode", "samba", "sorriso maroto", "menos e mais", "thiaguinho", "zeca pagodinho", "ferrugem", "dilsinho", "grupo revelacao", "exaltasamba"]},
    {"id": "sertanejo", "name": "Sertanejo", "query": "sertanejo universitário hits", "keywords": ["sertanejo", "gusttavo lima", "ana castela", "jorge e mateus", "henrique e juliano", "marilia mendonca", "maiara e maraisa", "luan santana", "murilo huff"]},
    {"id": "electronic", "name": "Eletrônica & dance", "query": "electronic dance house hits", "keywords": ["eletronica", "electronic", "house", "techno", "drum and bass", "dnb", "edm", "deadmau5", "skrillex", "alesso", "avicii", "swedish house mafia", "illenium"]},
    {"id": "jazz_soul", "name": "Jazz & soul", "query": "jazz soul R&B classics", "keywords": ["jazz", "soul", "r&b", "rnb", "frank ocean", "sza", "steve lacy", "bill withers", "amy winehouse", "marvin gaye", "laufey"]},
]


def infer_track_styles(track: dict[str, Any]) -> list[str]:
    """Infer likely styles from explicit discovery choices, tags and artist clues."""
    explicit = str(track.get("discovery_style") or "")
    explicit_ids = {str(profile["id"]) for profile in STYLE_PROFILES}
    found: list[str] = [explicit] if explicit in explicit_ids else []
    corpus = " " + _normalise_search_text(" ".join(str(track.get(key) or "") for key in (
        "genre", "category", "title", "artist", "album", "creator", "query_context"
    ))) + " "
    for profile in STYLE_PROFILES:
        for keyword in profile["keywords"]:
            normalized = _normalise_search_text(keyword)
            if normalized and f" {normalized} " in corpus:
                found.append(str(profile["id"]))
                break
    return list(dict.fromkeys(found))


def select_discovery_styles(favorites: list[dict[str, Any]], recent: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    """Choose personalized genres, keeping some exploration until taste evidence is strong."""
    scores: dict[str, float] = {str(style["id"]): 0.0 for style in STYLE_PROFILES}
    evidence = 0.0
    for weight, tracks in ((2.0, favorites), (1.0, recent[:30])):
        for track in tracks:
            if not isinstance(track, dict):
                continue
            evidence += weight
            for style_id in infer_track_styles(track):
                scores[style_id] = scores.get(style_id, 0.0) + weight

    by_id = {str(style["id"]): style for style in STYLE_PROFILES}
    ranked = sorted(STYLE_PROFILES, key=lambda style: (scores[str(style["id"])], str(style["id"])), reverse=True)
    learned = [style for style in ranked if scores[str(style["id"])] > 0]

    # Early sessions explore several unrelated styles. As listens/likes accumulate,
    # the most strongly represented styles lead the list while two slots keep discovery diverse.
    selected: list[dict[str, Any]] = []
    if learned:
        known_count = min(3 if evidence >= 5 else 1, len(learned))
        selected.extend(learned[:known_count])
    exploration_order = ["funk_br", "rap_trap", "rock", "pop", "indie_lofi", "mpb", "pagode", "sertanejo", "electronic", "jazz_soul"]
    if not selected:
        exploration_order = ["funk_br", "rap_trap", "rock", "pop", "indie_lofi", "mpb", "electronic", "pagode", "sertanejo", "jazz_soul"]
    for style_id in exploration_order:
        if len(selected) >= limit:
            break
        if all(str(item["id"]) != style_id for item in selected):
            selected.append(by_id[style_id])
    if len(selected) < limit:
        for style in STYLE_PROFILES:
            if len(selected) >= limit:
                break
            if all(str(item["id"]) != str(style["id"]) for item in selected):
                selected.append(style)
    return selected[:max(1, limit)]



def most_listened_artist(favorites: list[dict[str, Any]], recent: list[dict[str, Any]]) -> str:
    """Find the artist with the strongest local listening/like signal."""
    totals: dict[str, float] = {}
    display_names: dict[str, str] = {}
    for weight, tracks in ((2.0, favorites), (1.0, recent[:40])):
        for index, track in enumerate(tracks):
            if not isinstance(track, dict):
                continue
            raw = str(track.get("artist") or track.get("creator") or "").split(",")[0].strip()
            normalized = _normalise_search_text(raw)
            if not normalized or normalized in {"artista desconhecido", "unknown artist", "varios artistas"}:
                continue
            if weight == 1.0:
                weight_here = max(0.3, weight - index * 0.017)
            else:
                weight_here = weight
            totals[normalized] = totals.get(normalized, 0.0) + weight_here
            display_names.setdefault(normalized, raw)
    if not totals:
        return ""
    best = max(totals, key=totals.get)
    return display_names[best]

def normalise_youtube_artist(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize an artist result returned by ytmusicapi."""
    thumbnails = item.get("thumbnails") or item.get("images") or []
    if isinstance(thumbnails, dict):
        thumbnails = [thumbnails]
    image = max(
        (entry for entry in thumbnails if isinstance(entry, dict) and (entry.get("url") or entry.get("src"))),
        key=lambda entry: int(entry.get("width") or 0), default={},
    )
    browse_id = str(item.get("browseId") or item.get("channelId") or item.get("id") or "")
    name = str(item.get("artist") or item.get("name") or item.get("title") or "Artista desconhecido")
    url = str(item.get("url") or (f"https://music.youtube.com/channel/{browse_id}" if browse_id else ""))
    return {
        "id": browse_id,
        "name": name,
        "url": url,
        "image": str(image.get("url") or image.get("src") or ""),
        "provider": "youtube",
        "profile_type": "artist",
    }

def _display_name(value: Any) -> str:
    """Convert YouTube Music's inconsistent person/channel fields to a name."""
    if isinstance(value, dict):
        return str(value.get("name") or value.get("title") or "").strip()
    return str(value or "").strip()


def infer_artist_from_title(title: str) -> str:
    """Infer an artist only from common explicit `Artist - Track` upload titles."""
    text = str(title or "").strip()
    match = re.match(r"^(.{1,80}?)\s+[-–—|]\s+(.{1,160})$", text)
    if not match:
        return ""
    left = match.group(1).strip(" .-–—|\t")
    # Avoid mistaking generic video labels for artist names.
    if _normalise_search_text(left) in {"official audio", "official video", "lyrics", "lyric video", "visualizer", "topic"}:
        return ""
    return left


def artist_profile_for_track(track: dict[str, Any]) -> dict[str, Any]:
    """Resolve the performer profile, never the channel that uploaded the video."""
    if str(track.get("profile_type") or "") == "artist":
        artist = dict(track)
        artist.setdefault("provider", "youtube")
        return artist
    profiles = track.get("artist_profiles") or []
    if isinstance(profiles, list):
        for value in profiles:
            if isinstance(value, dict) and str(value.get("name") or "").strip():
                artist = dict(value)
                artist["profile_type"] = "artist"
                artist.setdefault("provider", "youtube")
                artist.setdefault("image", str(track.get("artist_image") or ""))
                artist.setdefault("url", "")
                artist.setdefault("id", "")
                return artist
    name = _display_name(track.get("artist")) or infer_artist_from_title(str(track.get("title") or "")) or "Artista desconhecido"
    return {
        "id": "",
        "name": name,
        "url": str(track.get("artist_url") or ""),
        "image": str(track.get("artist_image") or ""),
        "provider": "youtube",
        "profile_type": "artist",
    }


def creator_profile_for_track(track: dict[str, Any]) -> dict[str, Any]:
    """Resolve the publishing channel separately from the performer profile."""
    raw = track.get("creator_profile") or {}
    profile = dict(raw) if isinstance(raw, dict) else {}
    name = _display_name(profile.get("name") or track.get("creator"))
    channel_id = str(profile.get("id") or track.get("channel_id") or track.get("uploader_id") or "").strip()
    url = str(profile.get("url") or track.get("channel_url") or track.get("uploader_url") or "").strip()
    if not url and channel_id.startswith("UC"):
        url = f"https://www.youtube.com/channel/{channel_id}"
    elif not url and channel_id.startswith("@"):
        url = f"https://www.youtube.com/{channel_id}"
    profile.update({"id": channel_id, "url": url, "name": name})
    return profile


def extract_channel_avatar_url(html: str) -> str:
    """Extract the actual YouTube channel avatar from public channel HTML."""
    text = str(html or "")[:5_000_000]
    # YouTube uses either normal metadata or the avatar thumbnails in its page data.
    for tag in re.findall(r"<meta\b[^>]*>", text, flags=re.IGNORECASE):
        attrs = {key.lower(): (double or single or bare or "") for key, double, single, bare in re.findall(
            r"([\w:-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", tag
        )}
        prop = (attrs.get("property") or attrs.get("name") or "").lower()
        content = attrs.get("content") or ""
        if prop in {"og:image", "twitter:image"} and content.startswith(("https://", "http://")):
            return content.replace("&amp;", "&").replace("\\u0026", "&").replace("\\/", "/")
    avatar_patterns = (
        r'"avatar"\s*:\s*\{\s*"thumbnails"\s*:\s*\[\s*\{\s*"url"\s*:\s*"([^"\\]+)',
        r'"channelMetadataRenderer"\s*:\s*\{.{0,3000}?"avatar"\s*:\s*\{.{0,500}?"url"\s*:\s*"([^"\\]+)',
    )
    for pattern in avatar_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            candidate = match.group(1).replace("\\u0026", "&").replace("\\/", "/")
            if candidate.startswith(("https://", "http://")):
                return candidate
    return ""


def normalise_track(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize YT Music and yt-dlp tracks while separating artist from uploader."""
    artists = item.get("artists") or []
    artist_profiles: list[dict[str, Any]] = []
    if isinstance(artists, str):
        artist = artists.strip()
    elif isinstance(artists, list):
        artist_names: list[str] = []
        for value in artists:
            if not isinstance(value, dict):
                continue
            name = _display_name(value)
            if not name:
                continue
            artist_names.append(name)
            browse_id = str(value.get("browseId") or value.get("channelId") or value.get("id") or "")
            thumbs = value.get("thumbnails") or value.get("images") or []
            if isinstance(thumbs, dict):
                thumbs = [thumbs]
            image = max(
                (entry for entry in thumbs if isinstance(entry, dict) and entry.get("url")),
                key=lambda entry: int(entry.get("width") or 0), default={},
            )
            artist_profiles.append({
                "id": browse_id,
                "name": name,
                "url": f"https://music.youtube.com/channel/{browse_id}" if browse_id else "",
                "image": str(image.get("url") or ""),
                "provider": "youtube",
                "profile_type": "artist",
            })
        artist = ", ".join(artist_names)
    else:
        artist = ""

    if not artist:
        # Some API responses supply a performer in `artist`, but `author`/`uploader`
        # normally names the publishing channel. Do not silently merge those roles.
        artist = _display_name(item.get("artist"))
    title = str(item.get("title") or "Faixa sem título")
    if not artist:
        artist = infer_artist_from_title(title) or "Artista desconhecido"

    album_obj = item.get("album") or {}
    thumbs = item.get("thumbnails") or ([{"url": item.get("thumbnail")}] if item.get("thumbnail") else [])
    if isinstance(thumbs, dict):
        thumbs = [thumbs]
    valid_thumbs = [
        thumb_item for thumb_item in thumbs
        if isinstance(thumb_item, dict)
        and str(thumb_item.get("url", "")).startswith(("https://", "http://"))
    ]
    if valid_thumbs:
        chosen = max(valid_thumbs, key=lambda entry: int(entry.get("width") or entry.get("height") or 0))
        thumbnail = str(chosen.get("url", "")).replace("&amp;", "&")
    else:
        thumbnail = ""

    try:
        duration_value = item.get("duration_seconds") or (item.get("duration") if isinstance(item.get("duration"), (int, float)) else 0) or 0
        duration = int(duration_value)
    except (TypeError, ValueError):
        duration = 0
    if not duration and item.get("duration") and not isinstance(item.get("duration"), (int, float)):
        try:
            parts = [int(part) for part in str(item["duration"]).split(":")]
            if len(parts) in (2, 3):
                for part in parts:
                    duration = duration * 60 + part
        except (TypeError, ValueError):
            duration = 0

    video_id = str(item.get("videoId") or item.get("video_id") or item.get("id") or "")
    fallback = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else ""
    if not thumbnail:
        thumbnail = fallback
    album = album_obj.get("name", "") if isinstance(album_obj, dict) else str(album_obj or "")

    creator = str(item.get("uploader") or item.get("channel") or item.get("author") or item.get("creator") or "").strip()
    creator_id = str(item.get("channel_id") or item.get("uploader_id") or item.get("channelId") or "").strip()
    creator_url = str(item.get("channel_url") or item.get("uploader_url") or "").strip()
    if not creator_url and creator_id.startswith("UC"):
        creator_url = f"https://www.youtube.com/channel/{creator_id}"
    return {
        "id": video_id,
        "provider": "youtube",
        "title": title,
        "artist": artist,
        "artist_profiles": artist_profiles,
        "artist_image": "",
        "creator": creator,
        "creator_profile": {"id": creator_id, "name": creator, "url": creator_url, "avatar": str(item.get("channel_thumbnail") or item.get("uploader_avatar") or "")},
        "album": str(album),
        "duration": duration,
        "thumbnail": thumbnail,
        "thumbnail_fallback": fallback if fallback != thumbnail else "",
        "url": str(item.get("webpage_url") or (f"https://music.youtube.com/watch?v={video_id}" if video_id else item.get("url") or "")),
        "genre": str(item.get("genre") or item.get("category") or ""),
    }

def cover_video_id(track: dict[str, Any]) -> str:
    """Return the YouTube video ID used for thumbnail fallbacks."""
    if track.get("youtube_id"):
        return str(track.get("youtube_id"))
    return str(track.get("id") or "")


def thumbnail_sources(track: dict[str, Any]) -> tuple[str, str]:
    """Return primary artwork and a source-appropriate fallback."""
    primary = str(track.get("thumbnail") or "")
    fallback = str(track.get("thumbnail_fallback") or "")
    video_id = cover_video_id(track)
    if video_id:
        youtube_fallback = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        if not primary:
            primary = youtube_fallback
        elif primary != youtube_fallback and not fallback:
            fallback = youtube_fallback
    if fallback == primary:
        fallback = ""
    return primary, fallback


def thumbnail_candidates(track: dict[str, Any]) -> list[str]:
    """Build robust artwork fallbacks for YouTube Music tracks and uploads."""
    primary, fallback = thumbnail_sources(track)
    candidates = [primary, fallback]
    video_id = cover_video_id(track).strip()
    if video_id:
        candidates.extend([
            f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
            f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
            f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
            f"https://i.ytimg.com/vi/{video_id}/default.jpg",
        ])
    unique: list[str] = []
    for candidate in candidates:
        if candidate.startswith(("https://", "http://")) and candidate not in unique:
            unique.append(candidate)
    return unique


class YouTubeSearchWorker(QThread):
    done = pyqtSignal(list, str, list)

    def __init__(self, query: str):
        super().__init__()
        self.query = query

    def run(self) -> None:
        try:
            from ytmusicapi import YTMusic
            api = YTMusic()
            tracks_by_id: dict[str, dict[str, Any]] = {}
            # Songs first for official catalog matches, then videos to surface covers and
            # uploads by channels that publish music by other artists.
            for filter_name, limit in (("songs", 30), ("videos", 25)):
                try:
                    results = api.search(self.query, filter=filter_name, limit=limit, ignore_spelling=False) or []
                except TypeError:
                    results = api.search(self.query, filter=filter_name, limit=limit) or []
                except Exception:
                    results = []
                for index, item in enumerate(results):
                    if not isinstance(item, dict) or not (item.get("videoId") or item.get("video_id") or item.get("id")):
                        continue
                    track = normalise_track(item)
                    key = str(track.get("id") or track.get("url") or "")
                    if not key:
                        continue
                    # Preserve native catalog order as a relevance tiebreaker.
                    score = search_relevance(self.query, track)
                    if filter_name == "songs":
                        score += 6.0
                    score += max(0.0, 12.0 - index * 0.35)
                    track["_search_score"] = score
                    if key not in tracks_by_id or score > float(tracks_by_id[key].get("_search_score") or 0):
                        tracks_by_id[key] = track

            tracks = sorted(
                tracks_by_id.values(),
                key=lambda track: float(track.get("_search_score") or 0),
                reverse=True,
            )[:40]
            for track in tracks:
                track.pop("_search_score", None)

            artists: list[dict[str, Any]] = []
            try:
                artist_results = api.search(self.query, filter="artists", limit=10) or []
            except Exception:
                artist_results = []
            seen_artists: set[str] = set()
            for item in artist_results:
                if not isinstance(item, dict):
                    continue
                artist = normalise_youtube_artist(item)
                key = artist.get("id") or artist.get("name")
                if key and key not in seen_artists:
                    artists.append(artist)
                    seen_artists.add(str(key))
            if not tracks and not artists:
                self.done.emit([], "Nenhuma música encontrada. Tente o nome da faixa, do artista ou ambos.", [])
            else:
                self.done.emit(tracks, "", artists[:8])
        except Exception as exc:
            self.done.emit([], f"A busca do YouTube Music falhou: {exc}", [])


class YouTubeArtistProfileWorker(QThread):
    done = pyqtSignal(dict, list, list, str)

    def __init__(self, artist: dict[str, Any]):
        super().__init__()
        self.artist = dict(artist)

    def run(self) -> None:
        artist = dict(self.artist)
        tracks: list[dict[str, Any]] = []
        albums: list[dict[str, Any]] = []
        errors: list[str] = []
        try:
            profile_type = str(artist.get("profile_type") or "artist")
            browse_id = str(artist.get("id") or "")
            if profile_type == "channel":
                import yt_dlp
                channel_url = str(artist.get("url") or "")
                if not channel_url and browse_id.startswith("UC"):
                    channel_url = f"https://www.youtube.com/channel/{browse_id}"
                opts = {
                    "quiet": True, "no_warnings": True, "extract_flat": "in_playlist",
                    "skip_download": True, "playlistend": 60, "ignoreerrors": True,
                    "socket_timeout": 15, "noplaylist": False,
                }
                # If a search result has a channel name but no stable URL/ID yet, resolve
                # it through yt-dlp's public search and pick the closest uploader name.
                if not channel_url:
                    creator_name = str(artist.get("name") or "").strip()
                    if creator_name:
                        with yt_dlp.YoutubeDL({**opts, "extract_flat": "in_playlist", "playlistend": 5}) as ydl:
                            search_info = ydl.extract_info(f"ytsearch5:{creator_name}", download=False)
                        entries = [entry for entry in (search_info or {}).get("entries", []) if isinstance(entry, dict)]
                        target = _normalise_search_text(creator_name)
                        candidates = []
                        for entry in entries:
                            entry_name = str(entry.get("channel") or entry.get("uploader") or "").strip()
                            entry_url = str(entry.get("channel_url") or entry.get("uploader_url") or "").strip()
                            entry_id = str(entry.get("channel_id") or entry.get("uploader_id") or "").strip()
                            if not entry_url and entry_id.startswith("UC"):
                                entry_url = f"https://www.youtube.com/channel/{entry_id}"
                            score = SequenceMatcher(None, target, _normalise_search_text(entry_name)).ratio()
                            if entry_url:
                                candidates.append((score, entry_name, entry_url, entry_id))
                        if candidates:
                            score, resolved_name, channel_url, resolved_id = max(candidates, key=lambda item: item[0])
                            if score >= 0.45:
                                artist["name"] = resolved_name or creator_name
                                artist["id"] = resolved_id or browse_id
                                artist["url"] = channel_url
                            else:
                                channel_url = ""
                videos_url = channel_url.rstrip("/") + "/videos" if channel_url and not channel_url.rstrip("/").endswith("/videos") else channel_url
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(videos_url, download=False) if videos_url else None
                if isinstance(info, dict):
                    artist["name"] = str(info.get("channel") or info.get("uploader") or info.get("title") or artist.get("name") or "Canal")
                    artist["url"] = str(info.get("channel_url") or info.get("uploader_url") or channel_url)
                    for entry in info.get("entries") or []:
                        if not isinstance(entry, dict):
                            continue
                        video_id = str(entry.get("id") or entry.get("url") or "")
                        if not video_id or video_id.startswith("http"):
                            match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,})", video_id)
                            video_id = match.group(1) if match else ""
                        if not video_id:
                            continue
                        item = {
                            "id": video_id,
                            "title": entry.get("title") or "Vídeo sem título",
                            "uploader": artist.get("name") or entry.get("uploader") or entry.get("channel") or "Canal",
                            "channel": artist.get("name") or entry.get("channel") or "Canal",
                            "channel_id": browse_id,
                            "duration": entry.get("duration") or 0,
                            "thumbnails": entry.get("thumbnails") or ([{"url": entry.get("thumbnail")}] if entry.get("thumbnail") else []),
                            "webpage_url": entry.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}",
                        }
                        track = normalise_track(item)
                        track["creator"] = str(artist.get("name") or "Canal")
                        track["creator_profile"] = {"id": browse_id, "name": track["creator"], "url": str(artist.get("url") or channel_url)}
                        tracks.append(track)
                if not tracks:
                    errors.append("Não foi possível obter uploads públicos deste canal. O YouTube pode ter limitado a consulta.")
            else:
                from ytmusicapi import YTMusic
                api = YTMusic()
                if not browse_id:
                    query = str(artist.get("name") or "")
                    artist_hits = api.search(query, filter="artists", limit=5) or []
                    resolved = next((normalise_youtube_artist(hit) for hit in artist_hits if isinstance(hit, dict)), None)
                    if resolved:
                        artist.update(resolved)
                        browse_id = str(artist.get("id") or "")
                if not browse_id:
                    raise RuntimeError("Não encontrei o perfil deste artista no YouTube Music.")
                raw = api.get_artist(browse_id)
                artist["name"] = str(raw.get("name") or raw.get("title") or artist.get("name") or "Artista")
                artist["url"] = str(artist.get("url") or f"https://music.youtube.com/channel/{browse_id}")
                thumbs = raw.get("thumbnails") or []
                if thumbs:
                    image = max((x for x in thumbs if isinstance(x, dict) and x.get("url")), key=lambda x: int(x.get("width") or 0), default={})
                    artist["image"] = str(image.get("url") or artist.get("image") or "")
                songs_obj = raw.get("songs") or {}
                song_items = songs_obj.get("results") or [] if isinstance(songs_obj, dict) else []
                for item in song_items:
                    if not isinstance(item, dict) or not (item.get("videoId") or item.get("video_id")):
                        continue
                    track = normalise_track(item)
                    if not track.get("artist_profiles"):
                        track["artist_profiles"] = [dict(artist)]
                    tracks.append(track)
                for album_type in ("albums", "singles", "albums"):
                    section = raw.get(album_type) or {}
                    items = section.get("results") or [] if isinstance(section, dict) else []
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        album_id = str(item.get("browseId") or item.get("id") or "")
                        name = str(item.get("title") or item.get("name") or "Lançamento")
                        thumbs = item.get("thumbnails") or []
                        thumb = max((x for x in thumbs if isinstance(x, dict) and x.get("url")), key=lambda x: int(x.get("width") or 0), default={}) if isinstance(thumbs, list) else {}
                        key = album_id or name
                        if any(str(existing.get("id") or existing.get("name")) == key for existing in albums):
                            continue
                        albums.append({
                            "id": album_id, "name": name,
                            "url": f"https://music.youtube.com/browse/{album_id}" if album_id else artist["url"],
                            "thumbnail": str(thumb.get("url") or ""),
                            "release_date": str(item.get("year") or item.get("yearText") or ""),
                        })
                if not tracks:
                    errors.append("O perfil foi encontrado, mas não retornou faixas públicas para listar.")
        except Exception as exc:
            errors.append(str(exc))
        self.done.emit(artist, tracks[:60], albums[:18], " · ".join(errors))


class DiscoveryWorker(QThread):
    done = pyqtSignal(list, str)

    def __init__(self, styles: list[dict[str, Any]]):
        super().__init__()
        self.styles = [dict(item) for item in styles]

    def run(self) -> None:
        try:
            from ytmusicapi import YTMusic
            api = YTMusic()
            sections: list[dict[str, Any]] = []
            for style in self.styles:
                found: list[dict[str, Any]] = []
                seen: set[str] = set()
                try:
                    items = api.search(str(style.get("query") or style.get("name") or "music"), filter="songs", limit=8) or []
                except Exception:
                    items = []
                if len(items) < 4:
                    try:
                        items += api.search(str(style.get("query") or style.get("name") or "music"), filter="videos", limit=8) or []
                    except Exception:
                        pass
                for item in items:
                    if not isinstance(item, dict) or not (item.get("videoId") or item.get("video_id") or item.get("id")):
                        continue
                    track = normalise_track(item)
                    track["discovery_style"] = str(style.get("id") or "")
                    track["discovery_style_name"] = str(style.get("name") or "")
                    key = str(track.get("id") or track.get("url"))
                    if key and key not in seen:
                        found.append(track)
                        seen.add(key)
                    if len(found) >= 6:
                        break
                if found:
                    sections.append({"id": style.get("id"), "name": style.get("name"), "tracks": found})
            self.done.emit(sections, "" if sections else "Não foi possível carregar recomendações agora.")
        except Exception as exc:
            self.done.emit([], f"Não foi possível carregar recomendações: {exc}")



class ChannelMetadataWorker(QThread):
    """Fetch uploader/channel details asynchronously for visible search results."""
    done = pyqtSignal(str, list)

    def __init__(self, query: str, tracks: list[dict[str, Any]]):
        super().__init__()
        self.query = query
        self.tracks = [dict(track) for track in tracks[:18]]

    @staticmethod
    def _resolve_one(track: dict[str, Any]) -> dict[str, Any] | None:
        video_id = str(track.get("youtube_id") or track.get("id") or "").strip()
        source_url = str(track.get("youtube_url") or track.get("url") or "").strip()
        if not source_url and video_id:
            source_url = f"https://www.youtube.com/watch?v={video_id}"
        if not source_url:
            return None
        existing = creator_profile_for_track(track)
        if existing.get("url") and existing.get("id") and existing.get("name"):
            return None
        try:
            import yt_dlp
            options = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": True,
                "socket_timeout": 9,
                "extractor_retries": 1,
                "ignoreerrors": True,
            }
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(source_url, download=False)
            if not isinstance(info, dict):
                return None
            name = str(info.get("uploader") or info.get("channel") or existing.get("name") or track.get("creator") or "").strip()
            channel_id = str(info.get("channel_id") or info.get("uploader_id") or existing.get("id") or "").strip()
            channel_url = str(info.get("channel_url") or info.get("uploader_url") or existing.get("url") or "").strip()
            if not channel_url and channel_id.startswith("UC"):
                channel_url = f"https://www.youtube.com/channel/{channel_id}"
            if not name:
                return None
            return {
                "id": video_id or str(track.get("id") or ""),
                "creator": name,
                "creator_profile": {
                    "id": channel_id,
                    "name": name,
                    "url": channel_url,
                    "avatar": str(info.get("channel_thumbnail") or info.get("uploader_thumbnail") or ""),
                },
            }
        except Exception:
            return None

    def run(self) -> None:
        resolved: list[dict[str, Any]] = []
        # Channel metadata is looked up in parallel after the results are already visible;
        # failures never block searching or playback.
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(self._resolve_one, track) for track in self.tracks]
            for future in as_completed(futures):
                try:
                    item = future.result()
                    if item:
                        resolved.append(item)
                except Exception:
                    continue
        self.done.emit(self.query, resolved)


class StreamWorker(QThread):
    done = pyqtSignal(dict, str)

    def __init__(self, track: dict[str, Any]):
        super().__init__()
        self.track = track

    def run(self) -> None:
        try:
            import yt_dlp
            opts = {
                "format": "bestaudio/best",
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "skip_download": True,
                "extractor_retries": 2,
                "socket_timeout": 15,
            }
            source_url = str(self.track.get("url") or "")
            track = dict(self.track)
            if not source_url:
                video_id = str(track.get("youtube_id") or track.get("id") or "")
                if video_id:
                    source_url = f"https://www.youtube.com/watch?v={video_id}"
            if not source_url:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    query_info = ydl.extract_info(f"ytsearch5:{track.get('title', '')} {track.get('artist', '')}", download=False)
                    entries = [entry for entry in (query_info.get("entries") or []) if entry]
                    if entries:
                        source_url = str(entries[0].get("webpage_url") or entries[0].get("original_url") or "")
            if not source_url:
                raise RuntimeError("Não encontrei uma versão tocável desta faixa no YouTube Music.")
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(source_url, download=False)
            url = info.get("url")
            if not url:
                formats = [f for f in info.get("formats", []) if f.get("url") and f.get("acodec") != "none"]
                if formats:
                    url = formats[-1]["url"]
            if not url:
                raise RuntimeError("O YouTube Music não retornou um fluxo de áudio.")
            track["duration"] = int(info.get("duration") or track.get("duration") or 0)
            resolved_video_id = str(info.get("id") or "")
            if resolved_video_id and not track.get("youtube_id"):
                track["youtube_id"] = resolved_video_id
            resolved_page = str(info.get("webpage_url") or source_url or "")
            if resolved_page:
                track["youtube_url"] = resolved_page
            # yt-dlp exposes the actual publishing channel, distinct from the track artist.
            old_creator_profile = creator_profile_for_track(track)
            uploader = str(info.get("uploader") or info.get("channel") or old_creator_profile.get("name") or track.get("creator") or "").strip()
            channel_id = str(info.get("channel_id") or info.get("uploader_id") or old_creator_profile.get("id") or "").strip()
            channel_url = str(info.get("channel_url") or info.get("uploader_url") or old_creator_profile.get("url") or "").strip()
            if not channel_url and channel_id.startswith("UC"):
                channel_url = f"https://www.youtube.com/channel/{channel_id}"
            elif not channel_url and channel_id.startswith("@"):
                channel_url = f"https://www.youtube.com/{channel_id}"
            avatar_url = str(info.get("channel_thumbnail") or info.get("uploader_thumbnail") or old_creator_profile.get("avatar") or "")
            if uploader:
                track["creator"] = uploader
                track["creator_profile"] = {
                    "id": channel_id,
                    "name": uploader,
                    "url": channel_url,
                    "avatar": avatar_url,
                }
            self.done.emit({"track": track, "stream_url": url}, "")
        except Exception as exc:
            self.done.emit({}, f"Falha ao abrir a faixa: {exc}")


class LyricsWorker(QThread):
    done = pyqtSignal(dict, str)

    def __init__(self, track: dict[str, Any]):
        super().__init__()
        self.track = dict(track)

    def run(self) -> None:
        title = self.track.get("title", "")
        artist = self.track.get("artist", "")
        headers = {"User-Agent": f"Noxtify/{APP_VERSION} (https://github.com/ympb/noxtify)"}
        try:
            params: dict[str, Any] = {"track_name": title, "artist_name": artist}
            duration = int(self.track.get("duration") or 0)
            if duration > 0:
                params["duration"] = duration
            response = requests.get("https://lrclib.net/api/get", params=params, headers=headers, timeout=8)
            if response.status_code == 200:
                self.done.emit(response.json(), "")
                return
            query = requests.get("https://lrclib.net/api/search", params={"q": f"{title} {artist}"}, headers=headers, timeout=8)
            query.raise_for_status()
            matches = query.json()
            if matches:
                target_title = _normalise_search_text(title)
                target_artist = _normalise_search_text(artist)
                def lyric_match_score(match: dict[str, Any]) -> tuple[float, float, float]:
                    match_title = _normalise_search_text(match.get("trackName", ""))
                    match_artist = _normalise_search_text(match.get("artistName", ""))
                    title_score = SequenceMatcher(None, target_title, match_title).ratio()
                    artist_score = SequenceMatcher(None, target_artist, match_artist).ratio()
                    if target_title and target_title in match_title:
                        title_score = max(title_score, 0.88)
                    if target_artist and (target_artist in match_artist or match_artist in target_artist):
                        artist_score = max(artist_score, 0.85)
                    match_duration = float(match.get("duration") or duration or 0)
                    duration_delta = abs(match_duration - duration) if duration else 0.0
                    return (title_score, artist_score, -duration_delta)
                matches.sort(key=lyric_match_score, reverse=True)
                best = matches[0]
                title_score, artist_score, _duration_score = lyric_match_score(best)
                if title_score >= 0.72 and (artist_score >= 0.48 or not best.get("artistName")):
                    self.done.emit(best, "")
                else:
                    self.done.emit({}, "Não encontramos letras correspondentes a esta versão da música.")
            else:
                self.done.emit({}, "Não encontramos letras para esta música.")
        except Exception as exc:
            self.done.emit({}, f"Não foi possível carregar as letras: {exc}")


class CoverFetchSignals(QObject):
    finished = pyqtSignal(str, bytes)


class CoverFetchTask(QRunnable):
    """Download artwork away from the GUI thread, following redirects and trying fallbacks."""
    def __init__(self, cache_key: str, candidates: list[str]):
        super().__init__()
        self.cache_key = cache_key
        self.candidates = list(candidates)
        self.signals = CoverFetchSignals()

    def run(self) -> None:
        base_headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        for url in self.candidates:
            try:
                headers = dict(base_headers)
                headers["Referer"] = "https://music.youtube.com/"
                response = requests.get(url, headers=headers, timeout=(4, 9), allow_redirects=True)
                if response.status_code != 200:
                    continue
                payload = response.content
                if not payload or len(payload) > 8 * 1024 * 1024:
                    continue
                content_type = str(response.headers.get("content-type", "")).lower()
                if content_type and not content_type.startswith("image/"):
                    continue
                image = QImage()
                if image.loadFromData(payload):
                    self.signals.finished.emit(self.cache_key, payload)
                    return
            except (requests.RequestException, ValueError, OSError):
                continue
        self.signals.finished.emit(self.cache_key, b"")


class CoverLoader(QObject):
    """Cached async artwork loader with several YouTube fallbacks and persistent disk cache."""
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.cache: dict[str, QPixmap] = {}
        self.pending: dict[str, list[tuple[weakref.ReferenceType[QLabel], int, str]]] = {}
        self.running: dict[str, CoverFetchTask] = {}
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(5)
        self.disk_cache = APP_DIR / "covers"
        self.disk_cache.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.disk_cache / f"{digest}.png"

    def _set_pixmap(self, label: QLabel, pixmap: QPixmap, size: int) -> None:
        label.setPixmap(pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                      Qt.TransformationMode.SmoothTransformation))
        label.setText("")
        label.setToolTip("")

    def load(self, url: str, label: QLabel, size: int, fallback_url: str = "", video_id: str = "") -> None:
        if not hasattr(label, "setFixedSize"):
            return
        label.setFixedSize(size, size)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("background:#171717; color:#777; border-radius:6px; font-size:24px;")
        label.setText("♪")
        label.setPixmap(QPixmap())
        candidates = [item for item in [url, fallback_url] if item.startswith(("https://", "http://"))]
        if video_id:
            candidates.extend([
                f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
                f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
                f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
                f"https://i.ytimg.com/vi/{video_id}/default.jpg",
            ])
        unique_candidates: list[str] = []
        for candidate in candidates:
            if candidate not in unique_candidates:
                unique_candidates.append(candidate)
        if not unique_candidates:
            label.setProperty("nox-cover-token", "")
            label.setToolTip("Capa indisponível para esta faixa")
            return

        key = unique_candidates[0]
        token = uuid.uuid4().hex
        label.setProperty("nox-cover-token", token)
        if key in self.cache:
            self._set_pixmap(label, self.cache[key], size)
            return

        cache_path = self._cache_path(key)
        if cache_path.is_file():
            cached = QPixmap(str(cache_path))
            if not cached.isNull():
                self.cache[key] = cached
                self._set_pixmap(label, cached, size)
                return
            try:
                cache_path.unlink(missing_ok=True)
            except OSError:
                pass

        self.pending.setdefault(key, []).append((weakref.ref(label), size, token))
        if key in self.running:
            return
        task = CoverFetchTask(key, unique_candidates)
        task.signals.finished.connect(self._download_finished)
        self.running[key] = task
        self.pool.start(task)

    @pyqtSlot(str, bytes)
    def _download_finished(self, key: str, payload: bytes) -> None:
        self.running.pop(key, None)
        pixmap = QPixmap()
        if payload:
            image = QImage()
            if image.loadFromData(payload):
                pixmap = QPixmap.fromImage(image)
        if not pixmap.isNull():
            self.cache[key] = pixmap
            try:
                pixmap.save(str(self._cache_path(key)), "PNG")
            except OSError:
                pass

        waiters = self.pending.pop(key, [])
        for label_ref, size, token in waiters:
            label = label_ref()
            if label is None:
                continue
            try:
                if label.property("nox-cover-token") != token:
                    continue
                if not pixmap.isNull():
                    self._set_pixmap(label, pixmap, size)
                else:
                    label.setText("♪")
                    label.setToolTip("Não foi possível carregar a capa. Verifique a conexão ou tente novamente.")
            except RuntimeError:
                # The containing row may have been destroyed while the image was downloading.
                continue


class ChannelAvatarSignals(QObject):
    finished = pyqtSignal(str, str)


class ChannelAvatarFetchTask(QRunnable):
    """Resolve the real channel portrait from public YouTube channel HTML."""
    def __init__(self, key: str, url: str):
        super().__init__()
        self.key = key
        self.url = url
        self.signals = ChannelAvatarSignals()

    def run(self) -> None:
        avatar_url = ""
        try:
            from urllib.parse import urlsplit, urlunsplit
            parts = urlsplit(self.url)
            clean_path = parts.path.rstrip("/")
            if clean_path.endswith("/videos") or clean_path.endswith("/streams") or clean_path.endswith("/shorts"):
                clean_path = clean_path.rsplit("/", 1)[0]
            page_url = urlunsplit((parts.scheme or "https", parts.netloc or "www.youtube.com", clean_path, "", ""))
            response = requests.get(
                page_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                },
                timeout=(5, 10), allow_redirects=True,
            )
            if response.ok:
                avatar_url = extract_channel_avatar_url(response.text)
        except (requests.RequestException, ValueError, OSError):
            avatar_url = ""
        self.signals.finished.emit(self.key, avatar_url)


class ChannelAvatarLoader(QObject):
    """Async, persistent cache of actual uploader avatars; never uses a track cover."""
    def __init__(self, parent: QWidget, covers: CoverLoader):
        super().__init__(parent)
        self.covers = covers
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self.cache_file = APP_DIR / "channel-avatar-urls.json"
        try:
            saved = json.loads(self.cache_file.read_text(encoding="utf-8"))
            self.cache: dict[str, str] = saved if isinstance(saved, dict) else {}
        except (OSError, json.JSONDecodeError):
            self.cache = {}
        self.pending: dict[str, list[tuple[weakref.ReferenceType[QLabel], int]]] = {}
        self.running: dict[str, ChannelAvatarFetchTask] = {}

    @staticmethod
    def _profile_url(profile: dict[str, Any]) -> str:
        url = str(profile.get("url") or "").strip()
        channel_id = str(profile.get("id") or "").strip()
        if not url and channel_id.startswith("UC"):
            url = f"https://www.youtube.com/channel/{channel_id}"
        elif not url and channel_id.startswith("@"):
            url = f"https://www.youtube.com/{channel_id}"
        if url and url.startswith(("https://www.youtube.com/", "https://music.youtube.com/")):
            return url
        return ""

    def load(self, profile: dict[str, Any] | None, label: QLabel, size: int) -> None:
        profile = profile if isinstance(profile, dict) else {}
        label.setFixedSize(size, size)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("background:#171717;color:#777;border-radius:10px;font-size:12px;")
        label.setText("◉")
        label.setPixmap(QPixmap())
        direct = str(profile.get("avatar") or profile.get("avatar_url") or "").strip()
        if direct.startswith(("https://", "http://")):
            self.covers.load(direct, label, size)
            return
        url = self._profile_url(profile)
        if not url:
            label.setToolTip("A URL do canal ainda não foi encontrada")
            return
        key = str(profile.get("id") or url).strip()
        cached = self.cache.get(key)
        if cached:
            self.covers.load(cached, label, size)
            return
        label.setToolTip("Carregando foto do canal…")
        self.pending.setdefault(key, []).append((weakref.ref(label), size))
        if key in self.running:
            return
        task = ChannelAvatarFetchTask(key, url)
        task.signals.finished.connect(self._finished)
        self.running[key] = task
        self.pool.start(task)

    @pyqtSlot(str, str)
    def _finished(self, key: str, avatar_url: str) -> None:
        self.running.pop(key, None)
        if avatar_url:
            self.cache[key] = avatar_url
            try:
                self.cache_file.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError:
                pass
        waiters = self.pending.pop(key, [])
        for label_ref, size in waiters:
            label = label_ref()
            if label is None:
                continue
            try:
                if avatar_url:
                    self.covers.load(avatar_url, label, size)
                    label.setToolTip("Foto do canal que publicou esta versão")
                else:
                    label.setText("◉")
                    label.setToolTip("O YouTube não disponibilizou a foto deste canal")
            except RuntimeError:
                continue


class TrackRow(QFrame):
    play_clicked = pyqtSignal()
    queue_clicked = pyqtSignal()
    artist_clicked = pyqtSignal(object)
    creator_clicked = pyqtSignal(object)
    playlist_add_requested = pyqtSignal(object)
    context_menu_requested = pyqtSignal(object, object)

    def __init__(self, track: dict[str, Any], covers: CoverLoader, index: int = 0, compact: bool = False, avatars: ChannelAvatarLoader | None = None):
        super().__init__()
        self.track = track
        self.covers = covers
        self.avatars = avatars
        self.setObjectName("trackRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 5, 8, 5)
        row.setSpacing(11)
        if not compact:
            number = QLabel(str(index + 1))
            number.setFixedWidth(19)
            number.setStyleSheet(f"color:{MUTED}; font-size:12px;")
            row.addWidget(number)
        self.cover = QLabel()
        thumbnail, fallback_thumbnail = thumbnail_sources(track)
        covers.load(thumbnail, self.cover, 44 if not compact else 38, fallback_thumbnail, cover_video_id(track))
        self.cover.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.addWidget(self.cover)
        labels = QVBoxLayout()
        labels.setSpacing(2)
        title = QLabel(str(track.get("title") or "Faixa sem título"))
        title.setObjectName("trackTitle")
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        labels.addWidget(title)
        self.artist_button = QPushButton()
        self.artist_button.setObjectName("artistLink")
        self.artist_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.artist_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.artist_button.clicked.connect(lambda checked=False, t=track: self.artist_clicked.emit(t))
        labels.addWidget(self.artist_button)
        creator_row = QHBoxLayout()
        creator_row.setContentsMargins(0, 0, 0, 0)
        creator_row.setSpacing(5)
        self.creator_avatar = QLabel()
        self.creator_avatar.setFixedSize(18, 18)
        self.creator_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.creator_avatar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        creator_row.addWidget(self.creator_avatar)
        self.creator_button = QPushButton()
        self.creator_button.setObjectName("artistLink")
        self.creator_button.setStyleSheet(f"color:{MUTED};font-size:10px;padding:0;text-align:left;")
        self.creator_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.creator_button.clicked.connect(lambda checked=False, t=track: self.creator_clicked.emit(t))
        creator_row.addWidget(self.creator_button, 1)
        creator_row.addStretch(1)
        labels.addLayout(creator_row)
        row.addLayout(labels, 1)
        duration = QLabel(fmt_time(track.get("duration")))
        duration.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        duration.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.addWidget(duration)
        queue = QPushButton("＋")
        queue.setObjectName("roundButton")
        queue.setToolTip("Adicionar à fila")
        queue.clicked.connect(self.queue_clicked.emit)
        row.addWidget(queue)
        self.update_author_label()
        self.setToolTip("Clique para reproduzir")

    def update_author_label(self) -> None:
        artist = artist_profile_for_track(self.track)
        artist_name = str(artist.get("name") or "Artista desconhecido")
        self.artist_button.setText(artist_name)
        self.artist_button.setToolTip("Abrir o perfil do artista desta música")
        creator_profile = creator_profile_for_track(self.track)
        creator = str(creator_profile.get("name") or self.track.get("creator") or "").strip()
        same_person = _normalise_search_text(creator) == _normalise_search_text(artist_name) if creator else False
        has_channel_identity = bool(creator_profile.get("id") or creator_profile.get("url") or creator_profile.get("avatar"))
        show_creator = bool(creator and creator.casefold() not in {"desconhecido", "unknown", "youtube"} and (not same_person or has_channel_identity))
        self.creator_avatar.setVisible(show_creator)
        self.creator_button.setVisible(show_creator)
        if show_creator:
            self.creator_button.setText(f"Publicado por {creator}")
            self.creator_button.setToolTip("Abrir o canal que publicou esta versão")
            if self.avatars:
                self.avatars.load(creator_profile, self.creator_avatar, 18)
            else:
                self.creator_avatar.setText("◉")

    def contextMenuEvent(self, event: Any) -> None:
        self.context_menu_requested.emit(self.track, event.globalPos())

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.play_clicked.emit()
        super().mousePressEvent(event)


class RecommendationCard(QFrame):
    play_clicked = pyqtSignal(object)
    queue_clicked = pyqtSignal(object)
    artist_clicked = pyqtSignal(object)
    creator_clicked = pyqtSignal(object)

    def __init__(self, track: dict[str, Any], covers: CoverLoader, avatars: ChannelAvatarLoader | None = None):
        super().__init__()
        self.track = dict(track)
        self.covers = covers
        self.avatars = avatars
        self.setObjectName("recommendationCard")
        self.setFixedWidth(158)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 9, 9, 8)
        layout.setSpacing(5)
        self.cover = QLabel()
        thumbnail, fallback = thumbnail_sources(track)
        covers.load(thumbnail, self.cover, 112, fallback, cover_video_id(track))
        self.cover.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title_label = QLabel(str(track.get("title") or "Faixa sem título"))
        self.title_label.setObjectName("recommendationTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setMaximumHeight(35)
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.title_label)
        self.artist_button = QPushButton()
        self.artist_button.setObjectName("artistLink")
        self.artist_button.setToolTip("Abrir perfil do artista desta música")
        self.artist_button.clicked.connect(lambda checked=False, t=self.track: self.artist_clicked.emit(t))
        layout.addWidget(self.artist_button)
        creator_row = QHBoxLayout()
        creator_row.setContentsMargins(0, 0, 0, 0)
        creator_row.setSpacing(5)
        self.creator_avatar = QLabel()
        self.creator_avatar.setFixedSize(18, 18)
        creator_row.addWidget(self.creator_avatar)
        self.creator_button = QPushButton()
        self.creator_button.setObjectName("artistLink")
        self.creator_button.setStyleSheet(f"color:{MUTED};font-size:10px;padding:0;text-align:left;")
        self.creator_button.clicked.connect(lambda checked=False, t=self.track: self.creator_clicked.emit(t))
        creator_row.addWidget(self.creator_button, 1)
        layout.addLayout(creator_row)
        controls = QHBoxLayout()
        controls.addWidget(QLabel(fmt_time(track.get("duration"))))
        controls.addStretch(1)
        add = QPushButton("＋")
        add.setObjectName("roundButton")
        add.setToolTip("Adicionar à fila")
        add.clicked.connect(lambda checked=False, t=self.track: self.queue_clicked.emit(t))
        controls.addWidget(add)
        layout.addLayout(controls)
        self.update_author_label()

    def update_author_label(self) -> None:
        artist = artist_profile_for_track(self.track)
        self.artist_button.setText(str(artist.get("name") or "Artista desconhecido"))
        creator = creator_profile_for_track(self.track)
        name = str(creator.get("name") or "").strip()
        same = bool(name and _normalise_search_text(name) == _normalise_search_text(str(artist.get("name") or "")))
        has_channel_identity = bool(creator.get("id") or creator.get("url") or creator.get("avatar"))
        show = bool(name and (not same or has_channel_identity))
        self.creator_avatar.setVisible(show)
        self.creator_button.setVisible(show)
        if show:
            self.creator_button.setText(name)
            self.creator_button.setToolTip("Abrir o canal que publicou esta versão")
            if self.avatars:
                self.avatars.load(creator, self.creator_avatar, 18)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.play_clicked.emit(self.track)
        super().mousePressEvent(event)


class MusicWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1300, 820)
        self.setMinimumSize(960, 620)
        self.setStyleSheet(STYLE)
        self.covers = CoverLoader(self)
        self.channel_avatars = ChannelAvatarLoader(self, self.covers)
        self.active_workers: list[QThread] = []
        self.current_track: dict[str, Any] | None = None
        self.current_stream = ""
        self.results: list[dict[str, Any]] = []
        self.queue: list[dict[str, Any]] = []
        self.queue_index = -1
        self.favorites: list[dict[str, Any]] = []
        self.recent: list[dict[str, Any]] = []
        self.playlists: list[dict[str, Any]] = []
        self.selected_collection = "liked"
        self.navigation_history: list[str] = []
        self.current_section = "home"
        self._queue_restore_after_lyrics = False
        self._navigating_back = False
        self.latest_search_query = ""
        self._profile_artist: dict[str, Any] = {}
        self.lyric_times: list[tuple[float, str]] = []
        self.lyric_labels: list[QLabel] = []
        self._mpv_ready = False
        self._handled_eof_for: str | None = None
        self._load_state()

        root = QWidget()
        root.setObjectName("root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        workspace = QHBoxLayout()
        workspace.setContentsMargins(0, 0, 0, 0)
        workspace.setSpacing(0)
        root_layout.addLayout(workspace, 1)

        self.sidebar = self._build_sidebar()
        workspace.addWidget(self.sidebar)
        center = QWidget()
        center.setObjectName("content")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(24, 0, 24, 0)
        center_layout.setSpacing(0)
        center_layout.addWidget(self._build_topbar())
        self.pages = QStackedWidget()
        self.home_page = self._build_home_page()
        self.search_page = self._build_search_page()
        self.library_page = self._build_library_page()
        self.lyrics_page = self._build_lyrics_page()
        self.artist_page = self._build_artist_page()
        self.pages.addWidget(self.home_page)
        self.pages.addWidget(self.search_page)
        self.pages.addWidget(self.library_page)
        self.pages.addWidget(self.lyrics_page)
        self.pages.addWidget(self.artist_page)
        center_layout.addWidget(self.pages, 1)
        workspace.addWidget(center, 1)

        self.queue_panel = self._build_queue_panel()
        workspace.addWidget(self.queue_panel)
        self.queue_panel.hide()
        root_layout.addWidget(self._build_playerbar())
        self.setCentralWidget(root)
        self.search_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self.search_shortcut.setWhatsThis("Atalho Ctrl+K: focar a busca musical")
        self.search_shortcut.activated.connect(self.focus_search)

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(900)
        self.poll_timer.timeout.connect(self._poll_player)
        self.poll_timer.start()
        self.refresh_sidebar_playlists()
        self.status("Pronto · pesquise uma faixa para começar")
        self._save_state()  # Rewrite legacy state without retired authentication fields.
        self.discovery_signature: tuple[str, ...] = ()
        self.discovery_worker: DiscoveryWorker | None = None
        self.discovery_refresh_timer = QTimer(self)
        self.discovery_refresh_timer.setSingleShot(True)
        self.discovery_refresh_timer.timeout.connect(self.load_discovery)
        QTimer.singleShot(450, self.load_discovery)

    def _load_state(self) -> None:
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            self.favorites = state.get("favorites", [])
            self.recent = state.get("recent", [])
            self.playlists = state.get("playlists", [])
            if not isinstance(self.playlists, list):
                self.playlists = []
            self.playlists = [p for p in self.playlists if isinstance(p, dict) and p.get("id") and p.get("name")]
        except (OSError, json.JSONDecodeError):
            self.favorites, self.recent, self.playlists = [], [], []

    def _save_state(self) -> None:
        try:
            payload = {
                "favorites": self.favorites[:300], "recent": self.recent[:60], "playlists": self.playlists[:100],
            }
            temp_path = STATE_FILE.with_suffix(".json.tmp")
            temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, STATE_FILE)
        except OSError:
            self.status("Não foi possível salvar a biblioteca local.")

    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(208)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(10, 16, 10, 14)
        layout.setSpacing(7)
        brand = QLabel("◉  nox")
        brand.setObjectName("brand")
        brand.setContentsMargins(5, 0, 0, 22)
        layout.addWidget(brand)

        self.nav_buttons: dict[str, QPushButton] = {}
        home_button = QPushButton("⌂   Início")
        home_button.setObjectName("nav")
        home_button.setCheckable(True)
        home_button.clicked.connect(lambda: self.navigate("home"))
        self.nav_buttons["home"] = home_button
        layout.addWidget(home_button)
        layout.addSpacing(15)

        split = QHBoxLayout()
        label = QPushButton("▤   Sua biblioteca")
        label.setObjectName("nav")
        label.setStyleSheet("text-align:left; padding-left:8px;")
        label.clicked.connect(lambda: self.open_collection("liked"))
        split.addWidget(label, 1)
        plus = QPushButton("＋")
        plus.setObjectName("roundButton")
        plus.setToolTip("Criar playlist")
        plus.clicked.connect(self.create_playlist)
        split.addWidget(plus)
        layout.addLayout(split)

        self.sidebar_playlist_host = QWidget()
        self.sidebar_playlist_layout = QVBoxLayout(self.sidebar_playlist_host)
        self.sidebar_playlist_layout.setContentsMargins(0, 4, 0, 0)
        self.sidebar_playlist_layout.setSpacing(2)
        playlists_scroll = QScrollArea()
        playlists_scroll.setWidgetResizable(True)
        playlists_scroll.setFrameShape(QFrame.Shape.NoFrame)
        playlists_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        playlists_scroll.setWidget(self.sidebar_playlist_host)
        layout.addWidget(playlists_scroll, 1)

        version = QLabel(f"NOXTIFY  ·  v{APP_VERSION}")
        version.setStyleSheet("color:#444; font-size:9px; letter-spacing:1px;")
        layout.addWidget(version)
        self.nav_buttons["home"].setChecked(True)
        return side

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topbar")
        layout = QGridLayout(bar)
        layout.setContentsMargins(0, 14, 0, 18)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(0)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(2, 1)

        left = QWidget()
        left_layout = QHBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        prev = QPushButton("‹")
        prev.setObjectName("roundButton")
        prev.setToolTip("Voltar à página anterior")
        prev.clicked.connect(self.go_back)
        left_layout.addWidget(prev)
        home = QPushButton("⌂")
        home.setObjectName("roundButton")
        home.setToolTip("Voltar para Início")
        home.clicked.connect(lambda: self.navigate("home"))
        left_layout.addWidget(home)
        layout.addWidget(left, 0, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        search_group = QWidget()
        search_layout = QHBoxLayout(search_group)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(10)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("O que você quer ouvir?")
        self.search_edit.setMinimumWidth(250)
        self.search_edit.setFixedWidth(390)
        self.search_edit.returnPressed.connect(lambda: self.search(self.search_edit.text()))
        search_layout.addWidget(self.search_edit, 1)
        search_btn = QPushButton("Buscar")
        search_btn.setObjectName("greenButton")
        search_btn.clicked.connect(lambda: self.search(self.search_edit.text()))
        search_layout.addWidget(search_btn)
        layout.addWidget(search_group, 0, 1, alignment=Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

        right = QWidget()
        right_layout = QHBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        self.top_queue_btn = QPushButton("☷")
        self.top_queue_btn.setObjectName("roundButton")
        self.top_queue_btn.setToolTip("Fila de reprodução")
        self.top_queue_btn.clicked.connect(self.toggle_queue)
        right_layout.addWidget(self.top_queue_btn)
        self.top_lyrics_btn = QPushButton("🎙")
        self.top_lyrics_btn.setObjectName("roundButton")
        self.top_lyrics_btn.setToolTip("Abrir letras da música")
        self.top_lyrics_btn.clicked.connect(lambda: self.navigate("lyrics"))
        right_layout.addWidget(self.top_lyrics_btn)
        layout.addWidget(right, 0, 2, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return bar

    def _scroll_page(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _build_home_page(self) -> QWidget:
        page_content = QWidget()
        layout = QVBoxLayout(page_content)
        layout.setContentsMargins(0, 18, 0, 28)
        layout.setSpacing(13)
        hero = QLabel("Feito pra você")
        hero.setObjectName("heroTitle")
        layout.addWidget(hero)
        if self.favorites or self.recent:
            subtitle_text = "Os estilos mudam conforme você ouve e curte músicas."
        else:
            subtitle_text = "Uma mistura de estilos para começar. Suas recomendações vão aprender com o que você ouvir e curtir."
        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        self.discovery_status = QLabel("Descobrindo músicas para você…")
        self.discovery_status.setObjectName("status")
        layout.addWidget(self.discovery_status)
        self.discovery_container = QWidget()
        self.discovery_layout = QVBoxLayout(self.discovery_container)
        self.discovery_layout.setContentsMargins(0, 0, 0, 0)
        self.discovery_layout.setSpacing(16)
        layout.addWidget(self.discovery_container, 1)
        layout.addStretch(1)
        return self._scroll_page(page_content)

    def _build_search_page(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 12, 0, 22)
        layout.setSpacing(13)
        self.search_page_title = QLabel("Buscar músicas")
        self.search_page_title.setObjectName("heroTitle")
        layout.addWidget(self.search_page_title)
        self.search_info = QLabel("Pesquise músicas, artistas e versões publicadas por canais no YouTube Music.")
        self.search_info.setObjectName("muted")
        self.search_info.setWordWrap(True)
        layout.addWidget(self.search_info)
        self.search_status = QLabel("Pesquise uma música ou artista na barra acima.")
        self.search_status.setObjectName("status")
        layout.addWidget(self.search_status)
        self.artist_results_container = QWidget()
        self.artist_results_layout = QVBoxLayout(self.artist_results_container)
        self.artist_results_layout.setContentsMargins(0, 0, 0, 0)
        self.artist_results_layout.setSpacing(6)
        layout.addWidget(self.artist_results_container)
        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(2)
        self.results_layout.addStretch(1)
        layout.addWidget(self.results_container, 1)
        return self._scroll_page(content)

    def _build_library_page(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 12, 0, 22)
        layout.setSpacing(12)
        self.library_title = QLabel("Músicas curtidas")
        self.library_title.setObjectName("heroTitle")
        layout.addWidget(self.library_title)
        self.library_subtitle = QLabel("Faixas que você marcou com ♥.")
        self.library_subtitle.setObjectName("muted")
        layout.addWidget(self.library_subtitle)
        self.library_container = QWidget()
        self.library_layout = QVBoxLayout(self.library_container)
        self.library_layout.setContentsMargins(0, 0, 0, 0)
        self.library_layout.setSpacing(2)
        layout.addWidget(self.library_container, 1)
        self.refresh_library()
        return self._scroll_page(content)

    def _build_lyrics_page(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 18, 24, 12)
        layout.setSpacing(12)
        self.lyrics_kicker = QLabel("LETRAS")
        self.lyrics_kicker.setStyleSheet(f"color:{GREEN}; font-size:10px; font-weight:900; letter-spacing:3px;")
        layout.addWidget(self.lyrics_kicker, 0, Qt.AlignmentFlag.AlignHCenter)
        self.lyrics_track = QLabel("Escolha uma música")
        self.lyrics_track.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lyrics_track.setStyleSheet("font-size:24px; font-weight:850;")
        layout.addWidget(self.lyrics_track)
        self.lyrics_artist = QLabel("As letras disponíveis aparecem aqui")
        self.lyrics_artist.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lyrics_artist.setStyleSheet(f"color:{MUTED}; font-size:13px;")
        layout.addWidget(self.lyrics_artist)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background:{BORDER}; max-height:1px;")
        layout.addWidget(line)
        self.lyrics_scroll = QScrollArea()
        self.lyrics_scroll.setWidgetResizable(True)
        self.lyrics_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lyric_inner = QWidget()
        self.lyrics_layout = QVBoxLayout(lyric_inner)
        self.lyrics_layout.setContentsMargins(14, 25, 14, 25)
        self.lyrics_layout.setSpacing(8)
        self.lyrics_layout.addStretch(1)
        self.lyrics_scroll.setWidget(lyric_inner)
        self.lyrics_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.lyrics_scroll, 1)
        return content

    def _build_artist_page(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 18, 12, 24)
        layout.setSpacing(18)
        header = QHBoxLayout()
        header.setSpacing(18)
        self.artist_profile_cover = QLabel("♫")
        self.artist_profile_cover.setFixedSize(144, 144)
        self.artist_profile_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artist_profile_cover.setStyleSheet("background:#151515;color:#777;font-size:42px;border-radius:9px;")
        header.addWidget(self.artist_profile_cover, 0, Qt.AlignmentFlag.AlignTop)
        meta = QVBoxLayout()
        self.artist_profile_kicker = QLabel("ARTISTA")
        self.artist_profile_kicker.setStyleSheet(f"color:{GREEN};font-size:10px;font-weight:900;letter-spacing:3px;")
        meta.addWidget(self.artist_profile_kicker)
        self.artist_profile_title = QLabel("Perfil do artista")
        self.artist_profile_title.setObjectName("heroTitle")
        self.artist_profile_title.setWordWrap(True)
        meta.addWidget(self.artist_profile_title)
        self.artist_profile_subtitle = QLabel("Artista e músicas disponíveis no YouTube Music")
        self.artist_profile_subtitle.setObjectName("muted")
        self.artist_profile_subtitle.setWordWrap(True)
        meta.addWidget(self.artist_profile_subtitle)
        self.artist_open_btn = QPushButton("Abrir perfil no YouTube Music ↗")
        self.artist_open_btn.setObjectName("greenButton")
        self.artist_open_btn.clicked.connect(self.open_artist_external)
        meta.addWidget(self.artist_open_btn, 0, Qt.AlignmentFlag.AlignLeft)
        meta.addStretch(1)
        header.addLayout(meta, 1)
        layout.addLayout(header)
        self.artist_profile_status = QLabel("Carregando discografia…")
        self.artist_profile_status.setObjectName("status")
        layout.addWidget(self.artist_profile_status)
        self.artist_albums_title = QLabel("Lançamentos")
        self.artist_albums_title.setObjectName("sectionTitle")
        layout.addWidget(self.artist_albums_title)
        self.artist_albums_grid = QGridLayout()
        self.artist_albums_grid.setSpacing(12)
        layout.addLayout(self.artist_albums_grid)
        self.artist_tracks_title = QLabel("Músicas")
        self.artist_tracks_title.setObjectName("sectionTitle")
        layout.addWidget(self.artist_tracks_title)
        self.artist_tracks_container = QWidget()
        self.artist_tracks_layout = QVBoxLayout(self.artist_tracks_container)
        self.artist_tracks_layout.setContentsMargins(0, 0, 0, 0)
        self.artist_tracks_layout.setSpacing(2)
        layout.addWidget(self.artist_tracks_container, 1)
        layout.addStretch(1)
        return self._scroll_page(content)

    def _build_queue_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("sidebar")
        panel.setFixedWidth(286)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(13, 18, 13, 12)
        title_row = QHBoxLayout()
        title = QLabel("Fila de reprodução")
        title.setStyleSheet("font-weight:800; font-size:14px;")
        title_row.addWidget(title, 1)
        close = QPushButton("×")
        close.setObjectName("roundButton")
        close.clicked.connect(self.toggle_queue)
        title_row.addWidget(close)
        layout.addLayout(title_row)
        current_label = QLabel("TOCANDO AGORA")
        current_label.setStyleSheet(f"font-size:9px; color:{GREEN}; font-weight:900; letter-spacing:2px; margin-top:16px;")
        layout.addWidget(current_label)
        self.queue_current = QLabel("Nada tocando")
        self.queue_current.setWordWrap(True)
        self.queue_current.setStyleSheet("font-size:12px; font-weight:700; padding:8px 0 14px;")
        layout.addWidget(self.queue_current)
        up_next = QLabel("PRÓXIMAS")
        up_next.setStyleSheet(f"font-size:9px; color:{MUTED}; font-weight:900; letter-spacing:2px;")
        layout.addWidget(up_next)
        self.queue_list = QListWidget()
        self.queue_list.itemDoubleClicked.connect(self._queue_item_activated)
        layout.addWidget(self.queue_list, 1)
        return panel

    def _build_playerbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("playerbar")
        bar.setStyleSheet(f"QFrame#playerbar {{ border-top:1px solid #202020; background:#050505; }}")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(14)
        self.now_cover = QLabel()
        self.covers.load("", self.now_cover, 48)
        layout.addWidget(self.now_cover)
        meta = QVBoxLayout()
        meta.setSpacing(4)
        self.now_title = QLabel("Nada tocando")
        self.now_title.setObjectName("trackTitle")
        self.now_title.setMaximumWidth(210)
        self.now_artist = QPushButton("Escolha uma faixa para começar")
        self.now_artist.setObjectName("artistLink")
        self.now_artist.setMaximumWidth(210)
        self.now_artist.setToolTip("Abrir perfil do artista ou canal de publicação")
        self.now_artist.clicked.connect(lambda checked=False: self.open_artist_profile(self.current_track) if self.current_track else None)
        meta.addWidget(self.now_title)
        meta.addWidget(self.now_artist)
        layout.addLayout(meta)
        self.like_btn = QPushButton("♡")
        self.like_btn.setObjectName("roundButton")
        self.like_btn.setToolTip("Curtir / descurtir")
        self.like_btn.clicked.connect(self.toggle_favorite)
        layout.addWidget(self.like_btn)
        center = QVBoxLayout()
        center.setSpacing(4)
        controls = QHBoxLayout()
        controls.setSpacing(10)
        controls.addStretch(1)
        self.shuffle_btn = QPushButton("⤨")
        self.shuffle_btn.setObjectName("roundButton")
        self.shuffle_btn.setToolTip("Embaralhar a fila")
        self.shuffle_btn.clicked.connect(self.shuffle_queue)
        controls.addWidget(self.shuffle_btn)
        self.previous_btn = QPushButton("|◀")
        self.previous_btn.setObjectName("roundButton")
        self.previous_btn.clicked.connect(self.play_previous)
        controls.addWidget(self.previous_btn)
        self.play_btn = QPushButton("▶")
        self.play_btn.setObjectName("playButton")
        self.play_btn.clicked.connect(self.toggle_play)
        controls.addWidget(self.play_btn)
        self.next_btn = QPushButton("▶| ")
        self.next_btn.setObjectName("roundButton")
        self.next_btn.clicked.connect(self.play_next)
        controls.addWidget(self.next_btn)
        controls.addStretch(1)
        center.addLayout(controls)
        progress_row = QHBoxLayout()
        self.elapsed_label = QLabel("0:00")
        self.elapsed_label.setObjectName("status")
        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setRange(0, 1000)
        self.progress_slider.sliderPressed.connect(self._begin_seek)
        self.progress_slider.sliderReleased.connect(self._finish_seek)
        self.total_label = QLabel("0:00")
        self.total_label.setObjectName("status")
        progress_row.addWidget(self.elapsed_label)
        progress_row.addWidget(self.progress_slider, 1)
        progress_row.addWidget(self.total_label)
        center.addLayout(progress_row)
        layout.addLayout(center, 1)
        volume_layout = QHBoxLayout()
        self.queue_btn = QPushButton("☷")
        self.queue_btn.setObjectName("roundButton")
        self.queue_btn.setToolTip("Fila")
        self.queue_btn.clicked.connect(self.toggle_queue)
        volume_layout.addWidget(self.queue_btn)
        volume_layout.addWidget(QLabel("◖"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(72)
        self.volume_slider.setFixedWidth(90)
        self.volume_slider.valueChanged.connect(lambda value: self._ipc(["set_property", "volume", value]))
        volume_layout.addWidget(self.volume_slider)
        layout.addLayout(volume_layout)
        bar.setMinimumHeight(80)
        return bar

    def status(self, text: str) -> None:
        self.statusBar().showMessage(text, 6500)

    def navigate(self, key: str) -> None:
        previous = self.current_section
        if not self._navigating_back and previous != key:
            self.navigation_history.append(previous)
            self.navigation_history = self.navigation_history[-30:]
        self.current_section = key
        idx = {"home": 0, "search": 1, "library": 2, "lyrics": 3, "artist": 4}.get(key, 0)
        self.pages.setCurrentIndex(idx)
        self.nav_buttons["home"].setChecked(key == "home")
        if key == "lyrics":
            if self.sidebar.isVisible():
                self.sidebar.hide()
            if self.queue_panel.isVisible():
                self._queue_restore_after_lyrics = True
                self.queue_panel.hide()
            if self.current_track and (not self.lyric_labels or self._lyrics_for_track != self._track_key(self.current_track)):
                self.fetch_lyrics(self.current_track)
        else:
            self.sidebar.show()
            if self._queue_restore_after_lyrics:
                self.queue_panel.show()
                self._queue_restore_after_lyrics = False
        if key == "library":
            self.refresh_library()

    def go_back(self) -> None:
        while self.navigation_history:
            key = self.navigation_history.pop()
            if key != self.current_section:
                self._navigating_back = True
                try:
                    self.navigate(key)
                finally:
                    self._navigating_back = False
                return
        self._navigating_back = True
        try:
            self.navigate("home")
        finally:
            self._navigating_back = False

    def create_playlist(self) -> str | None:
        name, accepted = QInputDialog.getText(self, "Nova playlist", "Nome da playlist:")
        name = (name or "").strip()
        if not accepted or not name:
            return None
        if any(p.get("name", "").casefold() == name.casefold() for p in self.playlists):
            QMessageBox.information(self, APP_NAME, "Já existe uma playlist com esse nome.")
            return None
        playlist = {"id": uuid.uuid4().hex, "name": name, "tracks": []}
        self.playlists.append(playlist)
        self.selected_collection = playlist["id"]
        self._save_state()
        self.refresh_sidebar_playlists()
        self.navigate("library")
        self.refresh_library()
        self.status(f'Playlist criada: {name}')
        return playlist["id"]

    def open_collection(self, collection_id: str) -> None:
        self.selected_collection = collection_id
        self.navigate("library")
        self.refresh_library()
        self.refresh_sidebar_playlists()

    def refresh_sidebar_playlists(self) -> None:
        if not hasattr(self, "sidebar_playlist_layout"):
            return
        self._clear_layout(self.sidebar_playlist_layout)
        entries: list[tuple[str, str, str, dict[str, Any] | None]] = [
            ("liked", "♥", "Músicas curtidas", self.favorites[0] if self.favorites else None),
            ("recent", "◷", "Tocadas recentemente", self.recent[0] if self.recent else None),
        ]
        entries.extend((str(p["id"]), "♫", str(p["name"]), (p.get("tracks") or [None])[0]) for p in self.playlists)
        for collection_id, symbol, name, sample_track in entries:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(7)
            icon = QLabel()
            if sample_track and (sample_track.get("thumbnail") or sample_track.get("id")):
                thumbnail, fallback_thumbnail = thumbnail_sources(sample_track)
                self.covers.load(thumbnail, icon, 30, fallback_thumbnail, cover_video_id(sample_track))
            else:
                icon.setFixedSize(30, 30)
                icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
                icon.setText(symbol)
                icon.setStyleSheet("background:#202020; border-radius:4px; color:#cfcfcf; font-size:15px;")
            row_layout.addWidget(icon)
            button = QPushButton(name)
            button.setObjectName("playlistNav")
            button.setCheckable(True)
            button.setChecked(collection_id == self.selected_collection)
            button.setToolTip(name)
            button.clicked.connect(lambda checked=False, cid=collection_id: self.open_collection(cid))
            row_layout.addWidget(button, 1)
            self.sidebar_playlist_layout.addWidget(row)
        self.sidebar_playlist_layout.addStretch(1)

    def add_track_to_playlist(self, track: dict[str, Any]) -> None:
        menu = QMenu(self)
        custom_actions: dict[Any, str] = {}
        if self.playlists:
            submenu = menu.addMenu("Adicionar a playlist")
            for playlist in self.playlists:
                action = submenu.addAction(str(playlist.get("name", "Playlist")))
                custom_actions[action] = str(playlist.get("id"))
        create_action = menu.addAction("Criar nova playlist…")
        chosen = menu.exec(self.mapToGlobal(self.rect().center()))
        if chosen == create_action:
            playlist_id = self.create_playlist()
            playlist = next((p for p in self.playlists if p.get("id") == playlist_id), None)
            if playlist:
                self._append_track_to_playlist(playlist, track)
        elif chosen in custom_actions:
            playlist = next((p for p in self.playlists if str(p.get("id")) == custom_actions[chosen]), None)
            if playlist:
                self._append_track_to_playlist(playlist, track)

    def _append_track_to_playlist(self, playlist: dict[str, Any], track: dict[str, Any]) -> None:
        tracks = playlist.setdefault("tracks", [])
        key = self._track_key(track)
        if not any(self._track_key(existing) == key for existing in tracks):
            tracks.insert(0, dict(track))
            playlist["tracks"] = tracks[:500]
            self._save_state()
            self.refresh_sidebar_playlists()
            if self.selected_collection == playlist.get("id"):
                self.refresh_library()
            self.status(f'Adicionada a {playlist.get("name", "playlist")}')
        else:
            self.status("Essa faixa já está na playlist")

    def show_track_context_menu(self, track: dict[str, Any], global_pos: Any) -> None:
        menu = QMenu(self)
        play_action = menu.addAction("Reproduzir agora")
        queue_action = menu.addAction("Adicionar à fila")
        menu.addSeparator()
        favorite_action = menu.addAction("Remover das curtidas" if self._find_favorite_index(track) >= 0 else "Adicionar às curtidas")
        playlist_menu = menu.addMenu("Adicionar à playlist")
        playlist_actions: dict[Any, str] = {}
        for playlist in self.playlists:
            action = playlist_menu.addAction(str(playlist.get("name", "Playlist")))
            playlist_actions[action] = str(playlist.get("id"))
        if not self.playlists:
            no_lists = playlist_menu.addAction("Criar uma playlist primeiro")
            no_lists.setEnabled(False)
        playlist_menu.addSeparator()
        create_action = playlist_menu.addAction("Criar nova playlist…")
        chosen = menu.exec(global_pos)
        if chosen == play_action:
            self.play_track(track)
        elif chosen == queue_action:
            self.add_to_queue(track)
        elif chosen == favorite_action:
            idx = self._find_favorite_index(track)
            if idx >= 0:
                self.favorites.pop(idx)
            else:
                self.favorites.insert(0, dict(track))
            self._save_state()
            self.refresh_library()
            self.refresh_sidebar_playlists()
        elif chosen == create_action:
            playlist_id = self.create_playlist()
            playlist = next((p for p in self.playlists if p.get("id") == playlist_id), None)
            if playlist:
                self._append_track_to_playlist(playlist, track)
        elif chosen in playlist_actions:
            playlist = next((p for p in self.playlists if str(p.get("id")) == playlist_actions[chosen]), None)
            if playlist:
                self._append_track_to_playlist(playlist, track)

    def toggle_queue(self) -> None:
        self.queue_panel.setVisible(not self.queue_panel.isVisible())
        if self.queue_panel.isVisible():
            self.refresh_queue()
        if self.current_section == "lyrics":
            self._queue_restore_after_lyrics = self.queue_panel.isVisible()

    def _track_key(self, track: dict[str, Any]) -> str:
        return str(track.get("id") or f"{track.get('title')}::{track.get('artist')}")

    def focus_search(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def search(self, query: str, show_page: bool = True) -> None:
        query = query.strip()
        if not query:
            return
        if show_page:
            self.navigate("search")
        self.latest_search_query = query
        self.results = []
        self._clear_layout(self.results_layout)
        self._clear_layout(self.artist_results_layout)
        self.search_page_title.setText("Buscar músicas")
        self.search_info.setText("Resultados do YouTube Music: faixas oficiais, vídeos e versões publicadas por canais.")
        self.search_status.setText(f'Pesquisando no YouTube Music: “{query}”…')
        self.status(f'Pesquisando “{query}”…')
        worker = YouTubeSearchWorker(query)
        self._keep_worker(worker)
        worker.done.connect(self._search_worker_done)
        worker.start()

    @pyqtSlot(list, str, list)
    def _search_worker_done(self, tracks: list[dict[str, Any]], error: str, artists: list[dict[str, Any]]) -> None:
        sender = self.sender()
        query = getattr(sender, "query", "")
        self._search_done(query, tracks, error, artists)

    def _keep_worker(self, worker: QThread) -> None:
        self.active_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._remove_worker(w))

    def _remove_worker(self, worker: QThread) -> None:
        if worker in self.active_workers:
            self.active_workers.remove(worker)
        worker.deleteLater()

    def _search_done(self, query: str, tracks: list[dict[str, Any]], error: str, artists: list[dict[str, Any]] | None = None) -> None:
        if self.latest_search_query and query != self.latest_search_query:
            return
        if error and not tracks and not artists:
            self.search_status.setText(error)
            self.status(error)
            return
        self.results = tracks
        self.search_status.setText(f'{len(tracks)} resultados de músicas e vídeos para “{query}”')
        self._populate_search_artists(artists or [])
        self._populate_track_list(self.results_layout, tracks)
        if not tracks and not artists:
            self.search_status.setText("Nenhuma música ou artista encontrado. Tente o título, nome do artista ou uma versão ao vivo/remix.")
        elif error:
            self.search_status.setText(error)
        self.status(f"Encontrados {len(tracks)} resultados")
        if tracks:
            self._hydrate_creator_metadata(query, tracks)

    def _hydrate_creator_metadata(self, query: str, tracks: list[dict[str, Any]]) -> None:
        worker = ChannelMetadataWorker(query, tracks)
        self._keep_worker(worker)
        worker.done.connect(self._search_channels_done)
        worker.start()

    @pyqtSlot(str, list)
    def _search_channels_done(self, query: str, channels: list[dict[str, Any]]) -> None:
        if query != self.latest_search_query or not channels:
            return
        metadata_by_id = {str(item.get("id") or ""): item for item in channels if item.get("id")}
        if not metadata_by_id:
            return

        collections: list[list[dict[str, Any]]] = [self.results, self.queue, self.favorites, self.recent]
        for playlist in self.playlists:
            playlist_tracks = playlist.get("tracks") or []
            if isinstance(playlist_tracks, list):
                collections.append(playlist_tracks)
        for tracks_here in collections:
            for track in tracks_here:
                metadata = metadata_by_id.get(str(track.get("youtube_id") or track.get("id") or ""))
                if not metadata:
                    continue
                if metadata.get("creator"):
                    track["creator"] = metadata["creator"]
                if metadata.get("creator_profile"):
                    track["creator_profile"] = dict(metadata["creator_profile"])
        for row in self.findChildren(TrackRow):
            metadata = metadata_by_id.get(str(row.track.get("youtube_id") or row.track.get("id") or ""))
            if metadata:
                row.track.update({key: value for key, value in metadata.items() if key != "id"})
                row.update_author_label()
        for card in self.findChildren(RecommendationCard):
            metadata = metadata_by_id.get(str(card.track.get("youtube_id") or card.track.get("id") or ""))
            if metadata:
                card.track.update({key: value for key, value in metadata.items() if key != "id"})
                card.update_author_label()
        self.refresh_queue()
        self._save_state()

    def _populate_search_artists(self, artists: list[dict[str, Any]]) -> None:
        self._clear_layout(self.artist_results_layout)
        if not artists:
            return
        title = QLabel("Artistas")
        title.setObjectName("sectionTitle")
        title.setStyleSheet("font-size:18px;")
        self.artist_results_layout.addWidget(title)
        for artist in artists[:8]:
            card = QFrame()
            card.setObjectName("trackRow")
            row = QHBoxLayout(card)
            row.setContentsMargins(7, 5, 7, 5)
            row.setSpacing(10)
            cover = QLabel()
            self.covers.load(str(artist.get("image") or ""), cover, 44)
            row.addWidget(cover)
            name_btn = QPushButton(str(artist.get("name") or "Artista"))
            name_btn.setObjectName("artistLink")
            name_btn.setStyleSheet(f"color:{TEXT};font-size:13px;font-weight:750;text-align:left;padding:5px 0;")
            name_btn.clicked.connect(lambda checked=False, a=artist: self.open_artist_profile(a))
            row.addWidget(name_btn, 1)
            open_btn = QPushButton("Ver perfil →")
            open_btn.setStyleSheet(f"color:{MUTED};font-size:11px;")
            open_btn.clicked.connect(lambda checked=False, a=artist: self.open_artist_profile(a))
            row.addWidget(open_btn)
            self.artist_results_layout.addWidget(card)

    def open_artist_profile(self, track_or_artist: dict[str, Any]) -> None:
        """Open the performer page for the exact row/card that was clicked."""
        source = dict(track_or_artist)
        if str(source.get("profile_type") or "") == "channel":
            # Channel pages are opened only by the dedicated publisher link.
            self.open_creator_profile(source)
            return
        artist = artist_profile_for_track(source)
        self._open_profile_page(artist)

    def open_creator_profile(self, track_or_creator: dict[str, Any]) -> None:
        """Open the channel that uploaded a version, never the performing artist."""
        source = dict(track_or_creator)
        if str(source.get("profile_type") or "") == "channel":
            profile = dict(source)
        else:
            creator = creator_profile_for_track(source)
            profile = {
                "id": str(creator.get("id") or ""),
                "name": str(creator.get("name") or source.get("creator") or "Canal do YouTube"),
                "url": str(creator.get("url") or ""),
                "image": str(creator.get("avatar") or ""),
                "provider": "youtube",
                "profile_type": "channel",
            }
        if not profile.get("name"):
            self.status("Ainda não há dados do canal que publicou esta versão.")
            return
        self._open_profile_page(profile)

    def _open_profile_page(self, profile: dict[str, Any]) -> None:
        self._profile_artist = dict(profile)
        self._clear_layout(self.artist_tracks_layout)
        self._clear_layout(self.artist_albums_grid)
        self.artist_profile_title.setText(str(profile.get("name") or "Artista"))
        if profile.get("profile_type") == "channel":
            self.artist_profile_subtitle.setText("Canal do YouTube · vídeos e músicas publicados")
            self.artist_open_btn.setText("Abrir canal no YouTube ↗")
            self.channel_avatars.load(profile, self.artist_profile_cover, 144)
        else:
            self.artist_profile_subtitle.setText("Artista no YouTube Music · músicas e lançamentos")
            self.artist_open_btn.setText("Abrir perfil no YouTube Music ↗")
            self.covers.load(str(profile.get("image") or ""), self.artist_profile_cover, 144)
        self.artist_profile_status.setText("Carregando músicas e publicações…")
        self.artist_open_btn.setEnabled(bool(profile.get("url") or profile.get("id")))
        self.navigate("artist")
        worker = YouTubeArtistProfileWorker(profile)
        self._keep_worker(worker)
        worker.done.connect(self._artist_profile_done)
        worker.start()

    @pyqtSlot(dict, list, list, str)
    def _artist_profile_done(self, artist: dict[str, Any], tracks: list[dict[str, Any]], albums: list[dict[str, Any]], error: str) -> None:
        self._profile_artist = artist or self._profile_artist
        self.artist_profile_title.setText(str(self._profile_artist.get("name") or "Artista"))
        is_channel = str(self._profile_artist.get("profile_type") or "") == "channel"
        if is_channel:
            self.artist_profile_subtitle.setText("Vídeos e músicas publicados por este canal")
            self.artist_open_btn.setText("Abrir canal no YouTube ↗")
        else:
            self.artist_profile_subtitle.setText("Perfil do artista · catálogo do YouTube Music")
            self.artist_open_btn.setText("Abrir perfil no YouTube Music ↗")
        self.artist_open_btn.setEnabled(bool(self._profile_artist.get("url")))
        if is_channel:
            self.channel_avatars.load(self._profile_artist, self.artist_profile_cover, 144)
        else:
            self.covers.load(str(self._profile_artist.get("image") or ""), self.artist_profile_cover, 144)
        self._clear_layout(self.artist_albums_grid)
        self.artist_albums_title.setVisible(bool(albums))
        self.artist_tracks_title.setText("Publicações do canal" if is_channel else "Músicas")
        for index, album in enumerate(albums[:9]):
            card = QFrame()
            card.setObjectName("artCard")
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(8, 8, 8, 8)
            card_layout.setSpacing(5)
            cover = QLabel()
            self.covers.load(str(album.get("thumbnail") or ""), cover, 94)
            card_layout.addWidget(cover, 0, Qt.AlignmentFlag.AlignHCenter)
            title = QLabel(str(album.get("name") or "Lançamento"))
            title.setWordWrap(True)
            title.setMaximumHeight(35)
            title.setStyleSheet("font-size:11px;font-weight:750;")
            card_layout.addWidget(title)
            date = QLabel(str(album.get("release_date") or ""))
            date.setObjectName("muted")
            date.setStyleSheet(f"color:{MUTED};font-size:10px;")
            card_layout.addWidget(date)
            card.mousePressEvent = lambda event, u=album.get("url", ""): QDesktopServices.openUrl(QUrl(str(u))) if event.button() == Qt.MouseButton.LeftButton and u else None
            self.artist_albums_grid.addWidget(card, index // 3, index % 3)
        self._clear_layout(self.artist_tracks_layout)
        for index, track in enumerate(tracks):
            row = TrackRow(track, self.covers, index, avatars=self.channel_avatars)
            row.play_clicked.connect(lambda t=track, ts=tracks, i=index: self.play_from_list(t, list(ts), i))
            row.queue_clicked.connect(lambda t=track: self.add_to_queue(t))
            row.artist_clicked.connect(self.open_artist_profile)
            row.creator_clicked.connect(self.open_creator_profile)
            row.context_menu_requested.connect(self.show_track_context_menu)
            self.artist_tracks_layout.addWidget(row)
        self.artist_tracks_layout.addStretch(1)
        if error and not tracks:
            self.artist_profile_status.setText(error)
        else:
            self.artist_profile_status.setText(f"{len(albums)} lançamentos · {len(tracks)} faixas/publicações")
        self.status(f"Perfil carregado: {self._profile_artist.get('name', 'artista')}")

    def open_artist_external(self) -> None:
        url = str(self._profile_artist.get("url") or "")
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def load_discovery(self) -> None:
        if not hasattr(self, "discovery_container"):
            return
        styles = select_discovery_styles(self.favorites, self.recent, limit=4)
        top_artist = most_listened_artist(self.favorites, self.recent)
        if top_artist:
            artist_key = _normalise_search_text(top_artist).replace(" ", "_")
            plan = [{"id": f"artist_{artist_key}", "name": f"Mais de {top_artist}", "query": top_artist, "kind": "artist"}] + styles[:3]
        else:
            plan = styles
        signature = tuple(str(style.get("id")) for style in plan)
        if self.discovery_worker and self.discovery_worker.isRunning():
            # Retry after the current background request completes if the taste profile changed.
            if signature != self.discovery_signature:
                self._discovery_refresh_pending = True
            return
        if signature == self.discovery_signature and self.discovery_layout.count() > 0:
            return
        self.discovery_signature = signature
        self.discovery_status.setText("Aprendendo seu gosto musical…" if self.favorites or self.recent else "Explorando estilos diferentes para conhecer seu gosto…")
        worker = DiscoveryWorker(plan)
        self.discovery_worker = worker
        self._keep_worker(worker)
        worker.done.connect(self._discovery_done)
        worker.start()

    @pyqtSlot(list, str)
    def _discovery_done(self, sections: list[dict[str, Any]], error: str) -> None:
        self.discovery_worker = None
        self._clear_layout(self.discovery_layout)
        if not sections:
            self.discovery_status.setText(error or "Não há recomendações disponíveis neste momento.")
            if getattr(self, "_discovery_refresh_pending", False):
                self._discovery_refresh_pending = False
                QTimer.singleShot(500, self.load_discovery)
            return
        for section in sections:
            heading_row = QHBoxLayout()
            heading = QLabel(str(section.get("name") or "Para você"))
            heading.setObjectName("sectionTitle")
            heading_row.addWidget(heading)
            heading_row.addStretch(1)
            self.discovery_layout.addLayout(heading_row)
            strip = QWidget()
            strip_layout = QHBoxLayout(strip)
            strip_layout.setContentsMargins(0, 0, 0, 0)
            strip_layout.setSpacing(10)
            tracks = list(section.get("tracks") or [])
            for index, track in enumerate(tracks):
                card = RecommendationCard(track, self.covers, avatars=self.channel_avatars)
                card.play_clicked.connect(lambda t, ts=tracks, i=index: self.play_from_list(t, list(ts), i))
                card.queue_clicked.connect(lambda t: self.add_to_queue(t))
                card.artist_clicked.connect(self.open_artist_profile)
                card.creator_clicked.connect(self.open_creator_profile)
                strip_layout.addWidget(card)
            strip_layout.addStretch(1)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFixedHeight(276)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(strip)
            self.discovery_layout.addWidget(scroll)
        if self.favorites or self.recent:
            self.discovery_status.setText("Recomendações ajustadas às suas curtidas e ao histórico recente. Elas mudam com o tempo.")
        else:
            self.discovery_status.setText("Sugestões variadas para começar — as próximas vão se adaptar ao que você ouvir e curtir.")
        if getattr(self, "_discovery_refresh_pending", False):
            self._discovery_refresh_pending = False
            QTimer.singleShot(500, self.load_discovery)

    def _clear_layout(self, layout: Any) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget:
                widget.deleteLater()
            elif child_layout:
                self._clear_layout(child_layout)
                child_layout.deleteLater()

    def _populate_track_list(self, layout: QVBoxLayout, tracks: list[dict[str, Any]]) -> None:
        self._clear_layout(layout)
        for idx, track in enumerate(tracks):
            row = TrackRow(track, self.covers, idx, avatars=self.channel_avatars)
            row.play_clicked.connect(lambda t=track, ts=tracks, i=idx: self.play_from_list(t, ts, i))
            row.queue_clicked.connect(lambda t=track: self.add_to_queue(t))
            row.artist_clicked.connect(self.open_artist_profile)
            row.creator_clicked.connect(self.open_creator_profile)
            row.playlist_add_requested.connect(self.add_track_to_playlist)
            row.context_menu_requested.connect(self.show_track_context_menu)
            layout.addWidget(row)
        layout.addStretch(1)

    def _find_favorite_index(self, track: dict[str, Any]) -> int:
        key = self._track_key(track)
        for index, item in enumerate(self.favorites):
            if self._track_key(item) == key:
                return index
        return -1

    def play_from_list(self, track: dict[str, Any], tracks: list[dict[str, Any]], index: int) -> None:
        self.queue = list(tracks)
        self.queue_index = index
        self.refresh_queue()
        self.play_track(track)

    def play_track(self, track: dict[str, Any]) -> None:
        self.status(f"Abrindo: {track.get('title', 'faixa')}…")
        self.play_btn.setText("…")
        worker = StreamWorker(track)
        self._keep_worker(worker)
        worker.done.connect(self._stream_done)
        worker.start()

    def _stream_done(self, result: dict[str, Any], error: str) -> None:
        if error:
            self.play_btn.setText("▶")
            self.status(error)
            QMessageBox.warning(self, APP_NAME, error)
            return
        track = result["track"]
        # Preserve the resolved YouTube video ID on the queued copy for artwork fallbacks.
        resolved_key = self._track_key(track)
        for queue_pos, queued_track in enumerate(self.queue):
            if self._track_key(queued_track) == resolved_key:
                # Mutate the existing metadata object too; rows in search/library keep
                # a reference to it, so their author link learns the resolved uploader.
                for key in ("youtube_id", "youtube_url", "thumbnail_fallback", "url", "creator", "creator_profile"):
                    if track.get(key):
                        queued_track[key] = track[key]
                if track.get("thumbnail") and not queued_track.get("thumbnail"):
                    queued_track["thumbnail"] = track["thumbnail"]
                self.queue[queue_pos] = queued_track
        for track_row in self.findChildren(TrackRow):
            if self._track_key(track_row.track) == resolved_key:
                track_row.track.update({key: value for key, value in track.items() if key in {"creator", "creator_profile", "youtube_id", "youtube_url", "thumbnail_fallback"}})
                track_row.update_author_label()
        for card in self.findChildren(RecommendationCard):
            if self._track_key(card.track) == resolved_key:
                card.track.update({key: value for key, value in track.items() if key in {"creator", "creator_profile", "youtube_id", "youtube_url", "thumbnail_fallback"}})
                card.update_author_label()
        self.current_track = track
        self._handled_eof_for = None
        self.current_stream = result["stream_url"]
        self._start_mpv()
        self.play_btn.setText("Ⅱ")
        self.now_title.setText(track.get("title", "Faixa"))
        self.now_artist.setText(str(artist_profile_for_track(track).get("name") or track.get("artist") or "Artista desconhecido"))
        self.now_artist.setToolTip("Abrir o perfil do artista da música")
        thumbnail, fallback_thumbnail = thumbnail_sources(track)
        self.covers.load(thumbnail, self.now_cover, 48, fallback_thumbnail, cover_video_id(track))
        self.like_btn.setText("♥" if self._find_favorite_index(track) >= 0 else "♡")
        self.total_label.setText(fmt_time(track.get("duration")))
        self.elapsed_label.setText("0:00")
        self.progress_slider.setValue(0)
        self.recent = [track] + [t for t in self.recent if self._track_key(t) != self._track_key(track)]
        self.recent = self.recent[:60]
        self._save_state()
        if hasattr(self, "discovery_refresh_timer"):
            self.discovery_refresh_timer.start(2200)
        self.refresh_sidebar_playlists()
        self.queue_current.setText(f"{track.get('title')}\n{track.get('artist')}")
        self.refresh_queue()
        self.fetch_lyrics(track)
        self.status(f"Tocando: {track.get('title')}")

    def _start_mpv(self) -> None:
        if self._mpv_ready and self.mpv_process is not None and self.mpv_process.poll() is None:
            pass
        else:
            try:
                Path(IPC_FILE).unlink(missing_ok=True)
            except OSError:
                pass
            try:
                self.mpv_process = subprocess.Popen(
                    ["mpv", "--no-video", "--force-window=no", "--idle=yes", "--keep-open=no",
                     "--really-quiet", f"--input-ipc-server={IPC_FILE}"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except FileNotFoundError:
                QMessageBox.critical(self, APP_NAME, "O mpv não está instalado. Instale com: sudo pacman -S mpv")
                self._mpv_ready = False
                return
            self._mpv_ready = True
        QTimer.singleShot(300, lambda u=self.current_stream: self._load_stream(u))

    def _load_stream(self, url: str) -> None:
        if not url:
            return
        ok = self._ipc(["loadfile", url, "replace"])
        if not ok:
            QTimer.singleShot(500, lambda u=url: self._ipc(["loadfile", u, "replace"]))
        self._ipc(["set_property", "volume", self.volume_slider.value()])

    def _ipc(self, command: list[Any], want_value: bool = False) -> Any:
        if not getattr(self, "_mpv_ready", False):
            return None
        try:
            request_id = int(time.time() * 1000) % 2_000_000_000
            data = json.dumps({"command": command, "request_id": request_id}) + "\n"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(0.22)
                client.connect(IPC_FILE)
                client.sendall(data.encode("utf-8"))
                if not want_value:
                    return True
                buffer = b""
                deadline = time.monotonic() + 0.22
                while time.monotonic() < deadline:
                    try:
                        chunk = client.recv(4096)
                        if not chunk:
                            break
                        buffer += chunk
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            try:
                                payload = json.loads(line.decode("utf-8"))
                            except json.JSONDecodeError:
                                continue
                            if payload.get("request_id") == request_id:
                                return payload.get("data")
                    except socket.timeout:
                        break
        except (OSError, ConnectionError):
            return None
        return None

    def toggle_play(self) -> None:
        if not self.current_track:
            if self.results:
                self.play_from_list(self.results[0], self.results, 0)
            else:
                self.focus_search()
            return
        paused = self._ipc(["get_property", "pause"], want_value=True)
        if paused is None:
            self._ipc(["set_property", "pause", False])
            self.play_btn.setText("Ⅱ")
        else:
            self._ipc(["set_property", "pause", not bool(paused)])
            self.play_btn.setText("▶" if not paused else "Ⅱ")

    def _poll_player(self) -> None:
        if not self.current_track or not self._mpv_ready:
            return
        position = self._ipc(["get_property", "time-pos"], want_value=True)
        duration = self._ipc(["get_property", "duration"], want_value=True)
        if isinstance(position, (float, int)):
            self.elapsed_label.setText(fmt_time(position))
            if isinstance(duration, (float, int)) and duration > 0 and not self.progress_slider.isSliderDown():
                self.progress_slider.setValue(max(0, min(1000, int(position / duration * 1000))))
            if self.lyric_times:
                self._highlight_lyric(float(position))
        if isinstance(duration, (float, int)) and duration > 0:
            self.total_label.setText(fmt_time(duration))
        eof = self._ipc(["get_property", "eof-reached"], want_value=True)
        current_key = self._track_key(self.current_track)
        if eof is True and self._handled_eof_for != current_key:
            self._handled_eof_for = current_key
            self.play_next()

    def _begin_seek(self) -> None:
        self._seek_duration = self._ipc(["get_property", "duration"], want_value=True)

    def _finish_seek(self) -> None:
        duration = getattr(self, "_seek_duration", None)
        if isinstance(duration, (float, int)) and duration > 0:
            target = duration * self.progress_slider.value() / 1000
            self._ipc(["seek", target, "absolute"])

    def play_next(self) -> None:
        if not self.queue:
            return
        if self.current_track is None:
            self.queue_index = max(0, self.queue_index)
        else:
            self.queue_index = (self.queue_index + 1) % len(self.queue)
        self.play_track(self.queue[self.queue_index])

    def play_previous(self) -> None:
        position = self._ipc(["get_property", "time-pos"], want_value=True)
        if isinstance(position, (int, float)) and position > 4:
            self._ipc(["seek", 0, "absolute"])
            return
        if self.queue:
            self.queue_index = (self.queue_index - 1) % len(self.queue)
            self.play_track(self.queue[self.queue_index])

    def shuffle_queue(self) -> None:
        import random
        if len(self.queue) > 1:
            current = self.current_track
            random.shuffle(self.queue)
            if current:
                self.queue_index = next((i for i, t in enumerate(self.queue) if self._track_key(t) == self._track_key(current)), 0)
            self.refresh_queue()
            self.status("Fila embaralhada")

    def add_to_queue(self, track: dict[str, Any]) -> None:
        self.queue.append(track)
        if self.queue_index < 0:
            self.queue_index = 0
        self.refresh_queue()
        self.status(f"Adicionada à fila: {track.get('title')}")

    def refresh_queue(self) -> None:
        if not hasattr(self, "queue_list"):
            return
        self.queue_list.clear()
        for index, track in enumerate(self.queue):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setSizeHint(QSize(252, 88))
            self.queue_list.addItem(item)
            row = QWidget()
            row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(2, 2, 2, 2)
            row_layout.setSpacing(8)
            cover = QLabel()
            cover.setToolTip(str(track.get("title") or "Capa da faixa"))
            thumbnail, fallback_thumbnail = thumbnail_sources(track)
            self.covers.load(thumbnail, cover, 48, fallback_thumbnail, cover_video_id(track))
            row_layout.addWidget(cover)
            labels = QVBoxLayout()
            labels.setContentsMargins(0, 1, 0, 1)
            labels.setSpacing(2)
            title = QLabel(str(track.get("title") or "Faixa"))
            title.setStyleSheet("font-size:11px;font-weight:750;")
            title.setWordWrap(False)
            title.setMaximumWidth(154)
            title.setToolTip(str(track.get("title") or "Faixa"))
            labels.addWidget(title)
            artist_name = str(artist_profile_for_track(track).get("name") or "Artista desconhecido")
            artist_label = QLabel(artist_name)
            artist_label.setStyleSheet(f"font-size:10px;color:{GREEN if index == self.queue_index else MUTED};")
            artist_label.setWordWrap(False)
            artist_label.setMaximumWidth(154)
            artist_label.setToolTip(f"Artista: {artist_name}")
            labels.addWidget(artist_label)
            row_layout.addLayout(labels, 1)
            creator_profile = creator_profile_for_track(track)
            creator_name = str(creator_profile.get("name") or "").strip()
            if creator_name:
                creator_row = QHBoxLayout()
                creator_row.setContentsMargins(0, 0, 0, 0)
                creator_row.setSpacing(4)
                avatar = QLabel()
                avatar.setFixedSize(16, 16)
                self.channel_avatars.load(creator_profile, avatar, 16)
                creator_row.addWidget(avatar)
                publisher = QLabel(f"{creator_name}")
                publisher.setStyleSheet(f"font-size:9px;color:{MUTED};")
                publisher.setWordWrap(False)
                publisher.setMaximumWidth(136)
                publisher.setToolTip(f"Publicado por: {creator_name}")
                creator_row.addWidget(publisher, 1)
                labels.addLayout(creator_row)
            if index == self.queue_index:
                marker = QLabel("▶")
                marker.setStyleSheet(f"color:{GREEN};font-size:12px;")
                row_layout.addWidget(marker)
            self.queue_list.setItemWidget(item, row)

    def _queue_item_activated(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(index, int) and 0 <= index < len(self.queue):
            self.queue_index = index
            self.play_track(self.queue[index])

    def toggle_favorite(self) -> None:
        if not self.current_track:
            return
        index = self._find_favorite_index(self.current_track)
        if index >= 0:
            self.favorites.pop(index)
            self.like_btn.setText("♡")
            self.status("Removida da biblioteca")
        else:
            self.favorites.insert(0, dict(self.current_track))
            self.like_btn.setText("♥")
            self.status("Adicionada à biblioteca")
        self._save_state()
        self.refresh_library()
        self.refresh_sidebar_playlists()

    def refresh_library(self) -> None:
        if not hasattr(self, "library_layout"):
            return
        self._clear_layout(self.library_layout)
        collection_id = self.selected_collection
        if collection_id == "liked":
            name, tracks, description = "Músicas curtidas", list(self.favorites), "Faixas que você marcou com ♥."
        elif collection_id == "recent":
            name, tracks, description = "Tocadas recentemente", list(self.recent), "O que você ouviu por último neste dispositivo."
        else:
            playlist = next((p for p in self.playlists if str(p.get("id")) == str(collection_id)), None)
            if playlist is None:
                self.selected_collection = "liked"
                name, tracks, description = "Músicas curtidas", list(self.favorites), "Faixas que você marcou com ♥."
            else:
                name = str(playlist.get("name", "Playlist"))
                tracks = list(playlist.get("tracks", []))
                description = f"{len(tracks)} música(s) nesta playlist. Clique com o botão direito numa faixa para gerenciá-la."
        self.library_title.setText(name)
        self.library_subtitle.setText(description)
        if not tracks:
            empty = QLabel("Esta playlist ainda está vazia.\nPesquise músicas e clique com o botão direito para adicioná-las.")
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color:{MUTED}; padding:22px; font-size:13px;")
            self.library_layout.addWidget(empty)
        else:
            for i, track in enumerate(tracks):
                row = TrackRow(track, self.covers, i, avatars=self.channel_avatars)
                row.play_clicked.connect(lambda t=track, ts=tracks, idx=i: self.play_from_list(t, list(ts), idx))
                row.queue_clicked.connect(lambda t=track: self.add_to_queue(t))
                row.artist_clicked.connect(self.open_artist_profile)
                row.creator_clicked.connect(self.open_creator_profile)
                row.playlist_add_requested.connect(self.add_track_to_playlist)
                row.context_menu_requested.connect(self.show_track_context_menu)
                self.library_layout.addWidget(row)
        self.library_layout.addStretch(1)
        self.refresh_sidebar_playlists()

    def fetch_lyrics(self, track: dict[str, Any]) -> None:
        self._lyrics_for_track = self._track_key(track)
        self.lyrics_track.setText(track.get("title", "Faixa"))
        self.lyrics_artist.setText(track.get("artist", ""))
        self._clear_layout(self.lyrics_layout)
        self.lyric_labels = []
        self.lyric_times = []
        loading = QLabel("Buscando letras…")
        loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading.setObjectName("muted")
        self.lyrics_layout.addWidget(loading)
        worker = LyricsWorker(track)
        self._keep_worker(worker)
        expected_track_key = self._track_key(track)
        worker.done.connect(lambda data, error, key=expected_track_key: self._lyrics_done(data, error, key))
        worker.start()

    def _lyrics_done(self, data: dict[str, Any], error: str, track_key: str | None = None) -> None:
        if track_key and self.current_track and self._track_key(self.current_track) != track_key:
            return
        self._clear_layout(self.lyrics_layout)
        self.lyric_labels = []
        self.lyric_times = []
        synced = data.get("syncedLyrics") if data else None
        plain = data.get("plainLyrics") if data else None
        if synced:
            self.lyric_times = parse_lrc(synced)
            for _timestamp, line in self.lyric_times:
                label = QLabel(line or "♪")
                label.setObjectName("lyricsLine")
                label.setWordWrap(True)
                label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                label.setMinimumWidth(0)
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.lyrics_layout.addWidget(label)
                self.lyric_labels.append(label)
        elif plain:
            for line in plain.splitlines():
                label = QLabel(line or "♪")
                label.setObjectName("lyricsLine")
                label.setWordWrap(True)
                label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                label.setMinimumWidth(0)
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.lyrics_layout.addWidget(label)
                self.lyric_labels.append(label)
        else:
            label = QLabel(error or "Não encontramos letras para esta música.")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            label.setStyleSheet(f"color:{MUTED}; font-size:14px; padding:24px;")
            self.lyrics_layout.addWidget(label)
        self.lyrics_layout.addStretch(1)
        if self.lyric_times:
            self._highlight_lyric(0)

    def _highlight_lyric(self, position: float) -> None:
        if not self.lyric_times or not self.lyric_labels:
            return
        active = 0
        for i, (timestamp, _line) in enumerate(self.lyric_times):
            if timestamp <= position:
                active = i
            else:
                break
        for i, label in enumerate(self.lyric_labels):
            label.setObjectName("lyricsActive" if i == active else "lyricsLine")
            label.style().unpolish(label)
            label.style().polish(label)
        current = self.lyric_labels[active]
        self.lyrics_scroll.ensureWidgetVisible(current, 0, max(20, self.lyrics_scroll.height() // 3))

    def closeEvent(self, event: Any) -> None:
        try:
            if getattr(self, "_mpv_ready", False):
                self._ipc(["quit"])
            process = getattr(self, "mpv_process", None)
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    process.kill()
            Path(IPC_FILE).unlink(missing_ok=True)
        except OSError:
            pass
        for worker in self.active_workers:
            if worker.isRunning():
                worker.wait(300)
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Noxtify")
    app.setStyle("Fusion")
    font = QFont("Noto Sans", 10)
    app.setFont(font)
    window = MusicWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
