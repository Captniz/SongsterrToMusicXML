<h1 align="center">SongsterrToMusicXML</h1>

Convert Songsterr track JSON to MusicXML through a terminal UI (Textual) or directly from stdin.

## Quick Start Guide

A full guide is below with copy/paste commands.


1. Download the `.zip` from GitHub [Releases](https://github.com/Captniz/SongsterrToMusicXML/releases)
2. Unzip and enter the folder
3. (*Optional*) Edit `converter.config` to choose output folder and fallback tuning behavior.
4. Run the launcher script (it creates/uses `.venv`, installs deps from `requirements.lock`, and starts the app)

```bash
  # Linux or macOS:
  ./run
```

```bash
  # Windows:
  run.bat
```

5. In the app, follow prompts to search for a song, select an instrument, and choose a track (*instrument*).
6. After selecting the track, wait for final conversion status (**The program hanging for a while is an intended behaviour. Do not close.**).
7. Open generated `.musicxml` from the configured output folder.
8. **IF USING MUSESCORE, SEE THE IMPORTANT NOTE [HERE](#importing-to-musescore-messes-up-the-notation) !!!!!!**

## Table of Contents

- [SongsterrToMusicXML](#songsterrtomusicxml)
  - [Quick Start Guide](#quick-start-guide)
  - [Table of Contents](#table-of-contents)
  - [What this project does](#what-this-project-does)
  - [Project structure](#project-structure)
  - [Requirements](#requirements)
  - [Configuration (`converter.config`)](#configuration-converterconfig)
    - [Supported options](#supported-options)
    - [Fallback tuning behavior](#fallback-tuning-behavior)
  - [Run the graphical app (TUI)](#run-the-graphical-app-tui)
  - [Run converter directly (without UI)](#run-converter-directly-without-ui)
  - [Output naming](#output-naming)
  - [Notes on notation support](#notes-on-notation-support)
  - [Troubleshooting](#troubleshooting)
    - [`Importing to Musescore messes up the notation`](#importing-to-musescore-messes-up-the-notation)
    - [`Track JSON missing valid 'measures'`](#track-json-missing-valid-measures)
    - [`~ path created as literal folder`](#-path-created-as-literal-folder)

## What this project does

- Search songs on Songsterr
- Select a track/instrument revision
- Download track JSON
- Convert to MusicXML via `Converter.py`
- Save output to a configurable folder (`converter.config`)

## Project structure

- `main.py` — app entry point
- `ui_app.py` — Textual UI + Songsterr API calls
- `Converter.py` — JSON -> MusicXML converter
- `converter.config` — converter options (for example save path)

## Requirements

- Python 3.11+ (3.13 works)
- Internet connection (Songsterr API is queried at runtime)

Python packages used:

- `textual`
- `musicscore`

Install (inside your venv) using the lock file:

```bash
# from project root
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
```

## Configuration (`converter.config`)

`Converter.py` loads `converter.config` from the project folder.

Example:

```json
{
  "save_path": "~/Downloads",
  "default_top_string_midi": null,
  "default_interval_semitones": 5
}
```

### Supported options

- `save_path` (string): destination folder for exported `.musicxml` files
  - Absolute path: used directly
  - Relative path: resolved relative to project folder
  - `~` is supported (home directory), including common variants like quoted values or `~\...`
- `default_top_string_midi` (number or `null`): top open-string MIDI for fallback tuning when input JSON has no `tuning`
  - If `null`, converter auto-selects based on string count
- `default_interval_semitones` (number): interval used between adjacent strings in fallback tuning
  - Must be a positive value; defaults to `5` if invalid

If config is missing/invalid, fallback default is your Documents folder.

### Fallback tuning behavior

When Songsterr JSON includes `tuning`, that value is always used.

When `tuning` is missing, converter generates fallback tuning using:

- detected `string_count`
- `default_top_string_midi` from config (or auto top string if `null`)
- `default_interval_semitones` from config

Formula:

- `tuning[i] = top_string_midi - interval * i`

This is instrument-agnostic and works for any fretted/string payload shape, not only guitar/bass names.

## Run the graphical app (TUI)

```bash
python main.py
```

Flow:

1. Type a song name
2. Choose instrument filter
3. Select song
4. Select track
5. App shows the final conversion status

## Run converter directly (without UI)

`Converter.py` reads one JSON payload from stdin.

```bash
python Converter.py < track.json
```

On success it prints the generated file path:

- `MusicXML written to: /path/to/file.musicxml`

## Output naming

Output filename format is:

- `{Song name}-{author}-{editor}.musicxml`

Song name is resolved from payload fields in this priority:

- `songName`, `songTitle`, `title`, `song`, `name`

## Notes on notation support

Converter includes support for common bass/guitar features found in Songsterr JSON, including:

- Staccato
- Hammer-on / Pull-off (with slur pairing)
- Slide / Glissando
- Dead notes (`x` notehead)
- String/Fret technical notation in MusicXML

Additional converter options supported in JSON payload:

- `deadNoteMode`: `"standard"` or `"unpitched"`
- `deadNotesAsUnpitched`: boolean shortcut for dead note rendering mode

## Troubleshooting

### `Importing to Musescore messes up the notation`

MuseScore's MusicXML import can be inconsistent across versions (*or just plainly suck*), especially for guitar-specific notation.

If your converted file looks different than expected in MuseScore, do the following (MuseScore 4.1+ recommended):
1. Go to `Layout` → Gear button on the instrument → `Replace Instrument` → Put the actual instrument you intend to use (for example, `Electric Bass` instead of `Slap Bass 2`) → Click `OK`.
   - *With this method you can also **convert to tabs** instead of standard notation*.
2. After changing the instrument click the arrow to open the staff subsection → Gear button on the tablature staff → Change `Staff type` from `Simple` or `Common` to `Full`.
3. If you are using tabs containing dead notes (ghost notes with `x` notehead), **Save the file and restart musescore**. This forces MuseScore to re-interpret the MusicXML and apply the correct notehead for dead notes.

### `Track JSON missing valid 'measures'`

Input payload is not a valid Songsterr track JSON.

### `~ path created as literal folder`

Use a valid JSON string in `converter.config`, for example:
  
- `"~/Documents"`

Avoid extra characters around `~`.
