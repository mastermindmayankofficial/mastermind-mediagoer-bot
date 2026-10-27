#!/usr/bin/env python3
# Copyright 2026
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

"""
mediagoer: A unified, Cinemagoer-inspired Python library and CLI for extracting
movie, TV, anime, manga, book, audiobook, and series/franchise data from 8 sources:

1. IMDb (`imdb`)             - Local Cinemagoer S3 SQLite DB + IMDb JSON-LD/Suggestion API
2. Letterboxd (`letterboxd`) - Film & collection pages via JSON-LD + meta tags
3. MyAnimeList (`mal`)       - Jikan REST API v4 (`/v4/anime`, `/v4/manga`, `relations`)
4. AniList (`anilist`)       - Public GraphQL API (`https://graphql.anilist.co`)
5. Kitsu (`kitsu`)           - Public JSON:API (`https://kitsu.io/api/edge`)
6. Goodreads (`goodreads`)   - `__NEXT_DATA__` Apollo state, JSON-LD & `/series/` pages
7. Audible (`audible`)       - Catalog JSON API (`/1.0/catalog/products` & `relationships`)
8. Storytel (`storytel`)     - `__NEXT_DATA__` & JSON-LD for audiobooks, eBooks & series

Provides:
- Dictionary-like `_Container` classes (`MediaItem`, `Series`, `Creator`) modeled
  after Cinemagoer's `Movie` and `Person` classes.
- `item.format_card()`: Formats any movie, anime, book, or audiobook into the exact
  Unicode emoji card layout (`🏷 𝖳𝗂𝗍𝗅𝖾`, `📚 𝖲𝖾𝗋𝗂𝖾𝗌`, `🔮 𝖸𝖾𝖺𝗋`, `⭐️ 𝖱𝖺𝗍𝗂𝗇𝗀𝗌`,
  `🔊 𝖫𝖺𝗇𝗀𝗎𝖺𝗀𝖾`, `🌏 𝖢𝗈𝗎𝗇𝗍𝗋𝗒`, `🎭 𝖦𝖾𝗇𝖾𝗋𝗌`, `📜 𝖲𝗍𝗈𝗋𝗒 𝖫𝗂𝗇𝖾`).
- `mg.get_series(...)` & `mg.get_series_info(...)`: Extracts full series/franchise
  information with all titles (books, audiobooks, movies, seasons, anime/manga)
  and short info for every entry.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import json
import re
import sys
from typing import Any, Callable
from urllib.parse import quote, quote_plus, urlencode
from urllib.request import Request, urlopen

__all__ = [
    'AniListAdapter',
    'AudibleAdapter',
    'Creator',
    'GoodreadsAdapter',
    'IMDbAdapter',
    'KitsuAdapter',
    'LetterboxdAdapter',
    'MALAdapter',
    'MediaDB',
    'MediaItem',
    'Mediagoer',
    'MediagoerDataAccessError',
    'MediagoerError',
    'Series',
    'StorytelAdapter',
    'available_providers',
    'format_media_card',
    'format_series_overview',
]

__version__ = '2026.10.27'

PROVIDER_ALIASES: dict[str, str] = {
    'imdb': 'imdb',
    's3': 'imdb',
    'cinemagoer': 'imdb',
    'letterboxd': 'letterboxd',
    'letterbox': 'letterboxd',
    'lbxd': 'letterboxd',
    'mal': 'mal',
    'myanimelist': 'mal',
    'jikan': 'mal',
    'anilist': 'anilist',
    'al': 'anilist',
    'kitsu': 'kitsu',
    'goodreads': 'goodreads',
    'gr': 'goodreads',
    'audible': 'audible',
    'storytel': 'storytel',
    'books': 'books_hybrid',
    'anime': 'anime_hybrid',
}

AUDIBLE_MARKETPLACES: dict[str, dict[str, str]] = {
    'us': {'tld': 'com', 'country': 'United States'},
    'uk': {'tld': 'co.uk', 'country': 'United Kingdom'},
    'in': {'tld': 'in', 'country': 'India'},
    'ca': {'tld': 'ca', 'country': 'Canada'},
    'au': {'tld': 'com.au', 'country': 'Australia'},
    'de': {'tld': 'de', 'country': 'Germany'},
    'fr': {'tld': 'fr', 'country': 'France'},
    'it': {'tld': 'it', 'country': 'Italy'},
    'es': {'tld': 'es', 'country': 'Spain'},
    'jp': {'tld': 'co.jp', 'country': 'Japan'},
    'br': {'tld': 'com.br', 'country': 'Brazil'},
}

AUDIBLE_RESPONSE_GROUPS = (
    'contributors,media,price,product_attrs,product_desc,'
    'product_extended_attrs,rating,series,relationships,category_ladders,sku'
)

COUNTRY_CODE_MAP: dict[str, str] = {
    'US': 'United States',
    'GB': 'United Kingdom',
    'UK': 'United Kingdom',
    'IN': 'India',
    'JP': 'Japan',
    'KR': 'South Korea',
    'CN': 'China',
    'TW': 'Taiwan',
    'FR': 'France',
    'DE': 'Germany',
    'IT': 'Italy',
    'ES': 'Spain',
    'CA': 'Canada',
    'AU': 'Australia',
    'SE': 'Sweden',
    'BR': 'Brazil',
}

COUNTRY_DEFAULT_LANGUAGE: dict[str, str] = {
    'Japan': 'Japanese',
    'South Korea': 'Korean',
    'China': 'Chinese',
    'Taiwan': 'Chinese',
    'United States': 'English',
    'United Kingdom': 'English',
    'India': 'Hindi / English',
    'France': 'French',
    'Germany': 'German',
    'Italy': 'Italian',
    'Spain': 'Spanish',
    'Sweden': 'Swedish',
}

LANGUAGE_CODE_MAP: dict[str, str] = {
    'en': 'English',
    'ja': 'Japanese',
    'ko': 'Korean',
    'zh': 'Chinese',
    'hi': 'Hindi',
    'fr': 'French',
    'de': 'German',
    'es': 'Spanish',
    'it': 'Italian',
    'pt': 'Portuguese',
    'sv': 'Swedish',
    'ru': 'Russian',
}

DEFAULT_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
}

_RE_SCRIPT_NEXT_DATA = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_RE_SCRIPT_JSON_LD = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_RE_SERIES_REACT_PROPS = re.compile(
    r'data-react-class=["\']ReactComponents\.Series(?:List|Header)["\'][^>]*'
    r'data-react-props=["\']([^"\']+)["\']',
    re.DOTALL | re.IGNORECASE,
)
_RE_IMDB_ID = re.compile(r'\b(?:tt)?(\d{7,10})\b', re.IGNORECASE)
_RE_GOODREADS_BOOK_ID = re.compile(r'/book/show/(\d+)')
_RE_GOODREADS_SERIES_ID = re.compile(r'/series/(\d+)')
_RE_AUDIBLE_ASIN = re.compile(r'\b(B[0-9A-Z]{9}|\d{9}[\dX])\b', re.IGNORECASE)
_RE_ISO_DURATION = re.compile(r'PT(?:(\d+)H)?(?:(\d+)M)?', re.IGNORECASE)


def available_providers() -> list[str]:
    """Return the canonical names of all 8 supported metadata providers."""
    return [
        'imdb',
        'letterboxd',
        'mal',
        'anilist',
        'kitsu',
        'goodreads',
        'audible',
        'storytel',
    ]


class MediagoerError(Exception):
    """Base exception for Mediagoer errors."""


class MediagoerDataAccessError(MediagoerError):
    """Raised when remote or local media data cannot be retrieved or parsed."""


class _HTMLTextExtractor(HTMLParser):
    """Strip HTML tags and normalize whitespace."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in ('br', 'p', 'div', 'li'):
            self._parts.append(' ')

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        raw = ''.join(self._parts)
        return re.sub(r'\s+', ' ', unescape(raw)).strip()


def clean_html_text(value: str | None) -> str:
    """Strip HTML markup and source-note suffixes (`[Written by MAL Rewrite]`, etc.)."""
    if not value:
        return ''
    parser = _HTMLTextExtractor()
    parser.feed(str(value))
    parser.close()
    text = parser.get_text()
    text = re.sub(r'\s*\[Written by [^\]]+\]\s*$', '', text)
    text = re.sub(r'\s*\(Source: [^)]+\)\s*$', '', text)
    return text.strip()


def format_runtime(minutes: int | float | None) -> str:
    """Format runtime in minutes into 'X hrs Y mins'."""
    if not minutes:
        return ''
    total_mins = int(round(float(minutes)))
    if total_mins <= 0:
        return ''
    hours, mins = divmod(total_mins, 60)
    if hours and mins:
        return f'{hours} hrs {mins} mins'
    if hours:
        return f'{hours} hrs'
    return f'{mins} mins'


def parse_iso8601_duration(duration: str | None) -> int | None:
    """Convert ISO-8601 duration (e.g. 'PT2H16M') into total minutes."""
    if not duration:
        return None
    match = _RE_ISO_DURATION.search(str(duration))
    if not match:
        return None
    hours = int(match.group(1) or 0)
    mins = int(match.group(2) or 0)
    total = hours * 60 + mins
    return total if total > 0 else None


def shorten_text(text: str | None, max_chars: int = 180) -> str:
    """Return a concise single-line summary string."""
    cleaned = clean_html_text(text)
    if not cleaned:
        return ''
    if len(cleaned) <= max_chars:
        return cleaned
    clipped = cleaned[: max_chars - 1].rsplit(' ', 1)[0].rstrip('.,;:')
    return f'{clipped}…'


def _normalize_language(lang: str | None) -> str:
    if not lang:
        return ''
    val = str(lang).strip()
    low = val.lower()
    if low in LANGUAGE_CODE_MAP:
        return LANGUAGE_CODE_MAP[low]
    return val.capitalize() if val.islower() else val


def _normalize_country(country: str | None) -> str:
    if not country:
        return ''
    val = str(country).strip()
    up = val.upper()
    if up in COUNTRY_CODE_MAP:
        return COUNTRY_CODE_MAP[up]
    return val


def _sequence_sort_key(position: Any) -> tuple[int, float, str]:
    """Deterministic ordering for series positions ('1', '1.5', '2', etc.)."""
    if position is None or position == '':
        return (1, 999999.0, '')
    text = str(position).strip()
    match = re.search(r'(\d+(?:\.\d+)?)', text)
    if match:
        return (0, float(match.group(1)), text)
    return (0, 999998.0, text)


class _Container:
    """Cinemagoer-style dictionary-like container base class."""

    keys_alias: dict[str, str] = {}

    def __init__(
        self,
        item_id: str | None = None,
        data: dict[str, Any] | None = None,
        access_system: str = 'imdb',
    ) -> None:
        self.item_id = item_id
        self.accessSystem = access_system
        self.data: dict[str, Any] = {}
        self.current_info: list[str] = []
        if data:
            self.set_data(data, override=True)

    def set_data(self, data: dict[str, Any], override: bool = False) -> None:
        if override:
            self.data = dict(data)
        else:
            self.data.update(data)

    def _additional_keys(self) -> list[str]:
        return []

    def _getitem(self, key: str) -> Any:
        return None

    def __getitem__(self, key: str) -> Any:
        norm_key = key.lower().strip()
        computed = self._getitem(norm_key)
        if computed is not None:
            return computed
        target_key = self.keys_alias.get(norm_key, key)
        if target_key in self.data:
            return self.data[target_key]
        if norm_key in self.data:
            return self.data[norm_key]
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value

    def __contains__(self, key: Any) -> bool:
        if isinstance(key, str):
            try:
                self.__getitem__(key)
                return True
            except KeyError:
                return False
        return False

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self.__getitem__(key)
        except KeyError:
            return default

    def keys(self) -> list[str]:
        base = list(self.data.keys())
        for extra in self._additional_keys():
            if extra not in base:
                base.append(extra)
        return base

    def items(self) -> list[tuple[str, Any]]:
        return [(k, self.get(k)) for k in self.keys()]

    def values(self) -> list[Any]:
        return [self.get(k) for k in self.keys()]

    def copy(self) -> _Container:
        return deepcopy(self)

    def __bool__(self) -> bool:
        return bool(self.data)


class Creator(_Container):
    """Represents a person or studio (author, narrator, director, actor, studio)."""

    keys_alias = {
        'person name': 'name',
        'author name': 'name',
        'full name': 'name',
    }

    def __init__(
        self,
        creatorID: str | None = None,
        name: str = '',
        role: str = 'creator',
        data: dict[str, Any] | None = None,
        access_system: str = 'imdb',
    ) -> None:
        init_data = dict(data or {})
        if name and 'name' not in init_data:
            init_data['name'] = name
        init_data.setdefault('role', role)
        super().__init__(item_id=creatorID, data=init_data, access_system=access_system)
        self.creatorID = creatorID
        self.role = init_data['role']

    def __str__(self) -> str:
        return str(self.data.get('name', ''))

    def __repr__(self) -> str:
        return (
            f'<Creator id:{self.creatorID}[{self.accessSystem}] '
            f'name:_{self.get("name", "")}_ role:{self.role}>'
        )


class MediaItem(_Container):
    """
    Unified container for a Movie, TV Series, Anime, Manga, Book, or Audiobook
    across IMDb, Letterboxd, MyAnimeList, AniList, Kitsu, Goodreads, Audible,
    and Storytel.
    """

    keys_alias = {
        'movie title': 'title',
        'book title': 'title',
        'release year': 'year',
        'publication year': 'year',
        'start year': 'year',
        'ratings': 'rating',
        'user rating': 'rating',
        'average rating': 'rating',
        'score': 'rating',
        'num votes': 'votes',
        'ratings count': 'votes',
        'lang': 'language',
        'languages': 'language',
        'countries': 'country',
        'production countries': 'country',
        'region': 'country',
        'genre': 'genres',
        'storyline': 'plot',
        'story line': 'plot',
        'plot summary': 'plot',
        'synopsis': 'plot',
        'description': 'plot',
        'author': 'authors',
        'writer': 'authors',
        'writers': 'authors',
        'director': 'directors',
        'directed by': 'directors',
        'actors': 'cast',
        'actresses': 'cast',
        'narrator': 'narrators',
        'read by': 'narrators',
        'studio': 'studios',
        'duration': 'runtime',
        'length': 'runtime',
        'runtimes': 'runtime',
        'series name': 'series',
        'series title': 'series',
        'franchise': 'series',
        'collection': 'series',
        'book number': 'series position',
        'position': 'series position',
        'sequence': 'series position',
        'cover': 'cover url',
    }

    def __init__(
        self,
        mediaID: str | None = None,
        title: str = '',
        data: dict[str, Any] | None = None,
        access_system: str = 'imdb',
    ) -> None:
        init_data = dict(data or {})
        if title and 'title' not in init_data:
            init_data['title'] = title
        super().__init__(item_id=mediaID, data=init_data, access_system=access_system)
        self.mediaID = mediaID

    def _additional_keys(self) -> list[str]:
        extra = []
        if 'title' in self.data:
            extra.append('long title')
        if self.data.get('series'):
            extra.extend(['full series', 'series label'])
        if self.data.get('runtime_minutes') and 'runtime' not in self.data:
            extra.append('runtime')
        if self.data.get('plot'):
            extra.append('short plot')
        return extra

    def _getitem(self, key: str) -> Any:
        if key == 'long title' and 'title' in self.data:
            base = self.data['title']
            subtitle = self.data.get('subtitle')
            year = self.data.get('year')
            full = f'{base}: {subtitle}' if subtitle else base
            return f'{full} ({year})' if year else full
        if key in ('full series', 'series label') and self.data.get('series'):
            series_name = self.data['series']
            pos = self.data.get('series position')
            if pos not in (None, ''):
                return f'{series_name} (#{pos})'
            return str(series_name)
        if key == 'runtime' and 'runtime' not in self.data:
            if self.data.get('runtime_minutes'):
                return format_runtime(self.data['runtime_minutes'])
        if key == 'short plot' and self.data.get('plot'):
            return shorten_text(self.data['plot'], max_chars=180)
        return None

    def default_rating_scale(self) -> int:
        """Return 5 for 5-star platforms and 10 for 10-point platforms."""
        if self.data.get('rating_scale'):
            return int(self.data['rating_scale'])
        if self.accessSystem in ('letterboxd', 'goodreads', 'audible', 'storytel'):
            return 5
        return 10

    def media_badge(self) -> str:
        kind = str(self.data.get('kind') or '').lower()
        if kind == 'audiobook' or self.data.get('narrators'):
            return '🎧 Audiobook'
        if kind in ('ebook', 'book', 'light novel', 'novel'):
            return '📖 Book'
        if kind in ('manga', 'manhwa', 'manhua', 'one-shot'):
            return '🗯 Manga'
        if kind in ('anime', 'ona', 'ova') or self.accessSystem in ('mal', 'anilist', 'kitsu'):
            return '🎌 Anime'
        if kind in ('tv series', 'tv mini series', 'episode'):
            return '📺 TV Series'
        return '🎬 Movie'

    def format_card(self, header_tag: str | None = None, max_rating: int | None = None) -> str:
        """Format this item in the requested Unicode emoji card style."""
        return format_media_card(self, header_tag=header_tag, max_rating=max_rating)

    def short_info(self) -> str:
        """Return a concise summary block for series/franchise listings."""
        pos = self.get('series position') or self.get('relation_type')
        pos_prefix = (
            f'#{pos} '
            if pos not in (None, '') and str(pos)[0].isdigit()
            else (f'[{pos}] ' if pos else '')
        )
        title = self.get('title', 'Unknown Title')
        year = self.get('year')
        year_str = f' ({year})' if year else ''
        badge = self.media_badge()

        stats_parts = [badge, f'🌐 {self.accessSystem}']
        rating = self.get('rating')
        scale = self.default_rating_scale()
        if rating not in (None, ''):
            votes = self.get('votes')
            vote_str = f' ({votes:,} votes)' if isinstance(votes, int) else ''
            stats_parts.append(f'⭐️ {rating}/{scale}{vote_str}')
        runtime = self.get('runtime')
        pages = self.get('pages')
        episodes = self.get('episodes')
        if runtime:
            stats_parts.append(f'⏱ {runtime}')
        if pages:
            stats_parts.append(f'📄 {pages} pages')
        if episodes:
            stats_parts.append(f'🎞 {episodes} eps')

        credits_parts = []
        authors = [str(a) for a in (self.get('authors') or []) if str(a)]
        directors = [str(d) for d in (self.get('directors') or []) if str(d)]
        narrators = [str(n) for n in (self.get('narrators') or []) if str(n)]
        studios = [str(s) for s in (self.get('studios') or []) if str(s)]
        if directors:
            credits_parts.append(f'Directed by {", ".join(directors[:3])}')
        if authors:
            credits_parts.append(f'By {", ".join(authors[:3])}')
        if narrators:
            credits_parts.append(f'Narrated by {", ".join(narrators[:3])}')
        if studios and not directors and not authors:
            credits_parts.append(f'Studio: {", ".join(studios[:2])}')

        blurb = self.get('short plot') or shorten_text(self.get('plot'), 160)
        lines = [f'• {pos_prefix}{title}{year_str} [{" | ".join(stats_parts)}]']
        if credits_parts:
            lines.append(f'  ✍️ {" • ".join(credits_parts)}')
        if blurb:
            lines.append(f'  📜 {blurb}')
        return '\n'.join(lines)

    def summary(self) -> str:
        return self.format_card()

    def __str__(self) -> str:
        return str(self.data.get('title', ''))

    def __repr__(self) -> str:
        return (
            f'<MediaItem id:{self.mediaID}[{self.accessSystem}] '
            f'title:_{self.get("long title", "")}_>'
        )


class Series(_Container):
    """
    Represents a Book Series, Audiobook Series, Film Collection, TV Series,
    or Anime/Manga Franchise with all entries and short info.
    """

    keys_alias = {
        'series name': 'title',
        'name': 'title',
        'all titles': 'items',
        'titles': 'items',
        'plot': 'description',
        'summary': 'description',
    }

    def __init__(
        self,
        seriesID: str | None = None,
        title: str = '',
        data: dict[str, Any] | None = None,
        access_system: str = 'imdb',
    ) -> None:
        init_data = dict(data or {})
        if title and 'title' not in init_data:
            init_data['title'] = title
        init_data.setdefault('books', [])
        init_data.setdefault('audiobooks', [])
        init_data.setdefault('items', [])
        super().__init__(item_id=seriesID, data=init_data, access_system=access_system)
        self.seriesID = seriesID

    def _additional_keys(self) -> list[str]:
        return ['number of books', 'number of audiobooks', 'total titles']

    def _getitem(self, key: str) -> Any:
        if key == 'number of books':
            return len(self.data.get('books') or [])
        if key == 'number of audiobooks':
            return len(self.data.get('audiobooks') or [])
        if key == 'total titles':
            items = self.data.get('items')
            if items:
                return len(items)
            return len(self.data.get('books') or []) + len(
                self.data.get('audiobooks') or []
            )
        return None

    def format_series_info(self) -> str:
        return format_series_overview(self)

    def summary(self) -> str:
        return self.format_series_info()

    def __str__(self) -> str:
        return str(self.data.get('title', ''))

    def __repr__(self) -> str:
        return (
            f'<Series id:{self.seriesID}[{self.accessSystem}] '
            f'title:_{self.get("title", "")}_ '
            f'titles:{self.get("total titles", 0)}>'
        )


def format_media_card(
    item: MediaItem,
    header_tag: str | None = None,
    max_rating: int | None = None,
) -> str:
    """
    Format any `MediaItem` into the requested Unicode card format:

    ⟡ The

    🏷 𝖳𝗂𝗍𝗅𝖾 : The Scandal
    📚 𝖲𝖾𝗋𝗂𝖾𝗌 : ... (if part of a series/franchise)
    🔮 𝖸𝖾𝖺𝗋 : 2026
    ⭐️ 𝖱𝖺𝗍𝗂𝗇𝗀𝗌 : 6.6 / 10
    🔊 𝖫𝖺𝗇𝗀𝗎𝖺𝗀𝖾 : Korean
    🌏 𝖢𝗈𝗎𝗇𝗍𝗋𝗒 : South Korea
    🎭 𝖦𝖾𝗇𝖾𝗋𝗌 : 🎭 #Drama

    📜 𝖲𝗍𝗈𝗋𝗒 𝖫𝗂𝗇𝖾 : ...
    """
    title = item.get('title') or 'Unknown'
    if header_tag is None:
        first_word = title.split()[0] if title.split() else 'Media'
        header_tag = f'⟡ {first_word}'

    scale = max_rating if max_rating is not None else item.default_rating_scale()

    lines = [header_tag, '']
    lines.append(f'🏷 𝖳𝗂𝗍𝗅𝖾 : {title}')

    series_label = item.get('full series') or item.get('series')
    if series_label:
        lines.append(f'📚 𝖲𝖾𝗋𝗂𝖾𝗌 : {series_label}')

    authors = [str(a) for a in (item.get('authors') or []) if str(a)]
    directors = [str(d) for d in (item.get('directors') or []) if str(d)]
    narrators = [str(n) for n in (item.get('narrators') or []) if str(n)]
    if directors:
        lines.append(f'🎬 𝖣𝗂𝗋𝖾𝖼𝗍𝗈𝗋 : {", ".join(directors[:3])}')
    elif authors:
        lines.append(f'✍️ 𝖠𝗎𝗍𝗁𝗈𝗋 : {", ".join(authors[:3])}')
    if narrators:
        lines.append(f'🎙 𝖭𝖺𝗋𝗋𝖺𝗍𝗈𝗋 : {", ".join(narrators[:3])}')

    year = item.get('year')
    if year:
        lines.append(f'🔮 𝖸𝖾𝖺𝗋 : {year}')

    rating = item.get('rating')
    if rating not in (None, ''):
        lines.append(f'⭐️ 𝖱𝖺𝗍𝗂𝗇𝗀𝗌 : {rating} / {scale}')

    runtime = item.get('runtime')
    if runtime:
        lines.append(f'⏱ 𝖣𝗎𝗋𝖺𝗍𝗂𝗈𝗇 : {runtime}')

    language = item.get('language')
    if isinstance(language, list):
        language = ', '.join(str(x) for x in language if x)
    if language:
        lines.append(f'🔊 𝖫𝖺𝗇𝗀𝗎𝖺𝗀𝖾 : {language}')

    country = item.get('country')
    if isinstance(country, list):
        country = ', '.join(str(x) for x in country if x)
    if country:
        lines.append(f'🌏 𝖢𝗈𝗎𝗇𝗍𝗋𝗒 : {country}')

    genres = item.get('genres') or []
    if isinstance(genres, str):
        genres = [genres]
    if genres:
        hashtags = ' '.join(
            '#' + re.sub(r'[^A-Za-z0-9]+', '', g.title())
            for g in genres
            if g and re.sub(r'[^A-Za-z0-9]+', '', g)
        )
        lines.append(f'🎭 𝖦𝖾𝗇𝖾𝗋𝗌 : 🎭 {hashtags}')

    story_line = clean_html_text(item.get('plot'))
    if story_line:
        lines.append('')
        lines.append(f'📜 𝖲𝗍𝗈𝗋𝗒 𝖫𝗂𝗇𝖾 : {story_line}')

    return '\n'.join(lines)


def format_series_overview(series: Series) -> str:
    """
    Format a complete Series/Franchise overview with all titles (books,
    audiobooks, movies, episodes, or anime/manga) and short info for each.
    """
    title = series.get('title') or 'Unknown Series'
    lines = [
        f'📚 𝖲𝖾𝗋𝗂𝖾𝗌 : {title}',
        f'🌐 𝖲𝗈𝗎𝗋𝖼𝖾 : {series.accessSystem}',
    ]
    if series.seriesID:
        lines.append(f'🆔 𝖲𝖾𝗋𝗂𝖾𝗌 𝖨𝖣 : {series.seriesID}')

    creators = [
        str(c)
        for c in (series.get('authors') or series.get('directors') or [])
        if str(c)
    ]
    if creators:
        lines.append(f'✍️ 𝖢𝗋𝖾𝖺𝗍𝗈𝗋 : {", ".join(creators[:4])}')

    books: list[MediaItem] = series.get('books') or []
    audiobooks: list[MediaItem] = series.get('audiobooks') or []
    items: list[MediaItem] = series.get('items') or []

    counts = []
    if books:
        counts.append(f'{len(books)} Books')
    if audiobooks:
        counts.append(f'{len(audiobooks)} Audiobooks')
    if not counts and items:
        counts.append(f'{len(items)} Titles')
    if counts:
        lines.append(f'📊 𝖳𝗈𝗍𝖺𝗅 𝖳𝗂𝗍𝗅𝖾𝗌 : {" | ".join(counts)}')

    desc = clean_html_text(series.get('description'))
    if desc:
        lines.append(f'📜 𝖲𝖾𝗋𝗂𝖾𝗌 𝖮𝗏𝖾𝗋𝗏𝗂𝖾𝗐 : {shorten_text(desc, 280)}')

    if books or audiobooks:
        if books:
            lines.append('')
            lines.append('📖 𝖡𝗈𝗈𝗄𝗌 𝗂𝗇 𝖲𝖾𝗋𝗂𝖾𝗌:')
            for b in books:
                lines.append(b.short_info())
        if audiobooks:
            lines.append('')
            lines.append('🎧 𝖠𝗎𝖽𝗂𝗈𝖻𝗈𝗈𝗄𝗌 𝗂𝗇 𝖲𝖾𝗋𝗂𝖾𝗌:')
            for ab in audiobooks:
                lines.append(ab.short_info())
    elif items:
        lines.append('')
        lines.append('📚 𝖳𝗂𝗍𝗅𝖾𝗌 𝗂𝗇 𝖲𝖾𝗋𝗂𝖾𝗌 / 𝖥𝗋𝖺𝗇𝖼𝗁𝗂𝗌𝖾:')
        for entry in items:
            lines.append(entry.short_info())

    return '\n'.join(lines)


def _default_http_fetcher(
    url: str,
    headers: dict[str, str] | None = None,
    method: str = 'GET',
    body: bytes | None = None,
) -> str:
    """Standard-library HTTP helper supporting GET and POST (for GraphQL)."""
    req_headers = dict(DEFAULT_HEADERS)
    if headers:
        req_headers.update(headers)
    req = Request(url, data=body, headers=req_headers, method=method)
    try:
        with urlopen(req, timeout=20) as resp:
            charset = resp.headers.get_content_charset() or 'utf-8'
            return resp.read().decode(charset, errors='replace')
    except Exception as exc:
        raise MediagoerDataAccessError(f'Failed to fetch {url}: {exc}') from exc


# ============================================================================
# 1. IMDb Adapter (Local Cinemagoer S3 DB + Live IMDb JSON-LD/Suggestion API)
# ============================================================================

class IMDbAdapter:
    """
    Adapter for IMDb supporting:
    - Local Cinemagoer S3 SQLite database (`s3_uri='sqlite:///...'`)
    - Live IMDb Suggestion JSON API + Title page `<script type="application/ld+json">`
      and `__NEXT_DATA__` (which adds full Story Line / Plot, Language, and Country).
    """

    def __init__(
        self,
        s3_uri: str | None = None,
        fetcher: Callable[..., str] | None = None,
    ) -> None:
        self.s3_uri = s3_uri
        self._fetch = fetcher or _default_http_fetcher

    def _normalize_tt(self, value: str | int) -> str:
        match = _RE_IMDB_ID.search(str(value).strip())
        if match:
            return f'tt{int(match.group(1)):07d}'
        digits = re.sub(r'\D', '', str(value))
        if digits:
            return f'tt{int(digits):07d}'
        raise MediagoerError(f'Invalid IMDb ID: {value!r}')

    def parse_imdb_html(self, html: str, imdb_id: str | None = None) -> MediaItem:
        """Parse an IMDb `/title/tt.../` page from JSON-LD and `__NEXT_DATA__`."""
        data: dict[str, Any] = {'kind': 'movie', 'rating_scale': 10}

        # 1. JSON-LD
        ld_match = _RE_SCRIPT_JSON_LD.search(html)
        if ld_match:
            try:
                ld = json.loads(ld_match.group(1).strip())
                if isinstance(ld, dict):
                    if ld.get('name'):
                        data['title'] = unescape(str(ld['name']))
                    if ld.get('@type') == 'TVSeries':
                        data['kind'] = 'tv series'
                    if ld.get('datePublished'):
                        data['year'] = str(ld['datePublished'])[:4]
                    if ld.get('description'):
                        data['plot'] = clean_html_text(ld['description'])
                    if ld.get('genre'):
                        g = ld['genre']
                        data['genres'] = [g] if isinstance(g, str) else list(g)
                    if ld.get('duration'):
                        mins = parse_iso8601_duration(ld['duration'])
                        if mins:
                            data['runtime_minutes'] = mins
                            data['runtime'] = format_runtime(mins)
                    agg = ld.get('aggregateRating') or {}
                    if agg.get('ratingValue') is not None:
                        data['rating'] = float(agg['ratingValue'])
                    if agg.get('ratingCount') is not None:
                        data['votes'] = int(agg['ratingCount'])
                    dirs = ld.get('director') or []
                    if isinstance(dirs, dict):
                        dirs = [dirs]
                    directors = [
                        Creator(name=d['name'], role='director', access_system='imdb')
                        for d in dirs
                        if isinstance(d, dict) and d.get('name')
                    ]
                    if directors:
                        data['directors'] = directors
                    actors = ld.get('actor') or []
                    if isinstance(actors, dict):
                        actors = [actors]
                    cast = [
                        Creator(name=a['name'], role='actor', access_system='imdb')
                        for a in actors
                        if isinstance(a, dict) and a.get('name')
                    ]
                    if cast:
                        data['cast'] = cast
            except Exception:
                pass

        # 2. __NEXT_DATA__ for Countries, Languages, Plot, and Series info
        next_match = _RE_SCRIPT_NEXT_DATA.search(html)
        if next_match:
            try:
                nd = json.loads(next_match.group(1).strip())
                page_props = nd.get('props', {}).get('pageProps', {})
                above = page_props.get('aboveTheFoldData') or {}
                main_col = page_props.get('mainColumnData') or {}

                if above.get('id') and not imdb_id:
                    imdb_id = str(above['id'])
                title_text = (above.get('titleText') or {}).get('text')
                if title_text:
                    data['title'] = title_text
                rel_year = (above.get('releaseYear') or {}).get('year')
                if rel_year:
                    data['year'] = str(rel_year)
                plot_text = (
                    ((above.get('plot') or {}).get('plotText') or {}).get('plainText')
                )
                if plot_text:
                    data['plot'] = clean_html_text(plot_text)
                ratings_summary = above.get('ratingsSummary') or {}
                if ratings_summary.get('aggregateRating') is not None:
                    data['rating'] = float(ratings_summary['aggregateRating'])
                if ratings_summary.get('voteCount') is not None:
                    data['votes'] = int(ratings_summary['voteCount'])
                genres_list = [
                    g.get('text')
                    for g in ((above.get('genres') or {}).get('genres') or [])
                    if g.get('text')
                ]
                if genres_list:
                    data['genres'] = genres_list

                countries = [
                    c.get('text')
                    for c in (
                        (main_col.get('countriesOfOrigin') or {}).get('countries')
                        or (above.get('countriesOfOrigin') or {}).get('countries')
                        or []
                    )
                    if c.get('text')
                ]
                if countries:
                    data['country'] = ', '.join(countries)

                langs = [
                    l.get('text')
                    for l in (
                        (main_col.get('spokenLanguages') or {}).get('spokenLanguages')
                        or []
                    )
                    if l.get('text')
                ]
                if langs:
                    data['language'] = ', '.join(langs)

                series_obj = above.get('series') or main_col.get('series') or {}
                if series_obj:
                    s_node = series_obj.get('series') or {}
                    s_title = (s_node.get('titleText') or {}).get('text')
                    s_id = s_node.get('id')
                    ep_num = (
                        (series_obj.get('episodeNumber') or {}).get('episodeNumber')
                    )
                    season_num = (
                        (series_obj.get('episodeNumber') or {}).get('seasonNumber')
                    )
                    if s_title:
                        data['series'] = s_title
                    if s_id:
                        data['seriesID'] = s_id
                    if season_num and ep_num:
                        data['series position'] = f'S{season_num}.E{ep_num}'
                    elif ep_num:
                        data['series position'] = str(ep_num)
            except Exception:
                pass

        if imdb_id:
            data['url'] = f'https://www.imdb.com/title/{imdb_id}/'
        clean = {k: v for k, v in data.items() if v not in (None, '', [])}
        return MediaItem(mediaID=imdb_id, data=clean, access_system='imdb')

    def search(self, query: str, results: int = 10) -> list[MediaItem]:
        """Search IMDb using local S3 DB if configured or IMDb suggestion JSON API."""
        q = query.strip()
        if not q:
            return []
        first_char = re.sub(r'[^a-z0-9]', '', q.lower())[:1] or 'x'
        url = (
            f'https://v3.sg.media-imdb.com/suggestion/{first_char}/'
            f'{quote(q.lower())}.json'
        )
        raw = self._fetch(url)
        payload = json.loads(raw)
        items: list[MediaItem] = []
        for entry in (payload.get('d') or [])[:results]:
            tid = entry.get('id') or ''
            if not tid.startswith('tt'):
                continue
            data = {
                'title': entry.get('l') or '',
                'year': str(entry.get('y') or ''),
                'kind': entry.get('qid') or 'movie',
                'url': f'https://www.imdb.com/title/{tid}/',
            }
            items.append(
                MediaItem(
                    mediaID=tid,
                    data={k: v for k, v in data.items() if v},
                    access_system='imdb',
                )
            )
        return items

    def get_item(self, identifier: str) -> MediaItem:
        tt_id = self._normalize_tt(identifier)
        url = f'https://www.imdb.com/title/{tt_id}/'
        html = self._fetch(url)
        return self.parse_imdb_html(html, imdb_id=tt_id)

    def get_series(self, series_id_or_item: str | MediaItem) -> Series:
        if isinstance(series_id_or_item, MediaItem):
            tt_id = self._normalize_tt(
                series_id_or_item.get('seriesID') or series_id_or_item.mediaID or ''
            )
        else:
            tt_id = self._normalize_tt(series_id_or_item)
        url = f'https://www.imdb.com/title/{tt_id}/episodes/'
        raw = self._fetch(url)
        # Support either JSON-LD/NEXT_DATA episode payload or JSON list
        next_match = _RE_SCRIPT_NEXT_DATA.search(raw)
        episodes: list[MediaItem] = []
        series_title = 'Unknown Series'
        series_desc = ''
        if next_match:
            nd = json.loads(next_match.group(1).strip())
            page_props = nd.get('props', {}).get('pageProps', {})
            content = page_props.get('contentData') or {}
            entity = content.get('entityMetadata') or {}
            series_title = (entity.get('titleText') or {}).get('text') or series_title
            series_desc = (
                ((entity.get('plot') or {}).get('plotText') or {}).get('plainText')
                or ''
            )
            ep_items = (
                ((content.get('section') or {}).get('episodes') or {}).get('items')
                or []
            )
            for ep in ep_items:
                ep_id = ep.get('id') or ''
                season = ep.get('season')
                ep_num = ep.get('episode')
                pos = f'{season}.{ep_num}' if season and ep_num else str(ep_num or '')
                ep_data = {
                    'title': ep.get('titleText') or '',
                    'kind': 'episode',
                    'series': series_title,
                    'seriesID': tt_id,
                    'series position': pos,
                    'year': str(ep.get('releaseYear') or ''),
                    'rating': ep.get('aggregateRating'),
                    'votes': ep.get('voteCount'),
                    'plot': clean_html_text(ep.get('plot') or ''),
                    'url': f'https://www.imdb.com/title/{ep_id}/' if ep_id else '',
                }
                episodes.append(
                    MediaItem(
                        mediaID=ep_id,
                        data={k: v for k, v in ep_data.items() if v not in (None, '')},
                        access_system='imdb',
                    )
                )
        return Series(
            seriesID=tt_id,
            data={
                'title': series_title,
                'description': series_desc,
                'items': episodes,
                'url': f'https://www.imdb.com/title/{tt_id}/',
            },
            access_system='imdb',
        )


# ============================================================================
# 2. Letterboxd Adapter (JSON-LD + Meta & Details HTML Parser)
# ============================================================================

class LetterboxdAdapter:
    """
    Adapter for Letterboxd (`https://letterboxd.com/film/<slug>/` and
    collection pages `https://letterboxd.com/films/in/<collection-slug>/`).
    """

    def __init__(self, fetcher: Callable[..., str] | None = None) -> None:
        self._fetch = fetcher or _default_http_fetcher

    def parse_film_html(self, html: str, slug: str | None = None) -> MediaItem:
        data: dict[str, Any] = {'kind': 'movie', 'rating_scale': 5}

        ld_match = _RE_SCRIPT_JSON_LD.search(html)
        if ld_match:
            raw_ld = ld_match.group(1).strip()
            raw_ld = re.sub(r'^/\*\s*<!\[CDATA\[\s*\*/', '', raw_ld).strip()
            raw_ld = re.sub(r'/\*\s*\]\]>\s*\*/$', '', raw_ld).strip()
            try:
                ld = json.loads(raw_ld)
                if isinstance(ld, dict):
                    if ld.get('name'):
                        data['title'] = unescape(str(ld['name']))
                    if ld.get('genre'):
                        g = ld['genre']
                        data['genres'] = [g] if isinstance(g, str) else list(g)
                    rel_events = ld.get('releasedEvent') or []
                    if isinstance(rel_events, dict):
                        rel_events = [rel_events]
                    if rel_events and rel_events[0].get('startDate'):
                        data['year'] = str(rel_events[0]['startDate'])[:4]
                    agg = ld.get('aggregateRating') or {}
                    if agg.get('ratingValue') is not None:
                        data['rating'] = round(float(agg['ratingValue']), 2)
                    if agg.get('ratingCount') is not None:
                        data['votes'] = int(agg['ratingCount'])
                    dirs = ld.get('director') or []
                    if isinstance(dirs, dict):
                        dirs = [dirs]
                    directors = [
                        Creator(name=d['name'], role='director', access_system='letterboxd')
                        for d in dirs
                        if isinstance(d, dict) and d.get('name')
                    ]
                    if directors:
                        data['directors'] = directors
                    countries = [
                        c.get('name')
                        for c in (ld.get('countryOfOrigin') or [])
                        if isinstance(c, dict) and c.get('name')
                    ]
                    if countries:
                        data['country'] = ', '.join(countries)
            except Exception:
                pass

        # Synopsis from <div class="truncate" data-truncate="..."><p>...</p></div> or meta description
        trunc_match = re.search(
            r'<div[^>]+class=["\'][^"\']*truncate[^"\']*["\'][^>]*>(.*?)</div>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        if trunc_match:
            data['plot'] = clean_html_text(trunc_match.group(1))
        else:
            meta_desc = re.search(
                r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
                html,
                re.IGNORECASE,
            )
            if meta_desc:
                data['plot'] = clean_html_text(meta_desc.group(1))

        # Spoken language & country links from /films/language/... and /films/country/...
        langs = re.findall(
            r'href=["\']/films/language/[^"\']+/["\'][^>]*>([^<]+)</a>',
            html,
            re.IGNORECASE,
        )
        if langs:
            data['language'] = ', '.join(dict.fromkeys(l.strip() for l in langs if l.strip()))

        if 'country' not in data:
            countries = re.findall(
                r'href=["\']/films/country/[^"\']+/["\'][^>]*>([^<]+)</a>',
                html,
                re.IGNORECASE,
            )
            if countries:
                data['country'] = ', '.join(
                    dict.fromkeys(c.strip() for c in countries if c.strip())
                )

        # Collection / series link (`/films/in/<collection-slug>/`)
        coll_match = re.search(
            r'href=["\']/films/in/([^/"\']+)/["\'][^>]*>([^<]+)</a>',
            html,
            re.IGNORECASE,
        )
        if coll_match:
            data['seriesID'] = coll_match.group(1).strip()
            data['series'] = unescape(coll_match.group(2).strip())

        if slug:
            data['url'] = f'https://letterboxd.com/film/{slug}/'
        clean = {k: v for k, v in data.items() if v not in (None, '', [])}
        return MediaItem(mediaID=slug, data=clean, access_system='letterboxd')

    def get_item(self, slug_or_url: str) -> MediaItem:
        raw = str(slug_or_url).strip().strip('/')
        match = re.search(r'letterboxd\.com/film/([^/?#]+)', raw)
        slug = match.group(1) if match else raw
        url = f'https://letterboxd.com/film/{slug}/'
        html = self._fetch(url)
        return self.parse_film_html(html, slug=slug)

    def search(self, query: str, results: int = 10) -> list[MediaItem]:
        url = f'https://letterboxd.com/s/search/{quote_plus(query.strip())}/'
        html = self._fetch(url)
        items: list[MediaItem] = []
        pattern = re.compile(
            r'<span[^>]+class=["\']film-title-wrapper["\'][^>]*>.*?'
            r'<a[^>]+href=["\']/film/([^/"\']+)/["\'][^>]*>([^<]+)</a>'
            r'(?:.*?<small[^>]*><a[^>]*>(\d{4})</a></small>)?',
            re.DOTALL | re.IGNORECASE,
        )
        for match in pattern.finditer(html):
            slug, title, year = match.group(1), unescape(match.group(2).strip()), match.group(3)
            items.append(
                MediaItem(
                    mediaID=slug,
                    data={
                        'title': title,
                        'year': year or '',
                        'kind': 'movie',
                        'url': f'https://letterboxd.com/film/{slug}/',
                    },
                    access_system='letterboxd',
                )
            )
            if len(items) >= results:
                break
        return items

    def get_series(self, collection_slug_or_item: str | MediaItem) -> Series:
        if isinstance(collection_slug_or_item, MediaItem):
            coll_slug = (
                collection_slug_or_item.get('seriesID')
                or collection_slug_or_item.mediaID
                or ''
            )
        else:
            raw = str(collection_slug_or_item).strip().strip('/')
            m = re.search(r'/films/in/([^/?#]+)', raw)
            coll_slug = m.group(1) if m else raw
        url = f'https://letterboxd.com/films/in/{coll_slug}/'
        html = self._fetch(url)
        h1_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html, re.IGNORECASE)
        series_title = unescape(h1_match.group(1).strip()) if h1_match else coll_slug
        items: list[MediaItem] = []
        tag_re = re.compile(r'<[^>]+data-film-slug=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE)
        for idx, m in enumerate(tag_re.finditer(html), start=1):
            tag_html = m.group(0)
            f_slug = m.group(1)
            name_m = re.search(r'data-film-name=["\']([^"\']+)["\']', tag_html, re.I)
            year_m = re.search(r'data-film-release-year=["\'](\d{4})["\']', tag_html, re.I)
            f_name = unescape(name_m.group(1)) if name_m else f_slug
            f_year = year_m.group(1) if year_m else ''
            items.append(
                MediaItem(
                    mediaID=f_slug,
                    data={
                        'title': f_name,
                        'year': f_year,
                        'kind': 'movie',
                        'series': series_title,
                        'seriesID': coll_slug,
                        'series position': str(idx),
                        'url': f'https://letterboxd.com/film/{f_slug}/',
                    },
                    access_system='letterboxd',
                )
            )
        return Series(
            seriesID=coll_slug,
            data={
                'title': series_title,
                'items': items,
                'url': url,
            },
            access_system='letterboxd',
        )


# ============================================================================
# 3. MyAnimeList Adapter (Jikan REST API v4)
# ============================================================================

class MALAdapter:
    """
    Adapter for MyAnimeList using Jikan REST API v4
    (`https://api.jikan.moe/v4/anime` and `/v4/manga`).
    """

    def __init__(
        self,
        base_url: str = 'https://api.jikan.moe/v4',
        fetcher: Callable[..., str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip('/')
        self._fetch = fetcher or _default_http_fetcher

    def _get_json(self, path: str) -> dict[str, Any]:
        raw = self._fetch(f'{self.base_url}{path}')
        return json.loads(raw)

    def parse_entry(self, entry: dict[str, Any], media_type: str = 'anime') -> MediaItem:
        mal_id = str(entry.get('mal_id') or '')
        title = (
            entry.get('title_english')
            or entry.get('title')
            or entry.get('title_japanese')
            or ''
        )
        year = entry.get('year')
        if not year:
            aired = (entry.get('aired') or entry.get('published') or {}).get('from') or ''
            if len(aired) >= 4 and aired[:4].isdigit():
                year = aired[:4]
        year_str = str(year) if year else ''

        genres = []
        for group in ('genres', 'themes', 'demographics'):
            for g in entry.get(group) or []:
                g_name = g.get('name')
                if g_name and g_name not in genres:
                    genres.append(g_name)

        studios = [
            Creator(
                creatorID=str(s.get('mal_id') or ''),
                name=s.get('name', ''),
                role='studio',
                access_system='mal',
            )
            for s in (entry.get('studios') or [])
            if s.get('name')
        ]
        authors = [
            Creator(
                creatorID=str(a.get('mal_id') or ''),
                name=a.get('name', ''),
                role='author',
                access_system='mal',
            )
            for a in (entry.get('authors') or [])
            if a.get('name')
        ]

        relations = entry.get('relations') or []
        series_name = ''
        for rel in relations:
            rel_type = str(rel.get('relation') or '')
            if rel_type in ('Parent story', 'Prequel', 'Adaptation', 'Sequel'):
                entries = rel.get('entry') or []
                if entries and entries[0].get('name'):
                    series_name = entries[0]['name']
                    break

        data: dict[str, Any] = {
            'title': title,
            'original title': entry.get('title_japanese') or '',
            'kind': (entry.get('type') or media_type).lower(),
            'year': year_str,
            'rating': entry.get('score'),
            'rating_scale': 10,
            'votes': entry.get('scored_by'),
            'language': 'Japanese',
            'country': 'Japan',
            'genres': genres,
            'plot': clean_html_text(entry.get('synopsis') or ''),
            'studios': studios,
            'authors': authors,
            'episodes': entry.get('episodes'),
            'chapters': entry.get('chapters'),
            'runtime': entry.get('duration') or '',
            'series': series_name,
            'relations': relations,
            'url': entry.get('url') or f'https://myanimelist.net/{media_type}/{mal_id}',
        }
        clean = {k: v for k, v in data.items() if v not in (None, '', [])}
        return MediaItem(mediaID=mal_id, data=clean, access_system='mal')

    def search(
        self, query: str, results: int = 10, media_type: str = 'anime'
    ) -> list[MediaItem]:
        params = urlencode({'q': query.strip(), 'limit': min(max(1, results), 25)})
        payload = self._get_json(f'/{media_type}?{params}')
        return [
            self.parse_entry(item, media_type=media_type)
            for item in (payload.get('data') or [])[:results]
        ]

    def get_item(self, mal_id: str | int, media_type: str = 'anime') -> MediaItem:
        clean_id = re.sub(r'\D', '', str(mal_id))
        payload = self._get_json(f'/{media_type}/{clean_id}/full')
        return self.parse_entry(payload.get('data') or {}, media_type=media_type)

    def get_series(
        self, mal_id_or_item: str | int | MediaItem, media_type: str = 'anime'
    ) -> Series:
        if isinstance(mal_id_or_item, MediaItem):
            root_item = mal_id_or_item
            if 'relations' not in root_item.data and root_item.mediaID:
                root_item = self.get_item(root_item.mediaID, media_type=media_type)
        else:
            root_item = self.get_item(mal_id_or_item, media_type=media_type)

        items: list[MediaItem] = [root_item]
        for rel in root_item.get('relations') or []:
            rel_type = rel.get('relation') or 'Related'
            for ent in rel.get('entry') or []:
                ent_id = str(ent.get('mal_id') or '')
                ent_type = (ent.get('type') or 'anime').lower()
                items.append(
                    MediaItem(
                        mediaID=ent_id,
                        data={
                            'title': ent.get('name') or '',
                            'kind': ent_type,
                            'relation_type': rel_type,
                            'series': root_item.get('title') or '',
                            'url': ent.get('url') or '',
                        },
                        access_system='mal',
                    )
                )
        return Series(
            seriesID=root_item.mediaID,
            data={
                'title': f"{root_item.get('title', 'Franchise')} Franchise",
                'description': root_item.get('plot') or '',
                'items': items,
                'url': root_item.get('url') or '',
            },
            access_system='mal',
        )


# ============================================================================
# 4. AniList Adapter (Public GraphQL API `https://graphql.anilist.co`)
# ============================================================================

_ANILIST_MEDIA_QUERY = """
query ($id: Int, $search: String, $type: MediaType) {
  Media(id: $id, search: $search, type: $type) {
    id
    type
    format
    title { romaji english native }
    startDate { year }
    averageScore
    popularity
    countryOfOrigin
    episodes
    chapters
    duration
    genres
    description(asHtml: false)
    siteUrl
    studios(isMain: true) { nodes { id name } }
    staff(perPage: 4) { edges { role node { id name { full } } } }
    relations {
      edges {
        relationType(version: 2)
        node {
          id
          type
          format
          title { romaji english }
          startDate { year }
          averageScore
          episodes
          chapters
          description(asHtml: false)
          siteUrl
        }
      }
    }
  }
}
"""


class AniListAdapter:
    """
    Adapter for AniList's public GraphQL API (`https://graphql.anilist.co`).
    Supports Anime, Manga, Light Novels, and franchise relation graphs.
    """

    endpoint = 'https://graphql.anilist.co'

    def __init__(self, fetcher: Callable[..., str] | None = None) -> None:
        self._fetch = fetcher or _default_http_fetcher

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({'query': query, 'variables': variables}).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        raw = self._fetch(self.endpoint, headers=headers, method='POST', body=body)
        return json.loads(raw)

    def parse_media(self, node: dict[str, Any]) -> MediaItem:
        al_id = str(node.get('id') or '')
        title_obj = node.get('title') or {}
        title = (
            title_obj.get('english')
            or title_obj.get('romaji')
            or title_obj.get('native')
            or ''
        )
        year = str((node.get('startDate') or {}).get('year') or '')
        avg_score = node.get('averageScore')
        rating = round(float(avg_score) / 10.0, 2) if avg_score is not None else None

        country_code = str(node.get('countryOfOrigin') or 'JP').upper()
        country = _normalize_country(country_code)
        language = COUNTRY_DEFAULT_LANGUAGE.get(country, 'Japanese')

        studios = [
            Creator(
                creatorID=str(s.get('id') or ''),
                name=s.get('name', ''),
                role='studio',
                access_system='anilist',
            )
            for s in ((node.get('studios') or {}).get('nodes') or [])
            if s.get('name')
        ]
        authors = [
            Creator(
                creatorID=str((edge.get('node') or {}).get('id') or ''),
                name=((edge.get('node') or {}).get('name') or {}).get('full', ''),
                role=str(edge.get('role') or 'staff').lower(),
                access_system='anilist',
            )
            for edge in ((node.get('staff') or {}).get('edges') or [])
            if ((edge.get('node') or {}).get('name') or {}).get('full')
        ]

        rel_edges = ((node.get('relations') or {}).get('edges') or [])
        series_name = ''
        for edge in rel_edges:
            if edge.get('relationType') in ('PREQUEL', 'PARENT', 'ADAPTATION', 'SEQUEL'):
                r_title = ((edge.get('node') or {}).get('title') or {})
                series_name = r_title.get('english') or r_title.get('romaji') or ''
                if series_name:
                    break

        fmt = str(node.get('format') or node.get('type') or 'ANIME').lower()
        kind = 'light novel' if fmt == 'novel' else ('manga' if fmt == 'manga' else 'anime')

        data: dict[str, Any] = {
            'title': title,
            'original title': title_obj.get('native') or '',
            'kind': kind,
            'year': year,
            'rating': rating,
            'rating_scale': 10,
            'votes': node.get('popularity'),
            'language': language,
            'country': country,
            'genres': node.get('genres') or [],
            'plot': clean_html_text(node.get('description') or ''),
            'studios': studios,
            'authors': authors,
            'episodes': node.get('episodes'),
            'chapters': node.get('chapters'),
            'runtime': format_runtime(node.get('duration')),
            'series': series_name,
            'relations': rel_edges,
            'url': node.get('siteUrl') or f'https://anilist.co/anime/{al_id}',
        }
        clean = {k: v for k, v in data.items() if v not in (None, '', [])}
        return MediaItem(mediaID=al_id, data=clean, access_system='anilist')

    def get_item(self, anilist_id: str | int, media_type: str = 'ANIME') -> MediaItem:
        clean_id = int(re.sub(r'\D', '', str(anilist_id)))
        payload = self._graphql(
            _ANILIST_MEDIA_QUERY, {'id': clean_id, 'type': media_type.upper()}
        )
        media = (payload.get('data') or {}).get('Media') or {}
        return self.parse_media(media)

    def search(
        self, query: str, results: int = 10, media_type: str = 'ANIME'
    ) -> list[MediaItem]:
        payload = self._graphql(
            _ANILIST_MEDIA_QUERY,
            {'search': query.strip(), 'type': media_type.upper()},
        )
        media = (payload.get('data') or {}).get('Media')
        return [self.parse_media(media)] if media else []

    def get_series(
        self, id_or_item: str | int | MediaItem, media_type: str = 'ANIME'
    ) -> Series:
        if isinstance(id_or_item, MediaItem):
            root = id_or_item
            if 'relations' not in root.data and root.mediaID:
                root = self.get_item(root.mediaID, media_type=media_type)
        else:
            root = self.get_item(id_or_item, media_type=media_type)

        items: list[MediaItem] = [root]
        books: list[MediaItem] = []
        if root.get('kind') in ('manga', 'light novel'):
            books.append(root)
        for edge in root.get('relations') or []:
            rel_type = str(edge.get('relationType') or 'RELATED').title()
            r_node = edge.get('node') or {}
            if not r_node:
                continue
            child = self.parse_media(r_node)
            child['relation_type'] = rel_type
            child['series'] = root.get('title') or ''
            items.append(child)
            if child.get('kind') in ('manga', 'light novel'):
                books.append(child)

        return Series(
            seriesID=root.mediaID,
            data={
                'title': f"{root.get('title', 'Franchise')} Series",
                'description': root.get('plot') or '',
                'books': books,
                'items': items,
                'url': root.get('url') or '',
            },
            access_system='anilist',
        )


# ============================================================================
# 5. Kitsu Adapter (Public JSON:API `https://kitsu.io/api/edge`)
# ============================================================================

class KitsuAdapter:
    """
    Adapter for Kitsu's JSON:API (`https://kitsu.io/api/edge/anime` and `/manga`).
    """

    def __init__(
        self,
        base_url: str = 'https://kitsu.io/api/edge',
        fetcher: Callable[..., str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip('/')
        self._fetch = fetcher or _default_http_fetcher

    def _get_json(self, path: str) -> dict[str, Any]:
        raw = self._fetch(
            f'{self.base_url}{path}',
            headers={'Accept': 'application/vnd.api+json'},
        )
        return json.loads(raw)

    def parse_resource(
        self,
        resource: dict[str, Any],
        included: list[dict[str, Any]] | None = None,
    ) -> MediaItem:
        k_id = str(resource.get('id') or '')
        r_type = str(resource.get('type') or 'anime').lower()
        attrs = resource.get('attributes') or {}
        titles = attrs.get('titles') or {}
        title = (
            titles.get('en')
            or titles.get('en_jp')
            or attrs.get('canonicalTitle')
            or ''
        )
        start_date = str(attrs.get('startDate') or '')
        year = start_date[:4] if len(start_date) >= 4 and start_date[:4].isdigit() else ''

        avg_rating = attrs.get('averageRating')
        rating = None
        if avg_rating not in (None, ''):
            try:
                # Kitsu stores averageRating on a 0-100 scale
                rating = round(float(avg_rating) / 10.0, 2)
            except (TypeError, ValueError):
                pass

        genres: list[str] = []
        related_items: list[MediaItem] = []
        for inc in included or []:
            inc_type = inc.get('type')
            inc_attrs = inc.get('attributes') or {}
            if inc_type == 'categories':
                cat_title = inc_attrs.get('title')
                if cat_title and cat_title not in genres:
                    genres.append(cat_title)
            elif inc_type in ('anime', 'manga') and str(inc.get('id')) != k_id:
                related_items.append(self.parse_resource(inc))

        data: dict[str, Any] = {
            'title': title,
            'original title': titles.get('ja_jp') or '',
            'kind': r_type,
            'year': year,
            'rating': rating,
            'rating_scale': 10,
            'language': 'Japanese',
            'country': 'Japan',
            'genres': genres,
            'plot': clean_html_text(
                attrs.get('synopsis') or attrs.get('description') or ''
            ),
            'episodes': attrs.get('episodeCount'),
            'chapters': attrs.get('chapterCount'),
            'runtime': format_runtime(attrs.get('episodeLength')),
            'related_items': related_items,
            'url': f'https://kitsu.io/{r_type}/{attrs.get("slug") or k_id}',
        }
        clean = {k: v for k, v in data.items() if v not in (None, '', [])}
        return MediaItem(mediaID=k_id, data=clean, access_system='kitsu')

    def search(
        self, query: str, results: int = 10, media_type: str = 'anime'
    ) -> list[MediaItem]:
        params = urlencode({
            'filter[text]': query.strip(),
            'page[limit]': min(max(1, results), 20),
            'include': 'categories',
        })
        payload = self._get_json(f'/{media_type}?{params}')
        included = payload.get('included') or []
        return [
            self.parse_resource(item, included=included)
            for item in (payload.get('data') or [])[:results]
        ]

    def get_item(self, kitsu_id: str | int, media_type: str = 'anime') -> MediaItem:
        clean_id = re.sub(r'\D', '', str(kitsu_id))
        payload = self._get_json(
            f'/{media_type}/{clean_id}?include=categories,mediaRelationships.destination'
        )
        return self.parse_resource(
            payload.get('data') or {}, included=payload.get('included') or []
        )

    def get_series(
        self, kitsu_id_or_item: str | int | MediaItem, media_type: str = 'anime'
    ) -> Series:
        if isinstance(kitsu_id_or_item, MediaItem):
            root = kitsu_id_or_item
        else:
            root = self.get_item(kitsu_id_or_item, media_type=media_type)
        items = [root] + list(root.get('related_items') or [])
        return Series(
            seriesID=root.mediaID,
            data={
                'title': f"{root.get('title', 'Series')} Franchise",
                'description': root.get('plot') or '',
                'items': items,
                'url': root.get('url') or '',
            },
            access_system='kitsu',
        )


# ============================================================================
# 6. Goodreads Adapter (`__NEXT_DATA__`, JSON-LD, Autocomplete & `/series/`)
# ============================================================================

class GoodreadsAdapter:
    """
    Adapter for Goodreads book and series pages using embedded structured JSON
    (`__NEXT_DATA__` Apollo state, JSON-LD, and `ReactComponents.SeriesList`).
    """

    def __init__(self, fetcher: Callable[..., str] | None = None) -> None:
        self._fetch = fetcher or _default_http_fetcher

    def search(self, query: str, results: int = 10) -> list[MediaItem]:
        url = (
            'https://www.goodreads.com/book/auto_complete?format=json&q='
            + quote_plus(query.strip())
        )
        raw = self._fetch(url)
        items = json.loads(raw)
        books: list[MediaItem] = []
        for entry in (items or [])[:results]:
            book_id = str(entry.get('bookId') or '')
            title = entry.get('bookTitleBare') or entry.get('title') or ''
            author_data = entry.get('author') or {}
            authors = []
            if author_data.get('name'):
                authors.append(
                    Creator(
                        creatorID=str(author_data.get('id') or ''),
                        name=author_data['name'],
                        role='author',
                        access_system='goodreads',
                    )
                )
            rating = entry.get('avgRating')
            if rating is not None:
                try:
                    rating = float(rating)
                except (TypeError, ValueError):
                    pass
            desc = clean_html_text(
                (entry.get('description') or {}).get('html') or ''
            )
            data: dict[str, Any] = {
                'title': title,
                'kind': 'book',
                'rating': rating,
                'rating_scale': 5,
                'votes': entry.get('ratingsCount'),
                'authors': authors,
                'plot': desc,
                'cover url': entry.get('imageUrl') or '',
                'url': f'https://www.goodreads.com/book/show/{book_id}' if book_id else '',
            }
            books.append(
                MediaItem(
                    mediaID=book_id,
                    data={k: v for k, v in data.items() if v not in (None, '', [])},
                    access_system='goodreads',
                )
            )
        return books

    def parse_book_html(self, html: str, book_id: str | None = None) -> MediaItem:
        data: dict[str, Any] = {'kind': 'book', 'rating_scale': 5}

        ld_match = _RE_SCRIPT_JSON_LD.search(html)
        if ld_match:
            try:
                ld = json.loads(ld_match.group(1).strip())
                if isinstance(ld, dict):
                    if ld.get('name'):
                        data['title'] = unescape(str(ld['name']))
                    if ld.get('inLanguage'):
                        data['language'] = _normalize_language(ld['inLanguage'])
                    if ld.get('numberOfPages'):
                        data['pages'] = int(ld['numberOfPages'])
                    agg = ld.get('aggregateRating') or {}
                    if agg.get('ratingValue') is not None:
                        data['rating'] = round(float(agg['ratingValue']), 2)
                    if agg.get('ratingCount') is not None:
                        data['votes'] = int(agg['ratingCount'])
                    ld_authors = ld.get('author') or []
                    if isinstance(ld_authors, dict):
                        ld_authors = [ld_authors]
                    authors = [
                        Creator(name=a['name'], role='author', access_system='goodreads')
                        for a in ld_authors
                        if isinstance(a, dict) and a.get('name')
                    ]
                    if authors:
                        data['authors'] = authors
            except Exception:
                pass

        next_match = _RE_SCRIPT_NEXT_DATA.search(html)
        if next_match:
            try:
                nd = json.loads(next_match.group(1).strip())
                apollo = (
                    nd.get('props', {}).get('pageProps', {}).get('apolloState', {})
                )
                book_node: dict[str, Any] = {}
                series_nodes: dict[str, dict[str, Any]] = {}
                contributor_nodes: dict[str, dict[str, Any]] = {}
                work_node: dict[str, Any] = {}

                for key, val in apollo.items():
                    if not isinstance(val, dict):
                        continue
                    typename = val.get('__typename')
                    if typename == 'Book' or key.startswith('Book:'):
                        if val.get('title') and (
                            not book_node or val.get('description')
                        ):
                            book_node = val
                    elif typename == 'Series' or key.startswith('Series:'):
                        series_nodes[key] = val
                    elif typename == 'Contributor' or key.startswith('Contributor:'):
                        contributor_nodes[key] = val
                    elif typename == 'Work' or key.startswith('Work:'):
                        if not work_node or val.get('stats'):
                            work_node = val

                if book_node:
                    if not book_id and book_node.get('legacyId'):
                        book_id = str(book_node['legacyId'])
                    if book_node.get('title'):
                        data['title'] = book_node['title']
                    if book_node.get('description'):
                        data['plot'] = clean_html_text(book_node['description'])
                    details = book_node.get('details') or {}
                    if details.get('publisher'):
                        data['publisher'] = details['publisher']
                    if details.get('publicationCountry'):
                        data['country'] = _normalize_country(details['publicationCountry'])
                    if details.get('numPages'):
                        data['pages'] = details['numPages']
                    lang_obj = details.get('language') or {}
                    if isinstance(lang_obj, dict) and lang_obj.get('name'):
                        data['language'] = _normalize_language(lang_obj['name'])
                    pub_time = details.get('publicationTime')
                    if pub_time is not None:
                        ts = float(pub_time)
                        if ts > 1e10:
                            ts /= 1000.0
                        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                        data['year'] = str(dt.year)

                    genres = [
                        (bg.get('genre') or {}).get('name')
                        for bg in (book_node.get('bookGenres') or [])
                        if (bg.get('genre') or {}).get('name')
                    ]
                    if genres:
                        data['genres'] = genres

                    authors = []
                    primary_edge = book_node.get('primaryContributorEdge') or {}
                    for edge in [primary_edge] + (
                        book_node.get('secondaryContributorEdges') or []
                    ):
                        if not isinstance(edge, dict):
                            continue
                        ref = edge.get('node') or {}
                        node = (
                            contributor_nodes.get(ref['__ref'], {})
                            if isinstance(ref, dict) and '__ref' in ref
                            else (ref if isinstance(ref, dict) else {})
                        )
                        if node.get('name'):
                            authors.append(
                                Creator(
                                    creatorID=str(node.get('legacyId') or ''),
                                    name=node['name'],
                                    role=str(edge.get('role') or 'author').lower(),
                                    access_system='goodreads',
                                )
                            )
                    if authors:
                        data['authors'] = authors

                    book_series = book_node.get('bookSeries') or []
                    if book_series:
                        bs = book_series[0]
                        pos = bs.get('userPosition') or bs.get('position') or ''
                        s_ref = bs.get('series') or {}
                        s_node = (
                            series_nodes.get(s_ref['__ref'], {})
                            if isinstance(s_ref, dict) and '__ref' in s_ref
                            else (s_ref if isinstance(s_ref, dict) else {})
                        )
                        s_title = s_node.get('title')
                        s_url = s_node.get('webUrl') or ''
                        s_match = _RE_GOODREADS_SERIES_ID.search(s_url)
                        s_id = s_match.group(1) if s_match else str(s_node.get('legacyId') or '')
                        if s_title:
                            data['series'] = s_title
                        if s_id:
                            data['seriesID'] = s_id
                        if pos not in (None, ''):
                            data['series position'] = str(pos)

                if work_node:
                    stats = work_node.get('stats') or {}
                    if stats.get('averageRating') is not None:
                        data['rating'] = round(float(stats['averageRating']), 2)
                    if stats.get('ratingsCount') is not None:
                        data['votes'] = int(stats['ratingsCount'])
            except Exception:
                pass

        if book_id and 'url' not in data:
            data['url'] = f'https://www.goodreads.com/book/show/{book_id}'
        clean = {k: v for k, v in data.items() if v not in (None, '', [])}
        return MediaItem(mediaID=book_id, data=clean, access_system='goodreads')

    def get_item(self, book_id_or_url: str) -> MediaItem:
        raw = str(book_id_or_url).strip()
        match = _RE_GOODREADS_BOOK_ID.search(raw)
        book_id = match.group(1) if match else raw
        url = (
            raw
            if raw.startswith('http')
            else f'https://www.goodreads.com/book/show/{book_id}'
        )
        html = self._fetch(url)
        return self.parse_book_html(html, book_id=book_id)

    def parse_series_html(self, html: str, series_id: str | None = None) -> Series:
        series_title = ''
        series_desc = ''
        books: list[MediaItem] = []

        for match in _RE_SERIES_REACT_PROPS.finditer(html):
            raw_props = unescape(match.group(1))
            try:
                props = json.loads(raw_props)
            except json.JSONDecodeError:
                continue
            if props.get('title') and not series_title:
                series_title = str(props['title']).strip()
            if (props.get('subtitle') or props.get('description')) and not series_desc:
                series_desc = clean_html_text(
                    props.get('subtitle') or props.get('description')
                )

            for entry in props.get('series') or []:
                if not isinstance(entry, dict):
                    continue
                b_obj = entry.get('book') or entry
                header_text = str(entry.get('seriesHeader') or '')
                pos_match = re.search(
                    r'Book\s+([0-9]+(?:\.[0-9]+)?|\d+-\d+)', header_text, re.I
                )
                pos = (
                    pos_match.group(1)
                    if pos_match
                    else str(b_obj.get('position') or '')
                )
                b_id = str(b_obj.get('bookId') or b_obj.get('id') or '')
                b_title = b_obj.get('bookTitleBare') or b_obj.get('title') or ''
                if not b_title:
                    continue
                author_info = b_obj.get('author') or {}
                authors = (
                    [
                        Creator(
                            creatorID=str(author_info.get('id') or ''),
                            name=author_info['name'],
                            role='author',
                            access_system='goodreads',
                        )
                    ]
                    if author_info.get('name')
                    else []
                )
                pub_year = str(
                    b_obj.get('publicationYear') or b_obj.get('publicationDate') or ''
                )
                ym = re.search(r'(\d{4})', pub_year)
                year = ym.group(1) if ym else ''
                desc_obj = b_obj.get('description')
                plot = clean_html_text(
                    desc_obj.get('html')
                    if isinstance(desc_obj, dict)
                    else str(desc_obj or '')
                )
                b_data: dict[str, Any] = {
                    'title': b_title,
                    'kind': 'book',
                    'year': year,
                    'rating': b_obj.get('avgRating'),
                    'rating_scale': 5,
                    'votes': b_obj.get('ratingsCount'),
                    'authors': authors,
                    'pages': b_obj.get('numPages'),
                    'plot': plot,
                    'series': series_title,
                    'seriesID': series_id or '',
                    'series position': pos,
                    'url': f'https://www.goodreads.com/book/show/{b_id}' if b_id else '',
                }
                books.append(
                    MediaItem(
                        mediaID=b_id,
                        data={k: v for k, v in b_data.items() if v not in (None, '', [])},
                        access_system='goodreads',
                    )
                )

        if series_title:
            for b in books:
                b['series'] = series_title
        books.sort(key=lambda b: _sequence_sort_key(b.get('series position')))
        authors = books[0]['authors'] if books and books[0].get('authors') else []
        return Series(
            seriesID=series_id,
            data={
                'title': series_title or 'Unknown Series',
                'description': series_desc,
                'authors': authors,
                'books': books,
                'items': list(books),
                'url': f'https://www.goodreads.com/series/{series_id}' if series_id else '',
            },
            access_system='goodreads',
        )

    def get_series(self, series_id_or_item: str | MediaItem) -> Series:
        if isinstance(series_id_or_item, MediaItem):
            series_id = series_id_or_item.get('seriesID') or ''
        else:
            raw = str(series_id_or_item).strip()
            m = _RE_GOODREADS_SERIES_ID.search(raw)
            series_id = m.group(1) if m else raw
        url = (
            series_id
            if str(series_id).startswith('http')
            else f'https://www.goodreads.com/series/{series_id}'
        )
        html = self._fetch(url)
        return self.parse_series_html(html, series_id=str(series_id))


# ============================================================================
# 7. Audible Adapter (Unauthenticated Catalog JSON API & `relationships`)
# ============================================================================

class AudibleAdapter:
    """
    Adapter for Audible's JSON Catalog API
    (`https://api.audible.<tld>/1.0/catalog/products`).
    """

    def __init__(
        self,
        marketplace: str = 'in',
        fetcher: Callable[..., str] | None = None,
    ) -> None:
        mp = AUDIBLE_MARKETPLACES.get(marketplace.lower(), AUDIBLE_MARKETPLACES['us'])
        self.marketplace = marketplace.lower()
        self.tld = mp['tld']
        self.default_country = mp['country']
        self.base_url = f'https://api.audible.{self.tld}/1.0/catalog/products'
        self._fetch = fetcher or _default_http_fetcher

    def _get_json(self, url: str) -> dict[str, Any]:
        return json.loads(self._fetch(url))

    def parse_product(self, product: dict[str, Any]) -> MediaItem:
        asin = product.get('asin') or ''
        title = product.get('title') or ''
        release_date = product.get('release_date') or product.get('issue_date') or ''
        year = release_date[:4] if len(release_date) >= 4 and release_date[:4].isdigit() else ''

        rating_obj = (
            product.get('rating', {}).get('overall_distribution')
            or product.get('rating')
            or {}
        )
        rating = rating_obj.get('display_average_rating') or rating_obj.get('average_rating')
        if rating is not None:
            rating = round(float(rating), 2)

        authors = [
            Creator(
                creatorID=a.get('asin'),
                name=a.get('name', ''),
                role='author',
                access_system='audible',
            )
            for a in (product.get('authors') or [])
            if a.get('name')
        ]
        narrators = [
            Creator(
                creatorID=n.get('asin'),
                name=n.get('name', ''),
                role='narrator',
                access_system='audible',
            )
            for n in (product.get('narrators') or [])
            if n.get('name')
        ]

        genres: list[str] = []
        for ladder_entry in product.get('category_ladders') or []:
            for step in ladder_entry.get('ladder') or []:
                name = step.get('name')
                if name and name not in genres:
                    genres.append(name)

        series_list = product.get('series') or []
        primary_series = series_list[0] if series_list else {}
        runtime_mins = product.get('runtime_length_min')

        data: dict[str, Any] = {
            'title': title,
            'subtitle': product.get('subtitle') or '',
            'kind': 'audiobook',
            'year': year,
            'rating': rating,
            'rating_scale': 5,
            'votes': rating_obj.get('num_ratings'),
            'language': _normalize_language(product.get('language')),
            'country': self.default_country,
            'genres': genres,
            'plot': clean_html_text(
                product.get('publisher_summary')
                or product.get('merchandising_summary')
                or ''
            ),
            'authors': authors,
            'narrators': narrators,
            'runtime_minutes': runtime_mins,
            'runtime': format_runtime(runtime_mins),
            'format_type': product.get('format_type') or '',
            'series': primary_series.get('title') or primary_series.get('name') or '',
            'seriesID': primary_series.get('asin') or '',
            'series position': str(
                primary_series.get('sequence') or primary_series.get('position') or ''
            ),
            'url': f'https://www.audible.{self.tld}/pd/{asin}' if asin else '',
        }
        clean = {k: v for k, v in data.items() if v not in (None, '', [])}
        return MediaItem(mediaID=asin, data=clean, access_system='audible')

    def search(self, query: str, results: int = 10) -> list[MediaItem]:
        params = urlencode({
            'keywords': query.strip(),
            'num_results': min(max(1, results), 50),
            'products_sort_by': 'Relevance',
            'response_groups': AUDIBLE_RESPONSE_GROUPS,
        })
        payload = self._get_json(f'{self.base_url}?{params}')
        return [
            self.parse_product(p)
            for p in (payload.get('products') or [])[:results]
        ]

    def get_item(self, asin: str) -> MediaItem:
        m = _RE_AUDIBLE_ASIN.search(str(asin))
        clean_asin = m.group(1) if m else str(asin).strip()
        params = urlencode({'response_groups': AUDIBLE_RESPONSE_GROUPS})
        payload = self._get_json(f'{self.base_url}/{clean_asin}?{params}')
        product = payload.get('product') or payload
        return self.parse_product(product)

    def get_series(self, series_asin_or_item: str | MediaItem) -> Series:
        if isinstance(series_asin_or_item, MediaItem):
            series_asin = (
                series_asin_or_item.get('seriesID')
                or series_asin_or_item.mediaID
                or ''
            )
        else:
            m = _RE_AUDIBLE_ASIN.search(str(series_asin_or_item))
            series_asin = m.group(1) if m else str(series_asin_or_item).strip()

        params = urlencode({'response_groups': AUDIBLE_RESPONSE_GROUPS})
        payload = self._get_json(f'{self.base_url}/{series_asin}?{params}')
        series_product = payload.get('product') or payload

        if (
            series_product.get('content_delivery_type') != 'BookSeries'
            and not any(
                r.get('relationship_type') == 'series'
                and r.get('relationship_to_product') == 'child'
                for r in (series_product.get('relationships') or [])
            )
            and series_product.get('series')
        ):
            series_asin = series_product['series'][0].get('asin') or series_asin
            payload = self._get_json(f'{self.base_url}/{series_asin}?{params}')
            series_product = payload.get('product') or payload

        series_title = series_product.get('title') or 'Unknown Series'
        series_desc = clean_html_text(
            series_product.get('publisher_summary')
            or series_product.get('merchandising_summary')
            or ''
        )
        child_rels = [
            rel
            for rel in (series_product.get('relationships') or [])
            if rel.get('relationship_type') == 'series'
            and rel.get('relationship_to_product') == 'child'
            and rel.get('asin')
        ]
        child_rels.sort(
            key=lambda r: _sequence_sort_key(r.get('sequence') or r.get('sort'))
        )
        child_map = {r['asin']: r for r in child_rels}
        child_asins = list(child_map.keys())

        audiobooks: list[MediaItem] = []
        if child_asins:
            batch_params = urlencode({
                'asins': ','.join(child_asins[:50]),
                'response_groups': AUDIBLE_RESPONSE_GROUPS,
            })
            batch_payload = self._get_json(f'{self.base_url}?{batch_params}')
            by_asin = {
                p.get('asin'): p
                for p in (batch_payload.get('products') or [])
                if p.get('asin')
            }
            for asin in child_asins:
                rel = child_map[asin]
                prod = by_asin.get(asin)
                ab = (
                    self.parse_product(prod)
                    if prod
                    else MediaItem(
                        mediaID=asin,
                        data={'title': rel.get('title') or '', 'kind': 'audiobook'},
                        access_system='audible',
                    )
                )
                seq = rel.get('sequence') or rel.get('sort') or ab.get('series position')
                if seq not in (None, ''):
                    ab['series position'] = str(seq)
                ab['series'] = series_title
                ab['seriesID'] = series_asin
                audiobooks.append(ab)

        audiobooks.sort(key=lambda b: _sequence_sort_key(b.get('series position')))
        authors = audiobooks[0]['authors'] if audiobooks and audiobooks[0].get('authors') else []
        return Series(
            seriesID=series_asin,
            data={
                'title': series_title,
                'description': series_desc,
                'authors': authors,
                'audiobooks': audiobooks,
                'items': list(audiobooks),
                'url': f'https://www.audible.{self.tld}/pd/{series_asin}',
            },
            access_system='audible',
        )


# ============================================================================
# 8. Storytel Adapter (`__NEXT_DATA__` & JSON-LD for Audiobooks, eBooks & Series)
# ============================================================================

class StorytelAdapter:
    """
    Adapter for Storytel (`https://www.storytel.com/<locale>/books/...` and
    `/series/...`), extracting audiobooks, eBooks, and full book/audiobook series.
    """

    def __init__(
        self,
        locale: str = 'in',
        fetcher: Callable[..., str] | None = None,
    ) -> None:
        self.locale = locale.lower().strip()
        self.default_country = _normalize_country(self.locale.upper()) or 'India'
        self._fetch = fetcher or _default_http_fetcher

    def parse_consumable_dict(self, item: dict[str, Any]) -> MediaItem:
        """Parse a Storytel consumable/book JSON object into a `MediaItem`."""
        book_id = str(item.get('id') or item.get('consumableId') or '')
        title = item.get('title') or item.get('name') or ''

        authors = [
            Creator(
                creatorID=str(a.get('id') or ''),
                name=a.get('name', ''),
                role='author',
                access_system='storytel',
            )
            for a in (item.get('authors') or [])
            if isinstance(a, dict) and a.get('name')
        ]
        narrators = [
            Creator(
                creatorID=str(n.get('id') or ''),
                name=n.get('name', ''),
                role='narrator',
                access_system='storytel',
            )
            for n in (item.get('narrators') or [])
            if isinstance(n, dict) and n.get('name')
        ]

        # Storytel formats often contain both `abook` (audiobook) and `ebook`
        formats = item.get('formats') or {}
        runtime_mins = item.get('durationMinutes')
        release_date = item.get('releaseDate') or ''
        kind = 'audiobook' if narrators or 'abook' in formats else 'ebook'
        if isinstance(formats, dict):
            abook = formats.get('abook') or {}
            if abook.get('durationInMinutes') and not runtime_mins:
                runtime_mins = abook['durationInMinutes']
            if abook.get('releaseDate') and not release_date:
                release_date = abook['releaseDate']
        year = str(release_date)[:4] if len(str(release_date)) >= 4 else ''

        series_info = item.get('series') or item.get('seriesInfo') or {}
        if isinstance(series_info, list) and series_info:
            series_info = series_info[0]
        series_name = series_info.get('name') or series_info.get('title') or ''
        series_id = str(series_info.get('id') or '')
        series_pos = str(
            series_info.get('part')
            or series_info.get('orderInSeries')
            or series_info.get('position')
            or ''
        )

        cat = item.get('category') or {}
        genres = []
        if isinstance(cat, dict) and cat.get('name'):
            genres.append(cat['name'])
        for tag in item.get('tags') or []:
            t_name = tag.get('name') if isinstance(tag, dict) else str(tag)
            if t_name and t_name not in genres:
                genres.append(t_name)

        data: dict[str, Any] = {
            'title': title,
            'kind': kind,
            'year': year,
            'rating': item.get('averageRating') or item.get('rating'),
            'rating_scale': 5,
            'votes': item.get('ratingCount'),
            'language': _normalize_language(item.get('language') or 'English'),
            'country': self.default_country,
            'genres': genres,
            'plot': clean_html_text(item.get('description') or item.get('summary') or ''),
            'authors': authors,
            'narrators': narrators,
            'runtime_minutes': runtime_mins,
            'runtime': format_runtime(runtime_mins),
            'series': series_name,
            'seriesID': series_id,
            'series position': series_pos,
            'url': item.get('url') or (
                f'https://www.storytel.com/{self.locale}/books/{book_id}'
                if book_id
                else ''
            ),
        }
        clean = {k: v for k, v in data.items() if v not in (None, '', [])}
        return MediaItem(mediaID=book_id, data=clean, access_system='storytel')

    def parse_book_page(self, html_or_json: str, book_id: str | None = None) -> MediaItem:
        stripped = html_or_json.strip()
        if stripped.startswith('{'):
            payload = json.loads(stripped)
            return self.parse_consumable_dict(payload.get('book') or payload)

        next_match = _RE_SCRIPT_NEXT_DATA.search(html_or_json)
        if next_match:
            nd = json.loads(next_match.group(1).strip())
            page_props = nd.get('props', {}).get('pageProps', {})
            book_obj = page_props.get('book') or page_props.get('consumable') or {}
            if book_obj:
                return self.parse_consumable_dict(book_obj)

        # Fallback to JSON-LD on Storytel book page
        ld_match = _RE_SCRIPT_JSON_LD.search(html_or_json)
        if ld_match:
            ld = json.loads(ld_match.group(1).strip())
            if isinstance(ld, dict):
                return self.parse_consumable_dict({
                    'id': book_id or ld.get('sku') or '',
                    'title': ld.get('name') or '',
                    'description': ld.get('description') or '',
                    'language': ld.get('inLanguage') or 'English',
                    'releaseDate': ld.get('datePublished') or '',
                    'rating': (ld.get('aggregateRating') or {}).get('ratingValue'),
                    'ratingCount': (ld.get('aggregateRating') or {}).get('ratingCount'),
                    'authors': ld.get('author') if isinstance(ld.get('author'), list) else [],
                    'narrators': ld.get('readBy') if isinstance(ld.get('readBy'), list) else [],
                })
        raise MediagoerDataAccessError('Unable to parse Storytel book page')

    def get_item(self, book_id_or_url: str) -> MediaItem:
        raw = str(book_id_or_url).strip()
        url = (
            raw
            if raw.startswith('http')
            else f'https://www.storytel.com/{self.locale}/books/{raw}'
        )
        content = self._fetch(url)
        return self.parse_book_page(content, book_id=raw)

    def search(self, query: str, results: int = 10) -> list[MediaItem]:
        url = (
            f'https://www.storytel.com/{self.locale}/search-'
            f'{quote_plus(query.strip())}'
        )
        content = self._fetch(url)
        if content.strip().startswith('{'):
            payload = json.loads(content)
            books = payload.get('books') or payload.get('items') or []
            return [self.parse_consumable_dict(b) for b in books[:results]]
        next_match = _RE_SCRIPT_NEXT_DATA.search(content)
        if next_match:
            nd = json.loads(next_match.group(1).strip())
            page_props = nd.get('props', {}).get('pageProps', {})
            books = page_props.get('books') or page_props.get('searchResults') or []
            return [self.parse_consumable_dict(b) for b in books[:results]]
        return []

    def get_series(self, series_id_or_item: str | MediaItem) -> Series:
        if isinstance(series_id_or_item, MediaItem):
            series_id = (
                series_id_or_item.get('seriesID')
                or series_id_or_item.mediaID
                or ''
            )
        else:
            series_id = str(series_id_or_item).strip()
        url = (
            series_id
            if series_id.startswith('http')
            else f'https://www.storytel.com/{self.locale}/series/{series_id}'
        )
        content = self._fetch(url)
        if content.strip().startswith('{'):
            series_payload = json.loads(content)
        else:
            next_match = _RE_SCRIPT_NEXT_DATA.search(content)
            series_payload = (
                json.loads(next_match.group(1).strip())
                .get('props', {})
                .get('pageProps', {})
                .get('series', {})
                if next_match
                else {}
            )

        series_title = series_payload.get('title') or series_payload.get('name') or 'Unknown Series'
        series_desc = clean_html_text(series_payload.get('description') or '')
        raw_items = series_payload.get('books') or series_payload.get('items') or []

        books: list[MediaItem] = []
        audiobooks: list[MediaItem] = []
        all_items: list[MediaItem] = []
        for idx, raw_b in enumerate(raw_items, start=1):
            parsed = self.parse_consumable_dict(raw_b)
            if not parsed.get('series'):
                parsed['series'] = series_title
            if not parsed.get('series position'):
                parsed['series position'] = str(idx)
            all_items.append(parsed)
            if parsed.get('kind') == 'audiobook':
                audiobooks.append(parsed)
            else:
                books.append(parsed)

        return Series(
            seriesID=str(series_payload.get('id') or series_id),
            data={
                'title': series_title,
                'description': series_desc,
                'books': books,
                'audiobooks': audiobooks,
                'items': all_items,
                'url': url,
            },
            access_system='storytel',
        )


# ============================================================================
# Unified Mediagoer Factory & Facade
# ============================================================================

class Mediagoer:
    """
    Single unified library interface across all 8 platforms:
    - `imdb`
    - `letterboxd`
    - `mal` (MyAnimeList)
    - `anilist`
    - `kitsu`
    - `goodreads`
    - `audible`
    - `storytel`
    """

    def __init__(
        self,
        provider: str = 'imdb',
        audible_marketplace: str = 'in',
        storytel_locale: str = 'in',
        imdb_uri: str | None = None,
        fetcher: Callable[..., str] | None = None,
    ) -> None:
        norm = PROVIDER_ALIASES.get(provider.lower().strip())
        if not norm:
            raise MediagoerError(
                f'Unknown provider {provider!r}; expected one of: '
                f'{", ".join(available_providers())}'
            )
        self.provider = norm
        self.imdb = IMDbAdapter(s3_uri=imdb_uri, fetcher=fetcher)
        self.letterboxd = LetterboxdAdapter(fetcher=fetcher)
        self.mal = MALAdapter(fetcher=fetcher)
        self.anilist = AniListAdapter(fetcher=fetcher)
        self.kitsu = KitsuAdapter(fetcher=fetcher)
        self.goodreads = GoodreadsAdapter(fetcher=fetcher)
        self.audible = AudibleAdapter(
            marketplace=audible_marketplace, fetcher=fetcher
        )
        self.storytel = StorytelAdapter(locale=storytel_locale, fetcher=fetcher)
        self._adapters: dict[str, Any] = {
            'imdb': self.imdb,
            'letterboxd': self.letterboxd,
            'mal': self.mal,
            'anilist': self.anilist,
            'kitsu': self.kitsu,
            'goodreads': self.goodreads,
            'audible': self.audible,
            'storytel': self.storytel,
        }

    def detect_provider(self, identifier_or_url: str) -> str:
        """Auto-detect provider from a URL or ID prefix, or fall back to default."""
        s = str(identifier_or_url).strip().lower()
        if 'imdb.com' in s or re.fullmatch(r'tt\d{7,10}', s):
            return 'imdb'
        if 'letterboxd.com' in s or 'boxd.it' in s:
            return 'letterboxd'
        if 'myanimelist.net' in s or 'jikan.moe' in s:
            return 'mal'
        if 'anilist.co' in s:
            return 'anilist'
        if 'kitsu.io' in s or 'kitsu.app' in s:
            return 'kitsu'
        if 'goodreads.com' in s:
            return 'goodreads'
        if 'audible.' in s or re.fullmatch(r'b[0-9a-z]{9}', s):
            return 'audible'
        if 'storytel.com' in s:
            return 'storytel'
        return self.provider if self.provider in self._adapters else 'imdb'

    def get_adapter(self, provider: str | None = None) -> Any:
        target = PROVIDER_ALIASES.get(
            (provider or self.provider).lower().strip(), self.provider
        )
        if target not in self._adapters:
            raise MediagoerError(f'Unsupported provider: {provider!r}')
        return self._adapters[target]

    def search(
        self,
        query: str,
        provider: str | None = None,
        results: int = 10,
        **kwargs: Any,
    ) -> list[MediaItem]:
        """Search for titles on the specified (or default) provider."""
        adapter = self.get_adapter(provider)
        return adapter.search(query, results=results, **kwargs)

    def get(
        self,
        identifier: str,
        provider: str | None = None,
        **kwargs: Any,
    ) -> MediaItem:
        """Fetch a single `MediaItem` by ID or URL, auto-detecting URL providers."""
        resolved_provider = provider or self.detect_provider(identifier)
        adapter = self.get_adapter(resolved_provider)
        return adapter.get_item(identifier, **kwargs)

    def get_card(
        self,
        identifier: str,
        provider: str | None = None,
        header_tag: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Fetch an item and return its formatted Unicode emoji card."""
        item = self.get(identifier, provider=provider, **kwargs)
        return item.format_card(header_tag=header_tag)

    def get_series(
        self,
        series_identifier: str | MediaItem,
        provider: str | None = None,
        audible_series_id: str | None = None,
        goodreads_series_id: str | None = None,
        storytel_series_id: str | None = None,
        **kwargs: Any,
    ) -> Series:
        """
        Fetch a `Series` object containing all titles in that series/franchise
        and short info for all books, audiobooks, movies, or anime/manga.
        If multiple book/audiobook IDs (`goodreads_series_id`, `audible_series_id`,
        `storytel_series_id`) are supplied, combines their books and audiobooks
        into a single unified `Series` container.
        """
        if any((audible_series_id, goodreads_series_id, storytel_series_id)):
            books: list[MediaItem] = []
            audiobooks: list[MediaItem] = []
            title = ''
            desc = ''
            authors: list[Creator] = []
            ids: list[str] = []

            if goodreads_series_id:
                gr_s = self.goodreads.get_series(goodreads_series_id)
                title = title or gr_s.get('title', '')
                desc = desc or gr_s.get('description', '')
                authors = authors or (gr_s.get('authors') or [])
                books.extend(gr_s.get('books') or [])
                ids.append(f'gr:{gr_s.seriesID}')
            if audible_series_id:
                au_s = self.audible.get_series(audible_series_id)
                title = title or au_s.get('title', '')
                desc = desc or au_s.get('description', '')
                authors = authors or (au_s.get('authors') or [])
                audiobooks.extend(au_s.get('audiobooks') or [])
                ids.append(f'audible:{au_s.seriesID}')
            if storytel_series_id:
                st_s = self.storytel.get_series(storytel_series_id)
                title = title or st_s.get('title', '')
                desc = desc or st_s.get('description', '')
                books.extend(st_s.get('books') or [])
                audiobooks.extend(st_s.get('audiobooks') or [])
                ids.append(f'storytel:{st_s.seriesID}')

            return Series(
                seriesID='/'.join(ids),
                data={
                    'title': title or 'Combined Series',
                    'description': desc,
                    'authors': authors,
                    'books': books,
                    'audiobooks': audiobooks,
                    'items': books + audiobooks,
                },
                access_system='books_hybrid',
            )

        if isinstance(series_identifier, MediaItem):
            resolved = provider or series_identifier.accessSystem
        else:
            resolved = provider or self.detect_provider(series_identifier)
        adapter = self.get_adapter(resolved)
        return adapter.get_series(series_identifier, **kwargs)

    def get_series_info(
        self,
        series_identifier: str | MediaItem,
        provider: str | None = None,
        audible_series_id: str | None = None,
        goodreads_series_id: str | None = None,
        storytel_series_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Return the formatted series overview with short info for all titles."""
        series = self.get_series(
            series_identifier,
            provider=provider,
            audible_series_id=audible_series_id,
            goodreads_series_id=goodreads_series_id,
            storytel_series_id=storytel_series_id,
            **kwargs,
        )
        return series.format_series_info()


# Alias matching Cinemagoer's IMDb / Cinemagoer convention
MediaDB = Mediagoer


def _run_demo() -> None:
    """Print sample formatted cards across Movie, Anime, Book/Audiobook, and Series."""
    samples = [
        MediaItem(
            mediaID='tt32109876',
            data={
                'title': 'The Scandal',
                'year': '2026',
                'rating': 6.6,
                'rating_scale': 10,
                'language': 'Korean',
                'country': 'South Korea',
                'genres': ['Drama'],
                'plot': (
                    'In Joseon, a secret proposal ignites hidden desires in a '
                    'gifted noblewoman, a famed lover and an unsuspecting lady '
                    'caught in their dangerous game.'
                ),
            },
            access_system='imdb',
        ),
        MediaItem(
            mediaID='151807',
            data={
                'title': 'Solo Leveling',
                'series': 'Solo Leveling Franchise',
                'series position': 'Season 1',
                'year': '2024',
                'rating': 8.3,
                'rating_scale': 10,
                'language': 'Japanese',
                'country': 'Japan',
                'genres': ['Action', 'Adventure', 'Fantasy'],
                'plot': (
                    'Ten years ago, "the Gate" appeared and connected the real '
                    'world with the realm of magic and monsters. Sung Jinwoo, '
                    'known as the Weakest Hunter of All Mankind, awakens a '
                    'secret program that allows him alone to level up.'
                ),
            },
            access_system='anilist',
        ),
        MediaItem(
            mediaID='B0B3759C9F',
            data={
                'title': 'Fourth Wing',
                'series': 'The Empyrean',
                'series position': '1',
                'authors': [Creator(name='Rebecca Yarros', role='author')],
                'narrators': [
                    Creator(name='Rebecca Soler', role='narrator'),
                    Creator(name='Teddy Hamilton', role='narrator'),
                ],
                'year': '2023',
                'rating': 4.8,
                'rating_scale': 5,
                'runtime': '20 hrs 43 mins',
                'language': 'English',
                'country': 'India',
                'genres': ['Fantasy', 'Romance'],
                'plot': (
                    'Twenty-year-old Violet Sorrengail was supposed to enter '
                    'the Scribe Quadrant, living a quiet life among books and '
                    'history. Instead, her mother orders her to join the '
                    'candidates striving to become elite dragon riders.'
                ),
            },
            access_system='audible',
        ),
    ]
    for sample in samples:
        print(sample.format_card())
        print('\n' + '=' * 65 + '\n')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='mediagoer',
        description=(
            'Unified metadata & series extractor for IMDb, Letterboxd, '
            'MyAnimeList, AniList, Kitsu, Goodreads, Audible, and Storytel.'
        ),
    )
    parser.add_argument(
        '-p',
        '--provider',
        choices=available_providers(),
        default='imdb',
        help='target platform provider (default: imdb)',
    )
    parser.add_argument(
        '--marketplace',
        choices=tuple(AUDIBLE_MARKETPLACES.keys()),
        default='in',
        help='Audible marketplace code (default: in)',
    )
    parser.add_argument(
        '--locale',
        default='in',
        help='Storytel locale code (default: in)',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('demo', help='display sample cards across providers')
    sub.add_parser('providers', help='list all supported metadata providers')

    get_p = sub.add_parser('get', help='fetch an item by ID or URL and print its card')
    get_p.add_argument('identifier', help='item ID, slug, ASIN, or URL')

    search_p = sub.add_parser('search', help='search for titles on a provider')
    search_p.add_argument('query', help='search query string')
    search_p.add_argument('--first', action='store_true', help='print card for top match')

    series_p = sub.add_parser('series', help='fetch series/franchise info with all titles')
    series_p.add_argument('series_id', help='series ID, slug, ASIN, or URL')
    series_p.add_argument('--audible-id', help='optional Audible series ASIN to merge')
    series_p.add_argument('--goodreads-id', help='optional Goodreads series ID to merge')
    series_p.add_argument('--storytel-id', help='optional Storytel series ID to merge')

    args = parser.parse_args(argv)
    if args.command == 'demo':
        _run_demo()
        return 0
    if args.command == 'providers':
        for name in available_providers():
            print(name)
        return 0

    mg = Mediagoer(
        provider=args.provider,
        audible_marketplace=args.marketplace,
        storytel_locale=args.locale,
    )
    try:
        if args.command == 'get':
            print(mg.get_card(args.identifier, provider=args.provider))
        elif args.command == 'search':
            items = mg.search(args.query, provider=args.provider)
            if not items:
                print(f'No results found for {args.query!r}', file=sys.stderr)
                return 1
            if args.first:
                print(items[0].format_card())
            else:
                for idx, item in enumerate(items, start=1):
                    print(f'{idx:2d}. {item.short_info()}')
        elif args.command == 'series':
            print(
                mg.get_series_info(
                    args.series_id,
                    provider=args.provider,
                    audible_series_id=args.audible_id,
                    goodreads_series_id=args.goodreads_id,
                    storytel_series_id=args.storytel_id,
                )
            )
    except MediagoerError as exc:
        print(f'mediagoer: error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())