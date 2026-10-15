"""Pure helper and recommendation tests; Qt/network access is not needed."""
from __future__ import annotations

import ast
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

APP = Path(__file__).parents[1] / "nox_music" / "app.py"
FUNCTIONS = {
    "fmt_time", "parse_lrc", "_normalise_search_text", "_token_match_strength",
    "query_match_coverage", "is_relevant_search_result", "search_relevance",
    "infer_track_styles", "select_discovery_styles", "most_listened_artist", "normalise_youtube_artist",
    "normalise_track", "cover_video_id", "thumbnail_sources", "thumbnail_candidates",
    "_display_name", "infer_artist_from_title", "artist_profile_for_track",
    "creator_profile_for_track", "extract_channel_avatar_url",
}


def load_pure_helpers() -> dict[str, Any]:
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    body = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS:
            body.append(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "STYLE_PROFILES":
            body.append(node)
    namespace: dict[str, Any] = {
        "Any": Any,
        "re": re,
        "unicodedata": unicodedata,
        "SequenceMatcher": SequenceMatcher,
    }
    exec(compile(ast.Module(body=body, type_ignores=[]), str(APP), "exec"), namespace)
    return namespace


HELPERS = load_pure_helpers()


def test_parse_lrc_multiple_timestamps():
    assert HELPERS["parse_lrc"]("[00:01.20]Hello\n[00:03.00]World") == [(1.2, "Hello"), (3.0, "World")]


def test_fmt_time():
    assert HELPERS["fmt_time"](125) == "2:05"
    assert HELPERS["fmt_time"](None) == "0:00"


def test_search_relevance_prefers_matching_artist_or_title():
    rank = HELPERS["search_relevance"]
    exact = {"title": "Night Drive", "artist": "Copagazz", "album": ""}
    unrelated = {"title": "Set 002 Radio Meia Noite", "artist": "Iku The Kid", "album": ""}
    assert rank("copagazz", exact) > rank("copagazz", unrelated)
    assert rank("Night Drive", exact) > rank("copagazz", unrelated)
    assert HELPERS["is_relevant_search_result"]("copagazz", exact)
    assert HELPERS["is_relevant_search_result"]("Night Drive", exact)
    assert not HELPERS["is_relevant_search_result"]("copagazz", unrelated)


def test_normalise_track_has_artwork_fallback_and_duration():
    track = HELPERS["normalise_track"]({
        "videoId": "abc123", "title": "Night Drive", "artists": [{"name": "Copagazz"}], "duration_seconds": 183,
    })
    assert track["duration"] == 183
    assert track["artist"] == "Copagazz"
    assert track["thumbnail"] == "https://i.ytimg.com/vi/abc123/hqdefault.jpg"
    assert track["url"] == "https://music.youtube.com/watch?v=abc123"
    saved_track = {"id": "abc123", "thumbnail": "https://images.example/cover.jpg"}
    assert HELPERS["thumbnail_sources"](saved_track) == (
        "https://images.example/cover.jpg", "https://i.ytimg.com/vi/abc123/hqdefault.jpg"
    )


def test_search_handles_accents_and_artist_plus_title():
    track = {"title": "Saudade", "artist": "Lil Zé, Copagazz", "album": ""}
    relevant = HELPERS["is_relevant_search_result"]
    assert relevant("Lil Ze", track)
    assert relevant("Copagazz Saudade", track)
    assert not relevant("Radiohead Creep", track)


def test_thumbnail_candidates_have_multiple_unique_youtube_fallbacks():
    track = {"id": "abc123", "thumbnail": "https://images.example/cover.jpg"}
    candidates = HELPERS["thumbnail_candidates"](track)
    assert candidates[0] == "https://images.example/cover.jpg"
    assert "https://i.ytimg.com/vi/abc123/hqdefault.jpg" in candidates
    assert "https://i.ytimg.com/vi/abc123/mqdefault.jpg" in candidates
    assert len(candidates) == len(set(candidates))


def test_normalise_track_supports_upload_channel_and_flat_video_metadata():
    track = HELPERS["normalise_track"]({
        "id": "video123", "title": "Night Drive (audio)", "uploader": "Copagazz Fan Uploads",
        "channel_id": "UC123", "channel_url": "https://www.youtube.com/@copagazzfan",
        "duration": 184, "thumbnail": "https://img.example/cover.jpg",
    })
    assert track["id"] == "video123"
    assert track["artist"] == "Artista desconhecido"
    assert track["creator"] == "Copagazz Fan Uploads"
    assert track["duration"] == 184
    assert track["creator_profile"]["url"] == "https://www.youtube.com/@copagazzfan"
    assert track["thumbnail"] == "https://img.example/cover.jpg"


def test_youtube_artist_normalization_retains_browse_id_and_cover():
    artist = HELPERS["normalise_youtube_artist"]({
        "browseId": "UCartist123", "title": "Copagazz", "thumbnails": [{"url": "https://img.example/artist.jpg", "width": 500}],
    })
    assert artist["name"] == "Copagazz"
    assert artist["id"] == "UCartist123"
    assert artist["url"] == "https://music.youtube.com/channel/UCartist123"
    assert artist["image"] == "https://img.example/artist.jpg"
    assert artist["profile_type"] == "artist"


def test_discovery_starts_with_multiple_distinct_styles():
    styles = HELPERS["select_discovery_styles"]([], [], 4)
    assert len(styles) == 4
    assert len({item["id"] for item in styles}) == 4
    assert len({item["name"] for item in styles}) == 4


def test_discovery_adapts_to_a_listened_style_but_keeps_exploration():
    select = HELPERS["select_discovery_styles"]
    favorites = [
        {"title": "Montagem Automotiva", "artist": "DJ Arana"},
        {"title": "Funk Brasileiro", "artist": "MC Ryan SP"},
        {"title": "Baile Funk", "artist": "MC Hariel"},
    ]
    styles = select(favorites, favorites, 4)
    ids = [item["id"] for item in styles]
    assert ids[0] == "funk_br"
    assert len(set(ids)) == 4
    assert any(item["id"] != "funk_br" for item in styles)


def test_discovery_finds_rock_when_history_points_to_rock():
    styles = HELPERS["select_discovery_styles"](
        [{"title": "Nirvana Live", "artist": "Rock"}] * 5,
        [{"title": "Deftones", "artist": "Alternative Rock"}] * 5,
        4,
    )
    assert styles[0]["id"] == "rock"


def test_selected_recommendation_style_becomes_a_preference_signal():
    select = HELPERS["select_discovery_styles"]
    favorites = [{"title": "Song A", "artist": "Unknown Artist", "discovery_style": "indie_lofi"}] * 4
    styles = select(favorites, favorites, 4)
    assert styles[0]["id"] == "indie_lofi"
    assert len({item["id"] for item in styles}) == 4


def test_most_listened_artist_personalizes_home_even_without_genre_tags():
    artist = HELPERS["most_listened_artist"]
    favorites = [{"title": "Track A", "artist": "Obscure Artist"}]
    recent = [{"title": "Track B", "artist": "Obscure Artist"}, {"title": "Track C", "artist": "Other Artist"}]
    assert artist(favorites, recent) == "Obscure Artist"



def test_artist_profile_uses_clicked_track_performer_not_current_or_publisher():
    track = {
        "id": "song-b",
        "title": "Song B",
        "artist": "Artist B",
        "artist_profiles": [{"id": "UCARTISTB", "name": "Artist B", "url": "https://music.youtube.com/channel/UCARTISTB"}],
        "creator": "FanChannelA",
        "creator_profile": {"id": "UCUPLOADA", "name": "FanChannelA", "url": "https://www.youtube.com/channel/UCUPLOADA"},
        "thumbnail": "https://i.ytimg.com/vi/song-b/hqdefault.jpg",
    }
    profile = HELPERS["artist_profile_for_track"](track)
    assert profile["name"] == "Artist B"
    assert profile["id"] == "UCARTISTB"
    assert profile["profile_type"] == "artist"
    assert profile["name"] != track["creator"]


def test_uploader_profile_is_separate_from_artist_profile():
    track = {
        "artist": "Artist B",
        "creator": "FanChannelB",
        "creator_profile": {"name": "FanChannelB", "id": "UCUPLOADB", "url": "https://www.youtube.com/channel/UCUPLOADB"},
    }
    artist = HELPERS["artist_profile_for_track"](track)
    creator = HELPERS["creator_profile_for_track"](track)
    assert artist["name"] == "Artist B"
    assert creator["name"] == "FanChannelB"
    assert creator["url"].endswith("UCUPLOADB")


def test_channel_avatar_html_metadata_is_extracted_not_video_cover():
    html = "<html><head><meta name=\"twitter:image\" content=\"https://yt3.googleusercontent.com/channel-avatar=s900-c-k-c0x00ffffff-no-rj\"></head></html>"
    assert HELPERS["extract_channel_avatar_url"](html) == "https://yt3.googleusercontent.com/channel-avatar=s900-c-k-c0x00ffffff-no-rj"


def test_title_artist_inference_only_uses_explicit_artist_separator():
    infer = HELPERS["infer_artist_from_title"]
    assert infer("Artist Name - Track Name (Official Audio)") == "Artist Name"
    assert infer("Track Name Official Audio") == ""
