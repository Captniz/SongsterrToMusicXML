import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from musicscore import Chord, Score
from musicxml.xmlelement.xmlelement import (
    XMLFret,
    XMLGlissando,
    XMLHammerOn,
    XMLPullOff,
    XMLSlide,
    XMLSlur,
    XMLStaccato,
    XMLString,
)


def _load_converter_config(config_path: Path) -> dict:
    default_config = {
        "save_path": str(Path.home() / "Documents"),
        "default_top_string_midi": None,
        "default_interval_semitones": 5,
    }

    if not config_path.exists():
        return default_config

    try:
        raw = config_path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except Exception:
        return default_config

    if not isinstance(parsed, dict):
        return default_config

    merged = dict(default_config)
    merged.update(parsed)
    return merged


def _resolve_output_directory(script_dir: Path, config: dict | None = None) -> Path:
    if config is None:
        config_path = script_dir / "converter.config"
        config = _load_converter_config(config_path)

    raw_save_path = config.get("save_path")
    if not isinstance(raw_save_path, str) or not raw_save_path.strip():
        raw_save_path = str(Path.home() / "Documents")

    output_dir = _resolve_configured_path(raw_save_path.strip())
    if not output_dir.is_absolute():
        output_dir = script_dir / output_dir

    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _resolve_configured_path(raw_path: str) -> Path:
    cleaned = raw_path.strip().strip('"').strip("'")
    cleaned = re.sub(r"^~\s*[\\/]", "~/", cleaned)
    cleaned = cleaned.replace("~\\", "~/")

    if cleaned == "~":
        return Path.home()

    if cleaned.startswith("~/"):
        return Path.home() / cleaned[2:]

    return Path(cleaned)


def _patch_musicscore_rest_comparison() -> None:
    original_has_same_pitches = Chord.has_same_pitches

    def safe_has_same_pitches(self: Chord, other: Chord) -> bool:
        if getattr(self, "is_rest", False) or getattr(other, "is_rest", False):
            return False
        return original_has_same_pitches(self, other)

    Chord.has_same_pitches = safe_has_same_pitches


def _safe_filename(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value.strip())
    return cleaned or "track"


def _first_non_empty_string(payload: dict, keys: list[str], default: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def _resolve_song_name(payload: dict) -> str:
    return _first_non_empty_string(
        payload,
        ["songName", "songTitle", "title", "song", "name"],
        "track",
    )


def _get_quarter_duration(beat: dict) -> float:
    duration = beat.get("duration", [1, 4])
    if not isinstance(duration, list) or len(duration) != 2:
        return 1.0

    numerator, denominator = duration
    if not isinstance(numerator, (int, float)) or not isinstance(denominator, (int, float)) or denominator == 0:
        return 1.0

    return (4.0 * float(numerator)) / float(denominator)


def _beat_to_chord(beat: dict, tuning: list[int]) -> tuple[Chord, list[tuple[int, int, bool]]]:
    quarter_duration = _get_quarter_duration(beat)

    if beat.get("rest"):
        return Chord(0, quarter_duration), []

    notes = beat.get("notes", [])
    if not isinstance(notes, list) or not notes:
        return Chord(0, quarter_duration), []

    midi_entries: list[tuple[int, int, int, bool]] = []
    for note in notes:
        if not isinstance(note, dict) or note.get("rest"):
            continue

        string_index = note.get("string")
        fret = note.get("fret")
        if not isinstance(string_index, int) or not isinstance(fret, int):
            continue
        if string_index < 0 or string_index >= len(tuning):
            continue

        midi_value = int(tuning[string_index]) + fret
        is_dead = bool(note.get("dead", False))
        midi_entries.append((midi_value, string_index, fret, is_dead))

    if not midi_entries:
        return Chord(0, quarter_duration), []

    midi_entries.sort(key=lambda item: item[0])
    midis = [midi_value for midi_value, _, _, _ in midi_entries]

    if len(midis) == 1:
        chord = Chord(midis[0], quarter_duration)
    else:
        chord = Chord(midis, quarter_duration)

    note_positions: list[tuple[int, int, bool]] = []
    for midi_obj, (_, string_index, fret, is_dead) in zip(chord.midis, midi_entries):
        if is_dead:
            midi_obj.notehead = "x"
        note_positions.append((string_index, fret, is_dead))

    return chord, note_positions


def _apply_tab_technical(chord: Chord, note_positions: list[tuple[int, int, bool]]) -> None:
    if not _is_non_rest_chord(chord) or not note_positions:
        return

    string_index, fret, is_dead = note_positions[0]
    xml_string_number = string_index + 1

    chord.add_x(XMLString(xml_string_number))

    if is_dead:
        chord.add_x(XMLFret(0))
    else:
        chord.add_x(XMLFret(fret))


def _resolve_dead_note_mode(payload: dict) -> str:
    raw_mode = payload.get("deadNoteMode")
    if isinstance(raw_mode, str):
        normalized = raw_mode.strip().lower()
        if normalized in {"standard", "unpitched"}:
            return normalized

    raw_bool = payload.get("deadNotesAsUnpitched")
    if isinstance(raw_bool, bool):
        return "unpitched" if raw_bool else "standard"

    return "standard"


def _convert_dead_notes_to_unpitched_musicxml(output_path: Path) -> None:
    tree = ET.parse(output_path)
    root = tree.getroot()

    for note in root.iter("note"):
        notehead = note.find("notehead")
        if notehead is None or (notehead.text or "").strip().lower() != "x":
            continue

        pitch = note.find("pitch")
        if pitch is None:
            continue

        note.remove(pitch)

        unpitched = ET.Element("unpitched")
        display_step = ET.SubElement(unpitched, "display-step")
        display_step.text = "C"
        display_octave = ET.SubElement(unpitched, "display-octave")
        display_octave.text = "4"

        insertion_index = 0
        for index, child in enumerate(list(note)):
            if child.tag in {"instrument", "voice", "type", "dot", "time-modification", "stem", "notehead", "staff", "beam", "notations", "lyric"}:
                insertion_index = index
                break
            insertion_index = index + 1

        note.insert(insertion_index, unpitched)

    tree.write(output_path, encoding="UTF-8", xml_declaration=True)


def _pitch_to_midi(pitch_element: ET.Element) -> int | None:
    step_text = (pitch_element.findtext("step") or "").strip().upper()
    octave_text = (pitch_element.findtext("octave") or "").strip()
    alter_text = (pitch_element.findtext("alter") or "0").strip()

    semitones = {
        "C": 0,
        "D": 2,
        "E": 4,
        "F": 5,
        "G": 7,
        "A": 9,
        "B": 11,
    }

    if step_text not in semitones:
        return None

    try:
        octave = int(octave_text)
        alter = int(float(alter_text))
    except Exception:
        return None

    return (octave + 1) * 12 + semitones[step_text] + alter


def _infer_string_and_fret_from_midi(midi_value: int, tuning: list[int]) -> tuple[int, int] | None:
    candidates: list[tuple[int, int]] = []
    for string_index, open_string_midi in enumerate(tuning):
        fret = midi_value - int(open_string_midi)
        if fret >= 0:
            candidates.append((string_index, fret))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[1], item[0]))
    return candidates[0]


def _ensure_note_has_technical_string_fret(note: ET.Element, tuning: list[int]) -> None:
    if note.find("rest") is not None:
        return

    notehead_text = (note.findtext("notehead") or "").strip().lower()
    is_dead = notehead_text == "x"

    notations = note.find("notations")
    if notations is None:
        notations = ET.SubElement(note, "notations")

    technical = notations.find("technical")
    if technical is None:
        technical = ET.SubElement(notations, "technical")

    existing_string = technical.find("string")
    existing_fret = technical.find("fret")

    if existing_string is not None and existing_fret is not None:
        return

    inferred_string_number: int | None = None
    inferred_fret: int | None = None

    pitch = note.find("pitch")
    if pitch is not None and tuning:
        midi_value = _pitch_to_midi(pitch)
        if midi_value is not None:
            inferred = _infer_string_and_fret_from_midi(midi_value, tuning)
            if inferred is not None:
                inferred_string_number = inferred[0] + 1
                inferred_fret = inferred[1]

    if inferred_string_number is None:
        inferred_string_number = 1

    if inferred_fret is None:
        inferred_fret = 0

    if existing_string is None:
        existing_string = ET.SubElement(technical, "string")
    existing_string.text = str(inferred_string_number)

    if existing_fret is None:
        existing_fret = ET.SubElement(technical, "fret")

    if is_dead:
        existing_fret.text = "0"
    else:
        existing_fret.text = str(inferred_fret)


def _ensure_string_fret_for_all_notes_musicxml(output_path: Path, tuning: list[int]) -> None:
    tree = ET.parse(output_path)
    root = tree.getroot()

    for note in root.iter("note"):
        _ensure_note_has_technical_string_fret(note, tuning)

    tree.write(output_path, encoding="UTF-8", xml_declaration=True)


def _iter_note_dicts(measures: list[dict]) -> list[dict]:
    notes: list[dict] = []

    for measure in measures:
        if not isinstance(measure, dict):
            continue

        voices = measure.get("voices", [])
        if not isinstance(voices, list):
            continue

        for voice in voices:
            if not isinstance(voice, dict):
                continue

            beats = voice.get("beats", [])
            if not isinstance(beats, list):
                continue

            for beat in beats:
                if not isinstance(beat, dict):
                    continue

                beat_notes = beat.get("notes", [])
                if not isinstance(beat_notes, list):
                    continue

                for note in beat_notes:
                    if isinstance(note, dict):
                        notes.append(note)

    return notes


def _normalize_tuning(raw_tuning: object) -> list[int]:
    if isinstance(raw_tuning, dict):
        values: list[tuple[int, int]] = []
        for key, value in raw_tuning.items():
            try:
                index = int(str(key))
            except Exception:
                continue

            if isinstance(value, (int, float)):
                values.append((index, int(value)))
            elif isinstance(value, dict):
                for field_name in ("value", "note", "pitch", "midi"):
                    field_value = value.get(field_name)
                    if isinstance(field_value, (int, float)):
                        values.append((index, int(field_value)))
                        break

        if values:
            values.sort(key=lambda entry: entry[0])
            return [value for _, value in values]
        return []

    if not isinstance(raw_tuning, list):
        return []

    normalized: list[int] = []
    for item in raw_tuning:
        if isinstance(item, (int, float)):
            normalized.append(int(item))
        elif isinstance(item, dict):
            parsed_value: int | None = None
            for field_name in ("value", "note", "pitch", "midi"):
                field_value = item.get(field_name)
                if isinstance(field_value, (int, float)):
                    parsed_value = int(field_value)
                    break
            if parsed_value is not None:
                normalized.append(parsed_value)

    return normalized


def _guess_string_count(payload: dict, measures: list[dict]) -> int:
    payload_strings = payload.get("strings")
    if isinstance(payload_strings, int) and payload_strings > 0:
        return payload_strings

    max_string_index = -1
    for note in _iter_note_dicts(measures):
        if note.get("rest"):
            continue
        string_index = note.get("string")
        if isinstance(string_index, int) and string_index > max_string_index:
            max_string_index = string_index

    return max_string_index + 1 if max_string_index >= 0 else 0


def _resolve_fallback_tuning_parameters(config: dict | None, string_count: int) -> tuple[int, int]:
    interval = 5
    if isinstance(config, dict):
        raw_interval = config.get("default_interval_semitones")
        if isinstance(raw_interval, (int, float)) and int(raw_interval) > 0:
            interval = int(raw_interval)

    top_string_midi: int | None = None
    if isinstance(config, dict):
        raw_top = config.get("default_top_string_midi")
        if isinstance(raw_top, (int, float)):
            parsed_top = int(raw_top)
            if parsed_top > 0:
                top_string_midi = parsed_top

    if top_string_midi is None:
        top_string_midi = 43 if string_count <= 4 else 64

    return top_string_midi, interval


def _default_tuning_for_track(payload: dict, measures: list[dict], config: dict | None = None) -> list[int]:
    string_count = _guess_string_count(payload, measures)
    if string_count <= 0:
        return []

    highest_open_string, interval = _resolve_fallback_tuning_parameters(config, string_count)
    return [highest_open_string - (interval * index) for index in range(string_count)]


def _resolve_tuning(payload: dict, measures: list[dict], config: dict | None = None) -> list[int]:
    normalized = _normalize_tuning(payload.get("tuning"))
    if normalized:
        return normalized

    return _default_tuning_for_track(payload, measures, config=config)


def _extract_beat_effects(beat: dict) -> dict[str, bool | str | None]:
    notes = beat.get("notes", [])
    if not isinstance(notes, list):
        return {"staccato": False, "hp": False, "slide": None}

    has_staccato = False
    has_hammer_pull = False
    slide_type: str | None = None

    for note in notes:
        if not isinstance(note, dict) or note.get("rest"):
            continue

        if bool(note.get("staccato")):
            has_staccato = True
        if bool(note.get("hp")):
            has_hammer_pull = True

        raw_slide = note.get("slide")
        if isinstance(raw_slide, str) and raw_slide.strip() and slide_type is None:
            slide_type = raw_slide.strip().lower()

    return {"staccato": has_staccato, "hp": has_hammer_pull, "slide": slide_type}


def _is_non_rest_chord(chord: Chord | None) -> bool:
    return bool(chord is not None and not getattr(chord, "is_rest", False))


def _lowest_chord_midi(chord: Chord) -> int | None:
    midi_values: list[int] = []
    for midi in getattr(chord, "midis", []):
        value = getattr(midi, "value", None)
        if isinstance(value, int):
            midi_values.append(value)

    return min(midi_values) if midi_values else None


def _apply_hp_slur(previous_chord: Chord, current_chord: Chord) -> None:
    previous_chord.add_x(XMLSlur(type="start", number=1))
    current_chord.add_x(XMLSlur(type="stop", number=1))

    previous_pitch = _lowest_chord_midi(previous_chord)
    current_pitch = _lowest_chord_midi(current_chord)
    if previous_pitch is None or current_pitch is None:
        return

    if current_pitch >= previous_pitch:
        previous_chord.add_x(XMLHammerOn(type="start", number=1))
        current_chord.add_x(XMLHammerOn(type="stop", number=1))
    else:
        previous_chord.add_x(XMLPullOff(type="start", number=1))
        current_chord.add_x(XMLPullOff(type="stop", number=1))


def _apply_slide_connection(start_chord: Chord, stop_chord: Chord, slide_type: str | None) -> None:
    start_chord.add_x(XMLGlissando(type="start", number=1))
    stop_chord.add_x(XMLGlissando(type="stop", number=1))
    start_chord.add_x(XMLSlide(type="start", number=1))
    stop_chord.add_x(XMLSlide(type="stop", number=1))

    if slide_type == "legato":
        start_chord.add_x(XMLSlur(type="start", number=1))
        stop_chord.add_x(XMLSlur(type="stop", number=1))


def convert_track_json_to_musicxml(payload: dict, output_dir: Path, config: dict | None = None) -> Path:
    measures = payload.get("measures", [])

    if isinstance(measures, dict):
        normalized_measures: list[dict] = []
        for key, value in measures.items():
            if not isinstance(value, dict):
                continue
            measure_data = dict(value)
            if "index" not in measure_data:
                try:
                    measure_data["index"] = int(str(key))
                except Exception:
                    pass
            normalized_measures.append(measure_data)
        measures = normalized_measures

    if not isinstance(measures, list) or not measures:
        raise ValueError("Track JSON missing valid 'measures'.")

    tuning = _resolve_tuning(payload, measures, config=config)
    dead_note_mode = _resolve_dead_note_mode(payload)

    song_name = _resolve_song_name(payload)
    track_name = str(payload.get("name") or "track")
    song_id = str(payload.get("songId") or "unknown")
    revision_id = str(payload.get("revisionId") or "unknown")

    score = Score(title=song_name)
    part = score.add_part("P1")
    part.name = str(payload.get("instrument") or track_name)

    sorted_measures = sorted(
        [measure for measure in measures if isinstance(measure, dict)],
        key=lambda measure: int(measure.get("index", 0)),
    )

    previous_signature: tuple[int, int] | None = None
    for measure_data in sorted_measures:
        signature = measure_data.get("signature")
        current_signature: tuple[int, int] | None = None
        if (
            isinstance(signature, list)
            and len(signature) == 2
            and isinstance(signature[0], int)
            and isinstance(signature[1], int)
            and signature[0] > 0
            and signature[1] > 0
        ):
            current_signature = (signature[0], signature[1])

        if not part.get_children():
            measure = part.add_measure(time=current_signature or (4, 4))
        elif current_signature and current_signature != previous_signature:
            measure = part.add_measure(time=current_signature)
        else:
            measure = part.add_measure()

        part.set_current_measure(1, 1, measure)

        voices = measure_data.get("voices", [])
        if not isinstance(voices, list) or not voices:
            part.add_chord(Chord(0, 4))
            previous_signature = current_signature or previous_signature
            continue

        primary_voice = voices[0] if isinstance(voices[0], dict) else {}
        beats = primary_voice.get("beats", [])
        if not isinstance(beats, list) or not beats:
            part.add_chord(Chord(0, 4))
            previous_signature = current_signature or previous_signature
            continue

        pending_hp_start: Chord | None = None
        pending_slide_start: Chord | None = None
        pending_slide_type: str | None = None

        for beat in beats:
            if not isinstance(beat, dict):
                continue

            chord, note_positions = _beat_to_chord(beat, tuning)
            effects = _extract_beat_effects(beat)

            _apply_tab_technical(chord, note_positions)

            if _is_non_rest_chord(chord) and bool(effects["staccato"]):
                chord.add_x(XMLStaccato())

            if _is_non_rest_chord(pending_hp_start) and _is_non_rest_chord(chord):
                _apply_hp_slur(pending_hp_start, chord)
                pending_hp_start = None

            if _is_non_rest_chord(pending_slide_start) and _is_non_rest_chord(chord):
                _apply_slide_connection(pending_slide_start, chord, pending_slide_type)
                pending_slide_start = None
                pending_slide_type = None

            if _is_non_rest_chord(chord) and bool(effects["hp"]):
                pending_hp_start = chord

            if _is_non_rest_chord(chord) and isinstance(effects["slide"], str):
                pending_slide_start = chord
                pending_slide_type = str(effects["slide"])
            elif getattr(chord, "is_rest", False):
                pending_hp_start = None
                pending_slide_start = None
                pending_slide_type = None

            part.add_chord(chord)

        previous_signature = current_signature or previous_signature

    author_name = _first_non_empty_string(
        payload,
        ["author", "artist", "composer", "songAuthor", "artistName"],
        "unknown-author",
    )
    editor_name = _first_non_empty_string(
        payload,
        ["editor", "editedBy", "editorName", "username", "revisionAuthor"],
        str(revision_id),
    )

    output_name = _safe_filename(f"{song_name}-{author_name}-{editor_name}") + ".musicxml"
    output_path = output_dir / output_name
    score.export_xml(output_path)

    _ensure_string_fret_for_all_notes_musicxml(output_path, tuning)

    if dead_note_mode == "unpitched":
        _convert_dead_notes_to_unpitched_musicxml(output_path)

    return output_path


def main() -> int:
    try:
        _patch_musicscore_rest_comparison()
        script_dir = Path(__file__).resolve().parent
        config = _load_converter_config(script_dir / "converter.config")

        raw_input = sys.stdin.read()
        if not raw_input.strip():
            print("No JSON payload received.", file=sys.stderr)
            return 1

        payload = json.loads(raw_input)
        if not isinstance(payload, dict):
            print("Payload must be a JSON object.", file=sys.stderr)
            return 1

        output_path = convert_track_json_to_musicxml(
            payload,
            _resolve_output_directory(script_dir, config=config),
            config=config,
        )
        print(f"MusicXML written to: {output_path}")

        return 0
    except Exception as exc:
        print(f"Converter.py error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
