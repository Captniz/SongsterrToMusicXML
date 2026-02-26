import json
import gzip
import subprocess
import sys
from pathlib import Path
from threading import Lock, Thread
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static


def _read_json_response(response) -> dict | list:
    raw_bytes = response.read()
    content_encoding = str(response.headers.get("Content-Encoding", "")).lower()

    if "gzip" in content_encoding or raw_bytes.startswith(b"\x1f\x8b"):
        raw_bytes = gzip.decompress(raw_bytes)

    return json.loads(raw_bytes.decode("utf-8"))


def send_json_to_score(track_json: dict) -> tuple[bool, str]:
    script_path = Path(__file__).with_name("Converter.py")
    if not script_path.exists():
        return False, f"Converter.py not found at: {script_path}"

    payload = json.dumps(track_json, ensure_ascii=False)

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            input=payload,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except Exception as exc:
        return False, f"Failed to execute Converter.py: {exc}"

    stdout_text = result.stdout.strip()
    stderr_text = result.stderr.strip()

    if result.returncode == 0:
        message = stdout_text or "Converter.py completed successfully."
        return True, message

    if result.returncode == 1:
        error_message = stderr_text or stdout_text or "Converter.py returned error code 1."
        return False, error_message

    error_message = (
        f"Converter.py returned unexpected exit code {result.returncode}."
        f"\nSTDERR: {stderr_text or 'empty'}"
        f"\nSTDOUT: {stdout_text or 'empty'}"
    )
    return False, error_message


def search_songs(song_search: str, instrument: str) -> list[dict]:
    song_search = song_search.strip()
    if not song_search:
        raise ValueError("Type a song name before searching.")

    query_params = {
        "pattern": song_search,
        "tuning": "undefined",
        "difficulty": "undefined",
        "size": 50,
        "from": 0,
        "more": "true",
    }
    if instrument:
        query_params["inst"] = instrument

    url = f"https://www.songsterr.com/api/search?{urlencode(query_params)}"

    request = Request(url, headers={"Accept": "application/json"})

    try:
        with urlopen(request, timeout=10) as response:
            data = _read_json_response(response)
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Request failed: HTTP {exc.code} {exc.reason}\nURL: {url}\n{details}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Request failed: {exc}\nURL: {url}") from exc

    if isinstance(data, dict):
        records = data.get("records", [])
        return records if isinstance(records, list) else []

    return data if isinstance(data, list) else []


def search_song_meta(song_id: str) -> dict:
    song_id = song_id.strip()
    if not song_id:
        raise ValueError("Song ID not provided.")

    url = f"https://www.songsterr.com/api/meta/{song_id}"

    request = Request(url, headers={"Accept": "application/json"})

    try:
        with urlopen(request, timeout=10) as response:
            data = _read_json_response(response)
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Request failed: HTTP {exc.code} {exc.reason}\nURL: {url}\n{details}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Request failed: {exc}\nURL: {url}") from exc

    if isinstance(data, dict):
        return data

    raise RuntimeError("Unexpected meta response format.")


def get_song_tabs(song_id: str, revision_id: str, image: str, selected_track_id: str) -> dict:
    if not song_id.strip() or not revision_id.strip() or not image.strip() or not selected_track_id.strip():
        raise ValueError("Missing required values for track JSON request.")

    safe_song_id = quote(song_id.strip(), safe="")
    safe_revision_id = quote(revision_id.strip(), safe="")
    safe_image = quote(image.strip(), safe="")
    safe_track_id = quote(selected_track_id.strip(), safe="")

    url = (
        "https://dqsljvtekg760.cloudfront.net/"
        f"{safe_song_id}/{safe_revision_id}/{safe_image}/{safe_track_id}.json"
    )

    request = Request(url, headers={"Accept": "application/json"})

    try:
        with urlopen(request, timeout=10) as response:
            data = _read_json_response(response)
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Track request failed: HTTP {exc.code} {exc.reason}\nURL: {url}\n{details}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Track request failed: {exc}\nURL: {url}") from exc

    if isinstance(data, dict):
        return data

    raise RuntimeError("Unexpected track JSON response format.")


class SongResultsScreen(Screen):
    CSS = """
    Screen {
        align: center middle;
    }

    #results_panel {
        width: 120;
        height: auto;
    }

    #results_row {
        height: 20;
        margin-top: 1;
    }

    #songs_list {
        width: 45;
        height: 100%;
    }

    #details_panel {
        width: 1fr;
        margin-left: 2;
        padding: 0 1;
    }

    #song_details {
        margin-top: 2;
        height: 100%;
    }
    """

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, records: list[dict]) -> None:
        super().__init__()
        self.records = records
        self.meta_cache: dict[str, dict] = {}
        self.meta_lock = Lock()
        self.current_index = 0
        self.current_song_id = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="results_panel"):
            yield Static("Risultati ricerca:")
            with Horizontal(id="results_row"):
                yield ListView(
                    *(
                        ListItem(
                            Label(
                                f"{record.get('title', 'Unknown Title')} — {record.get('artist', 'Unknown Artist')}"
                            )
                        )
                        for record in self.records
                    ),
                    id="songs_list",
                )
                with Vertical(id="details_panel"):
                    yield Static("Dettagli brano:")
                    yield Static("Select a song to view details.", id="song_details")
            yield Button("Back", id="back_button")

    def on_mount(self) -> None:
        songs_list = self.query_one("#songs_list", ListView)
        songs_list.focus()
        self._start_meta_prefetch()
        if self.records:
            songs_list.index = 0
            self._show_selected_song(0)

    def _start_meta_prefetch(self) -> None:
        Thread(target=self._prefetch_meta_worker, daemon=True).start()

    def _prefetch_meta_worker(self) -> None:
        for record in self.records:
            song_id = str(record.get("songId", "")).strip()
            if not song_id:
                continue

            with self.meta_lock:
                if song_id in self.meta_cache:
                    continue

            try:
                meta = search_song_meta(song_id)
            except Exception:
                continue

            with self.meta_lock:
                self.meta_cache[song_id] = meta

            if song_id == self.current_song_id:
                self.app.call_from_thread(self._refresh_current_song_details)

    def _refresh_current_song_details(self) -> None:
        self._show_selected_song(self.current_index)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back_button":
            self.app.pop_screen()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "songs_list":
            return

        selected_index = event.list_view.index if event.list_view.index is not None else 0
        self._show_selected_song(selected_index)
        self._open_track_selection(selected_index)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "songs_list":
            return

        highlighted_index = event.list_view.index if event.list_view.index is not None else 0
        self._show_selected_song(highlighted_index)

    def _show_selected_song(self, index: int) -> None:
        if index < 0 or index >= len(self.records):
            return

        self.current_index = index

        song = self.records[index]
        title = str(song.get("title", "Unknown Title"))
        artist = str(song.get("artist", "Unknown Artist"))
        song_id = str(song.get("songId", ""))
        self.current_song_id = song_id

        if not song_id:
            self.query_one("#song_details", Static).update(
                f"Title: {title}\nArtist: {artist}\n\nNo songId available."
            )
            return

        with self.meta_lock:
            meta = self.meta_cache.get(song_id)

        if meta is None:
            self.query_one("#song_details", Static).update(
                "Song\n"
                f"Title: {title}\n"
                f"Song ID: {song_id}\n\n"
                "People\n"
                f"Artist: {artist}\n"
                "Author: Loading...\n\n"
                "Meta\n"
                "Tags: Loading...\n"
                "Available instruments: Loading..."
            )
            return

        meta_artist = meta.get("artist")
        if isinstance(meta_artist, dict):
            meta_artist_name = meta_artist.get("name") or artist
        elif isinstance(meta_artist, str):
            meta_artist_name = meta_artist
        else:
            meta_artist_name = artist

        meta_author_name = "N/A"
        author_candidates = [
            meta.get("author"),
            meta.get("tabAuthor"),
            meta.get("composer"),
            meta.get("username"),
        ]
        for candidate in author_candidates:
            if isinstance(candidate, dict):
                candidate_name = candidate.get("name") or candidate.get("username")
                if isinstance(candidate_name, str) and candidate_name.strip():
                    meta_author_name = candidate_name.strip()
                    break
            elif isinstance(candidate, str) and candidate.strip():
                meta_author_name = candidate.strip()
                break

        tags_value = meta.get("tags", [])
        if isinstance(tags_value, list):
            parsed_tags: list[str] = []
            for tag in tags_value:
                if isinstance(tag, str):
                    parsed_tags.append(tag)
                elif isinstance(tag, dict):
                    name = tag.get("name")
                    if isinstance(name, str):
                        parsed_tags.append(name)
            tags_text = ", ".join(parsed_tags) if parsed_tags else "N/A"
        else:
            tags_text = "N/A"

        tracks = meta.get("tracks", [])
        instrument_names: list[str] = []
        if isinstance(tracks, list):
            for track in tracks:
                if isinstance(track, dict):
                    instrument_name = track.get("instrument")
                    if isinstance(instrument_name, str) and instrument_name:
                        instrument_names.append(instrument_name)

        unique_instruments = sorted(set(instrument_names))
        instruments_text = ", ".join(unique_instruments) if unique_instruments else "N/A"

        details_text = (
            "Song\n"
            f"Title: {meta.get('title', title)}\n"
            f"Song ID: {song_id}\n\n"
            "People\n"
            f"Artist: {meta_artist_name}\n"
            f"Author: {meta_author_name}\n\n"
            "Meta\n"
            f"Tags: {tags_text}\n"
            f"Available instruments: {instruments_text}"
        )
        self.query_one("#song_details", Static).update(details_text)

    def _open_track_selection(self, index: int) -> None:
        if index < 0 or index >= len(self.records):
            return

        song = self.records[index]
        song_id = str(song.get("songId", "")).strip()
        if not song_id:
            return

        with self.meta_lock:
            meta = self.meta_cache.get(song_id)

        if meta is None:
            try:
                meta = search_song_meta(song_id)
            except Exception as exc:
                self.query_one("#song_details", Static).update(f"Meta request failed:\n{exc}")
                return
            with self.meta_lock:
                self.meta_cache[song_id] = meta

        tracks_value = meta.get("tracks", [])
        tracks = [track for track in tracks_value if isinstance(track, dict)] if isinstance(tracks_value, list) else []
        if not tracks:
            self.query_one("#song_details", Static).update("No tracks available for this song.")
            return

        song_title = str(meta.get("title") or song.get("title") or "Unknown Title")
        self.app.push_screen(
            TrackSelectionScreen(
                song_id=song_id,
                song_title=song_title,
                tracks=tracks,
                meta=meta,
            )
        )


class TrackSelectionScreen(Screen):
    CSS = """
    Screen {
        align: center middle;
    }

    #track_panel {
        width: 110;
        height: auto;
    }

    #tracks_list {
        height: 16;
        margin-top: 1;
    }

    #track_details {
        margin-top: 1;
    }
    """

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, song_id: str, song_title: str, tracks: list[dict], meta: dict) -> None:
        super().__init__()
        self.song_id = song_id
        self.song_title = song_title
        self.tracks = tracks
        self.meta = meta
        self.track_json_cache: dict[str, dict] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="track_panel"):
            yield Static(f"Tracks for: {self.song_title}")
            yield ListView(
                *(
                    ListItem(
                        Label(
                            f"{track.get('name', 'Unnamed Track')} — {track.get('instrument', 'Unknown Instrument')}"
                        )
                    )
                    for track in self.tracks
                ),
                id="tracks_list",
            )
            yield Button("Back", id="track_back_button")
            yield Static("Select a track to view details.", id="track_details")

    def on_mount(self) -> None:
        tracks_list = self.query_one("#tracks_list", ListView)
        tracks_list.focus()
        if self.tracks:
            tracks_list.index = 0
            self._show_track_details(0)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "track_back_button":
            self.app.pop_screen()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "tracks_list":
            return
        track_index = event.list_view.index if event.list_view.index is not None else 0
        self._show_track_details(track_index)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "tracks_list":
            return
        track_index = event.list_view.index if event.list_view.index is not None else 0
        self._show_track_details(track_index)
        self.query_one("#track_details", Static).update("Converting ...")
        self._fetch_selected_track_json(track_index)

    def _show_track_details(self, index: int) -> None:
        if index < 0 or index >= len(self.tracks):
            return

        track = self.tracks[index]
        name = str(track.get("name", "Unnamed Track"))
        instrument = str(track.get("instrument", "Unknown Instrument"))
        difficulty = track.get("difficulty", "N/A")
        views = track.get("views", "N/A")
        track_hash = str(track.get("hash", "N/A"))

        details = (
            "Track\n"
            f"Name: {name}\n"
            f"Instrument: {instrument}\n"
            f"Difficulty: {difficulty}\n"
            f"Views: {views}\n"
            f"Hash: {track_hash}"
        )
        self.query_one("#track_details", Static).update(details)

    def _fetch_selected_track_json(self, index: int) -> None:
        if index < 0 or index >= len(self.tracks):
            return

        track = self.tracks[index]
        selected_track_id = str(index)

        revision_id = str(
            self.meta.get("revisionId")
            or self.meta.get("revision")
            or track.get("revisionId")
            or track.get("revision")
            or ""
        ).strip()

        image = str(
            self.meta.get("image")
            or self.meta.get("imageId")
            or track.get("image")
            or track.get("imageId")
            or ""
        ).strip()

        if not revision_id or not image or not selected_track_id:
            self.query_one("#track_details", Static).update(
                "Track\n"
                "Unable to build track JSON URL.\n"
                f"revision_id={revision_id or 'missing'}\n"
                f"image={image or 'missing'}\n"
                f"selected_track_id={selected_track_id or 'missing'}"
            )
            return

        cache_key = f"{self.song_id}:{revision_id}:{image}:{selected_track_id}"
        if cache_key in self.track_json_cache:
            track_json = self.track_json_cache[cache_key]
        else:
            try:
                track_json = get_song_tabs(self.song_id, revision_id, image, selected_track_id)
            except Exception as exc:
                self.query_one("#track_details", Static).update(f"Track JSON request failed:\n{exc}")
                return
            self.track_json_cache[cache_key] = track_json

        if isinstance(track_json, dict):
            enriched_track_json = dict(track_json)

            song_title = str(self.meta.get("title") or self.song_title or "").strip()
            if song_title:
                enriched_track_json["songName"] = song_title
                enriched_track_json["songTitle"] = song_title
                enriched_track_json["title"] = song_title

            artist_name = ""
            meta_artist = self.meta.get("artist")
            if isinstance(meta_artist, dict):
                artist_name = str(meta_artist.get("name") or "").strip()
            elif isinstance(meta_artist, str):
                artist_name = meta_artist.strip()

            if artist_name:
                enriched_track_json["artist"] = artist_name

            author_name = ""
            for candidate in (
                self.meta.get("author"),
                self.meta.get("tabAuthor"),
                self.meta.get("composer"),
                self.meta.get("username"),
            ):
                if isinstance(candidate, dict):
                    candidate_name = candidate.get("name") or candidate.get("username")
                    if isinstance(candidate_name, str) and candidate_name.strip():
                        author_name = candidate_name.strip()
                        break
                elif isinstance(candidate, str) and candidate.strip():
                    author_name = candidate.strip()
                    break

            if author_name:
                enriched_track_json["author"] = author_name

            editor_name = str(
                self.meta.get("editor")
                or self.meta.get("editedBy")
                or self.meta.get("editorName")
                or self.meta.get("revisionAuthor")
                or self.meta.get("username")
                or ""
            ).strip()
            if editor_name:
                enriched_track_json["editor"] = editor_name

            track_json = enriched_track_json

        self.query_one("#track_details", Static).update(
            "Track JSON\n"
            f"song_id={self.song_id}\n"
            f"revision_id={revision_id}\n"
            f"image={image}\n"
            f"selected_track_id={selected_track_id}\n\n"
            "Converting ..."
        )

        success, message = send_json_to_score(track_json)
        status_line = "Conversion status: success" if success else "Conversion status: error"
        self.query_one("#track_details", Static).update(
            "Track\n"
            f"song_id={self.song_id}\n"
            f"revision_id={revision_id}\n"
            f"image={image}\n"
            f"selected_track_id={selected_track_id}\n\n"
            f"{status_line}\n"
            f"{message}"
        )


class SongsterrToScoreApp(App):
    CSS = """
    Screen {
        align: center middle;
    }

    #panel {
        width: 70;
        height: auto;
    }

    #song_input {
        background: #4444ee;
        margin: 1;
    }

    #instrument_list {
        height: 8;
        margin: 1;
    }

    #result {
        margin-top: 1;
    }
    """

    BINDINGS = [
        ("up", "instrument_up", "Instrument Up"),
        ("down", "instrument_down", "Instrument Down"),
        ("enter", "run_search", "Search"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.instrument_options = [
            ("Guitar", "guitar"),
            ("Bass", "bass"),
            ("Drums", "drums"),
            ("Any", ""),
        ]

    def compose(self) -> ComposeResult:
        with Vertical(id="panel"):
            yield Static("Cerca Canzone:")
            yield Input(placeholder="Type song name...", id="song_input")
            yield Static("Seleziona Strumento:")
            yield ListView(
                *(ListItem(Label(name)) for name, _ in self.instrument_options),
                id="instrument_list",
            )
            yield Button("Search", id="search_button")
            yield Static("", id="result")

    def on_mount(self) -> None:
        self.query_one("#song_input", Input).focus()
        self.query_one("#instrument_list", ListView).index = 0

    def action_instrument_up(self) -> None:
        instrument_list = self.query_one("#instrument_list", ListView)
        current_index = instrument_list.index if instrument_list.index is not None else 0
        instrument_list.index = max(0, current_index - 1)

    def action_instrument_down(self) -> None:
        instrument_list = self.query_one("#instrument_list", ListView)
        current_index = instrument_list.index if instrument_list.index is not None else 0
        instrument_list.index = min(len(self.instrument_options) - 1, current_index + 1)

    def action_run_search(self) -> None:
        self._run_search()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "song_input":
            self._run_search()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "search_button":
            self._run_search()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "instrument_list":
            self._run_search()

    def _run_search(self) -> None:
        song_search = self.query_one("#song_input", Input).value.strip()
        instrument_list = self.query_one("#instrument_list", ListView)
        selected_index = instrument_list.index if instrument_list.index is not None else 0
        instrument = self.instrument_options[selected_index][1]
        try:
            records = search_songs(song_search, instrument)
        except Exception as exc:
            self.query_one("#result", Static).update(str(exc))
            return

        if not records:
            self.query_one("#result", Static).update("No songs found.")
            return

        self.query_one("#result", Static).update(f"Found {len(records)} songs")
        self.push_screen(SongResultsScreen(records))


def run() -> None:
    SongsterrToScoreApp().run()


def main() -> None:
    run()


if __name__ == "__main__":
    main()
