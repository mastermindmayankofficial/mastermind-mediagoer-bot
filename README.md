# Mastermind Multi-Media & Library Telegram Bot (Powered by Mediagoer)

A modular Telegram Bot built with `python-telegram-bot` and **Mediagoer** (`mediagoer.py`) for indexing, searching, requesting, and delivering **Books, Audiobooks, Movies, TV Series, Anime, and Manga**.

## ✨ Key Features & Modular Architecture

### 1. Unified 8-Provider `mediagoer.py` Engine
Extracts rich metadata, Unicode emoji cards, and full series/franchise breakdowns from:
- **Movies & TV Series:** `imdb` (IMDb Suggestion API + JSON-LD + `__NEXT_DATA__`), `letterboxd` (Film & Collection pages)
- **Anime & Manga:** `mal` (MyAnimeList Jikan REST v4), `anilist` (GraphQL API), `kitsu` (JSON:API)
- **Books & Audiobooks:** `goodreads` (Apollo `__NEXT_DATA__` + `/series/`), `audible` (Catalog API + `relationships`), `storytel` (`__NEXT_DATA__` + JSON-LD)

### 2. Separate Indexing Modules (`modules/indexing/`)
- **`modules/indexing/book_index.py`**: Indexes eBooks (`.epub`, `.pdf`, `.mobi`, `.azw3`, `.djvu`, `.txt`) and Audiobooks (`.mp3`, `.m4b`, `.aax`, `.flac`) using Goodreads, Audible, and Storytel metadata.
- **`modules/indexing/movie_index.py`**: Indexes Movie & TV Series files (`.mkv`, `.mp4`, `.avi`, `.mov`, `.webm`, `.flv`, `.m4v`, `.srt`) using IMDb and Letterboxd metadata (`/indexmovie`).
- **`modules/indexing/anime_index.py`**: Automatically detects and indexes Anime video releases (`[SubsPlease]`, `[Erai-raws]`, `Dual Audio`, `#anime`) and Manga archives (`.cbz`, `.cbr`) using AniList, MyAnimeList, and Kitsu metadata (`/indexanime`).
- **Unicode Card Captions**: All indexed files are captioned in the storage channel using the exact Unicode card format:
  ```text
  ⟡ The

  🏷 𝖳𝗂𝗍𝗅𝖾 : The Scandal
  📚 𝖲𝖾𝗋𝗂𝖾𝗌 : ...
  🔮 𝖸𝖾𝖺𝗋 : 2026
  ⭐️ 𝖱𝖺𝗍𝗂𝗇𝗀𝗌 : 6.6 / 10
  🔊 𝖫𝖺𝗇𝗀𝗎𝖺𝗀𝖾 : Korean
  🌏 𝖢𝗈𝗎𝗇𝗍𝗋𝗒 : South Korea
  🎭 𝖦𝖾𝗇𝖾𝗋𝗌 : 🎭 #Drama

  📜 𝖲𝗍𝗈𝗋𝗒 𝖫𝗂𝗇𝖾 : ...
  ```

### 3. Separate Search Modules (`modules/search/`)
- **`modules/search/handlers.py`**: Global multi-media search (`/search`), live metadata card lookup (`/info`, `/card`), and full series/franchise breakdown (`/series`).
- **`modules/search/movie_search.py`**: Dedicated Movie & TV Series database search (`/moviesearch`), IMDb/Letterboxd card lookup (`/movieinfo`), and film collection / TV episode lookup (`/movieseries`).
- **`modules/search/anime_search.py`**: Dedicated Anime & Manga database search (`/animesearch`), AniList/MAL/Kitsu card lookup (`/animeinfo`), and anime/manga/light novel franchise lookup (`/animeseries`).

### 4. Separate Request Modules (`modules/request/`)
- **`modules/request/handlers.py`**: Book & Audiobook requests (`/request`, `/requestbook`) backed by Audible, Goodreads, and Storytel + 4-step manual request wizard.
- **`modules/request/movie_request.py`**: Movie & TV Series requests (`/requestmovie`, `/reqmovie`) backed by IMDb and Letterboxd + 4-step manual movie request wizard.
- **`modules/request/anime_request.py`**: Anime & Manga requests (`/requestanime`, `/reqanime`) backed by AniList, MyAnimeList, and Kitsu + 4-step manual anime request wizard.

## 🚀 Quick Start
1. Configure `env.txt` (or `.env`) with `TELEGRAM_BOT_TOKEN` and your channel IDs.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the bot:
   ```bash
   python3 main.py
   ```
