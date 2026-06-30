#!/usr/bin/env python3
"""
pitch_app.py

Browser GUI (via Streamlit) to batch-pitch music files with FFmpeg —
speed + pitch, like "Change Speed" in Audacity.

You can:
  - pitch a whole folder
  - OR pitch only selected files
  - choose an output folder
  - convert to another format / quality (MP3 320, WAV, FLAC...)
  - create / save / load configuration PROFILES (JSON database)
  - switch the interface language (en.json by default, fr.json)

Run:
    pip install streamlit
    streamlit run pitch_app.py

Requires ffmpeg AND ffprobe installed and available in PATH.
  -> Windows : winget install ffmpeg   (or https://ffmpeg.org/download.html)
  -> Mac     : brew install ffmpeg
  -> Linux   : sudo apt install ffmpeg
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import streamlit as st

HERE = Path(__file__).parent

# Audio extensions accepted as input
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".aiff", ".aif", ".m4a", ".ogg", ".wma", ".opus"}

# Persistence files
PROFILES_PATH = HERE / "profiles.json"
DRAFT_PATH = HERE / ".pitch_draft.json"

# Available languages (code -> <code>.json file). "en" = default/fallback.
LANGUAGES = ["en", "fr"]
DEFAULT_LANG = "en"

# ---------------------------------------------------------------------------
# Output format / quality presets, identified by a STABLE id
# (language-independent). id -> (output extension, FFmpeg codec args).
# The displayed label comes from the translation files ("presets").
# "keep" = keep the original format (ext = None).
# ---------------------------------------------------------------------------
OUTPUT_PRESETS = {
    "keep":     (None, None),
    "mp3_320":  (".mp3", ["-codec:a", "libmp3lame", "-b:a", "320k"]),
    "mp3_256":  (".mp3", ["-codec:a", "libmp3lame", "-b:a", "256k"]),
    "mp3_192":  (".mp3", ["-codec:a", "libmp3lame", "-b:a", "192k"]),
    "mp3_128":  (".mp3", ["-codec:a", "libmp3lame", "-b:a", "128k"]),
    "mp3_v0":   (".mp3", ["-codec:a", "libmp3lame", "-q:a", "0"]),
    "mp3_v2":   (".mp3", ["-codec:a", "libmp3lame", "-q:a", "2"]),
    "flac":     (".flac", ["-codec:a", "flac", "-compression_level", "8"]),
    "wav16":    (".wav", ["-codec:a", "pcm_s16le"]),
    "wav24":    (".wav", ["-codec:a", "pcm_s24le"]),
    "aac_256":  (".m4a", ["-codec:a", "aac", "-b:a", "256k"]),
    "aac_192":  (".m4a", ["-codec:a", "aac", "-b:a", "192k"]),
    "ogg_q5":   (".ogg", ["-codec:a", "libvorbis", "-q:a", "5"]),
    "opus_128": (".opus", ["-codec:a", "libopus", "-b:a", "128k"]),
}

# "Max quality" settings used when keeping the original format
KEEP_FORMAT_CODECS = {
    ".mp3":  ["-codec:a", "libmp3lame", "-q:a", "0"],
    ".flac": ["-codec:a", "flac", "-compression_level", "8"],
    ".wav":  ["-codec:a", "pcm_s16le"],
    ".aiff": ["-codec:a", "pcm_s16be"],
    ".aif":  ["-codec:a", "pcm_s16be"],
    ".m4a":  ["-codec:a", "aac", "-b:a", "256k"],
    ".ogg":  ["-codec:a", "libvorbis", "-q:a", "6"],
    ".opus": ["-codec:a", "libopus", "-b:a", "160k"],
    ".wma":  ["-codec:a", "wmav2", "-b:a", "192k"],
}

# Config stored in a profile (internal, language-independent values).
# Individual files are deliberately NOT stored.
DEFAULTS = {
    "mode": "folder",            # "folder" | "files"
    "input_dir": "",
    "output_dir": "",
    "pitch_percent": 2.0,
    "preset_label": next(iter(OUTPUT_PRESETS)),  # "keep"
}

# Maps a config field -> its associated Streamlit widget key.
# We keep the (persistent) `cfg` dict separate from the widgets, because
# Streamlit drops the key of a widget that is not rendered (e.g. input_dir
# in "files" mode).
WIDGET_KEYS = {
    "mode": "w_mode",
    "input_dir": "w_input_dir",
    "output_dir": "w_output_dir",
    "pitch_percent": "w_pitch",
    "preset_label": "w_preset",
}


# ---------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------
def load_locale(lang: str) -> dict:
    try:
        return json.loads((HERE / f"{lang}.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_translations(lang: str) -> dict:
    """Load the requested language, falling back to English for missing keys."""
    base = load_locale(DEFAULT_LANG)
    if lang != DEFAULT_LANG:
        override = load_locale(lang)
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                base[k] = {**base[k], **v}  # deep merge (e.g. "presets")
            else:
                base[k] = v
    return base


# ---------------------------------------------------------------------------
# FFmpeg helpers
# ---------------------------------------------------------------------------
def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def get_sample_rate(filepath: Path) -> int:
    """Get the file's sample rate via ffprobe (44100 by default)."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=sample_rate",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(filepath),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return int(result.stdout.strip())
    except (ValueError, subprocess.SubprocessError):
        return 44100


def pitch_file(input_path: Path, output_path: Path, rate: float, codec_args):
    """Pitch a file (speed + pitch) and encode it according to codec_args."""
    sample_rate = get_sample_rate(input_path)
    new_rate = int(sample_rate * rate)

    # asetrate  -> replay the file at a different sample rate (changes speed + pitch)
    # aresample -> go back to the standard sample rate for player compatibility
    filter_chain = f"asetrate={new_rate},aresample={sample_rate}"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-filter:a", filter_chain,
        "-vn",
        *codec_args,
        str(output_path),
    ]

    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        last = proc.stderr.strip().splitlines()[-1] if proc.stderr else "ffmpeg error"
        raise RuntimeError(last)


def resolve_codec(preset_id: str, source_suffix: str):
    """Return (output_extension, codec_args) for a given file."""
    out_ext, codec_args = OUTPUT_PRESETS.get(preset_id, (None, None))
    if out_ext is None:  # keep the original format
        ext = source_suffix.lower()
        return ext, KEEP_FORMAT_CODECS.get(ext, ["-codec:a", "copy"])
    return out_ext, codec_args


# ---------------------------------------------------------------------------
# Native folder picker (OS dialog) — works locally
# ---------------------------------------------------------------------------
def pick_folder() -> str:
    """Open a native dialog to choose a folder."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory()
        root.destroy()
        return folder or ""
    except Exception:
        return ""  # no graphical environment (e.g. remote server)


# ---------------------------------------------------------------------------
# Persistence: profiles (JSON database) + draft (unsaved state)
# ---------------------------------------------------------------------------
def load_profiles() -> dict:
    try:
        return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_profiles(profiles: dict):
    PROFILES_PATH.write_text(
        json.dumps(profiles, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_draft():
    try:
        return json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_draft(profile, config, dirty):
    try:
        DRAFT_PATH.write_text(
            json.dumps(
                {
                    "profile": profile,
                    "config": config,
                    "dirty": dirty,
                    "lang": st.session_state.get("lang", DEFAULT_LANG),
                },
                indent=2, ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


def current_config() -> dict:
    """Current config (copy of the persistent `cfg` dict)."""
    return dict(st.session_state["cfg"])


# ---------------------------------------------------------------------------
# Widget <-> cfg synchronization
# ---------------------------------------------------------------------------
def sync(field: str, wkey: str):
    """on_change callback: copy a widget's value into the `cfg` dict."""
    st.session_state["cfg"][field] = st.session_state[wkey]


def ensure_widget(wkey: str, value):
    """Restore the value of a widget purged by Streamlit (conditional rendering)."""
    if wkey not in st.session_state:
        st.session_state[wkey] = value


# ---------------------------------------------------------------------------
# Initialization (first run of the session): restore the draft
# ---------------------------------------------------------------------------
if "init_done" not in st.session_state:
    profiles = load_profiles()
    draft = load_draft()

    lang = DEFAULT_LANG
    if draft and isinstance(draft.get("config"), dict):
        cfg = {**DEFAULTS, **draft["config"]}
        active = draft.get("profile")
        if active not in profiles:
            active = None
        if draft.get("lang") in LANGUAGES:
            lang = draft["lang"]
        snapshot = {**DEFAULTS, **profiles[active]} if active else dict(DEFAULTS)
    else:
        cfg = dict(DEFAULTS)
        active = None
        snapshot = dict(DEFAULTS)

    st.session_state["cfg"] = dict(cfg)
    st.session_state["saved_snapshot"] = snapshot
    for field, wkey in WIDGET_KEYS.items():
        st.session_state[wkey] = cfg[field]
    st.session_state["lang"] = lang
    st.session_state["active_profile"] = active
    st.session_state["profile_name"] = active or ""
    st.session_state["profile_select"] = active or ""
    st.session_state["init_done"] = True


# ---------------------------------------------------------------------------
# Profile callbacks (mutating session_state is allowed inside a callback,
# including for keys of widgets that are already instantiated)
# ---------------------------------------------------------------------------
def cb_load():
    profiles = load_profiles()
    sel = st.session_state.get("profile_select", "")
    if sel not in profiles:
        return
    cfg = {**DEFAULTS, **profiles[sel]}
    st.session_state["cfg"] = dict(cfg)
    for field, wkey in WIDGET_KEYS.items():
        st.session_state[wkey] = cfg[field]
    st.session_state["active_profile"] = sel
    st.session_state["profile_name"] = sel
    st.session_state["saved_snapshot"] = dict(cfg)


def cb_save():
    name = st.session_state.get("profile_name", "").strip()
    if not name:
        return
    cfg = current_config()
    profiles = load_profiles()
    profiles[name] = cfg
    save_profiles(profiles)
    st.session_state["active_profile"] = name
    st.session_state["saved_snapshot"] = dict(cfg)
    st.session_state["profile_select"] = name  # keep the dropdown in sync
    st.session_state["_just_saved"] = name


def cb_delete():
    name = st.session_state.get("profile_name", "").strip()
    profiles = load_profiles()
    if name in profiles:
        profiles.pop(name)
        save_profiles(profiles)
    st.session_state["active_profile"] = None
    st.session_state["profile_name"] = ""
    st.session_state["profile_select"] = ""
    st.session_state["saved_snapshot"] = dict(DEFAULTS)


# Translations for the current language
T = get_translations(st.session_state["lang"])
PRESETS_T = T.get("presets", {})


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Auto Pitch Export", page_icon="🎚️", layout="centered")

# CSS: blinking floppy-disk indicator + hand cursor on dropdowns/radios
st.markdown(
    """
    <style>
    @keyframes blink { 0%,100% {opacity:1;} 50% {opacity:0.12;} }
    .floppy-dirty { animation: blink 1s ease-in-out infinite;
                    color:#e63946; font-weight:700; font-size:1.05rem; }
    .floppy-saved { color:#2a9d8f; font-weight:700; font-size:1.05rem; }
    /* Show a pointer (hand) instead of a text caret on select widgets */
    div[data-baseweb="select"], div[data-baseweb="select"] * { cursor: pointer !important; }
    label[data-baseweb="radio"], label[data-baseweb="radio"] * { cursor: pointer !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title(T["title"])
st.caption(T["caption"])

if not ffmpeg_available():
    st.error(T["ffmpeg_missing"])

# "Modified / saved" state (cfg is always present, never purged)
dirty = st.session_state["cfg"] != st.session_state["saved_snapshot"]

# "Remember to save" warning — also visible after a page refresh
if dirty:
    active = st.session_state.get("active_profile")
    if active:
        st.warning(T["save_reminder_active"].format(name=active))
    else:
        st.warning(T["save_reminder_none"])


# ---------------------------------------------------------------------------
# Sidebar: language + profile management
# ---------------------------------------------------------------------------
with st.sidebar:
    st.selectbox(
        T["language_label"], LANGUAGES, key="lang",
        format_func=lambda code: get_translations(code).get("language_name", code),
    )

    st.header(T["sidebar_profiles"])

    if dirty:
        st.markdown(f"<div class='floppy-dirty'>{T['floppy_unsaved']}</div>",
                    unsafe_allow_html=True)
    else:
        st.markdown(f"<div class='floppy-saved'>{T['floppy_saved']}</div>",
                    unsafe_allow_html=True)

    profiles = load_profiles()
    names = list(profiles.keys())

    # Select a profile -> loads it immediately (no separate "Load" button).
    # Value "" = placeholder (stable, language-independent).
    st.selectbox(
        T["load_profile"], [""] + names, key="profile_select",
        format_func=lambda n: T["select_placeholder"] if n == "" else n,
        on_change=cb_load,
    )

    # Save / delete happen right here, in the same place as the selection.
    st.text_input(T["profile_name"], key="profile_name", placeholder=T["profile_name_ph"])
    name = st.session_state.get("profile_name", "").strip()

    b1, b2 = st.columns(2)
    b1.button(T["save_btn"], type="primary", use_container_width=True,
              on_click=cb_save, disabled=not name)
    b2.button(T["delete_btn"], use_container_width=True,
              on_click=cb_delete, disabled=name not in profiles)

    saved_name = st.session_state.pop("_just_saved", None)
    if saved_name:
        st.toast(T["saved_toast"].format(name=saved_name))


# ---------------------------------------------------------------------------
# Main area: configuration
# ---------------------------------------------------------------------------
st.radio(
    T["what_to_pitch"], ["folder", "files"], key="w_mode", horizontal=True,
    format_func=lambda m: T["mode_folder"] if m == "folder" else T["mode_files"],
    on_change=sync, args=("mode", "w_mode"),
)
mode = st.session_state["w_mode"]

uploaded_files = None

# --- Input ---
if mode == "folder":
    c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
    with c2:
        if st.button(T["browse"], key="browse_in", use_container_width=True):
            chosen = pick_folder()
            if chosen:
                st.session_state["cfg"]["input_dir"] = chosen
                st.session_state["w_input_dir"] = chosen
    ensure_widget("w_input_dir", st.session_state["cfg"]["input_dir"])
    c1.text_input(T["input_folder"], key="w_input_dir", placeholder=T["input_folder_ph"],
                  on_change=sync, args=("input_dir", "w_input_dir"))
else:
    st.caption(T["files_not_saved_note"])
    uploaded_files = st.file_uploader(
        T["files_uploader"],
        type=[e.lstrip(".") for e in AUDIO_EXTENSIONS],
        accept_multiple_files=True,
    )

# --- Output ---
o1, o2 = st.columns([5, 1], vertical_alignment="bottom")
with o2:
    if st.button(T["browse"], key="browse_out", use_container_width=True):
        chosen = pick_folder()
        if chosen:
            st.session_state["cfg"]["output_dir"] = chosen
            st.session_state["w_output_dir"] = chosen
ensure_widget("w_output_dir", st.session_state["cfg"]["output_dir"])
o1.text_input(T["output_folder"], key="w_output_dir", placeholder=T["output_folder_ph"],
              on_change=sync, args=("output_dir", "w_output_dir"))

# --- Settings ---
r1, r2 = st.columns(2)
ensure_widget("w_pitch", st.session_state["cfg"]["pitch_percent"])
r1.slider(T["pitch_slider"], min_value=-12.0, max_value=12.0, step=0.1, key="w_pitch",
          on_change=sync, args=("pitch_percent", "w_pitch"))
ensure_widget("w_preset", st.session_state["cfg"]["preset_label"])
r2.selectbox(T["format_select"], list(OUTPUT_PRESETS), key="w_preset",
             format_func=lambda pid: PRESETS_T.get(pid, pid),
             on_change=sync, args=("preset_label", "w_preset"))

cfg = st.session_state["cfg"]
input_dir = cfg["input_dir"]
output_dir = cfg["output_dir"]
pitch_percent = cfg["pitch_percent"]
preset_id = cfg["preset_label"]

st.divider()
run = st.button(T["run_btn"], type="primary", use_container_width=True)

# Persist the draft (= current state + unsaved flag) on every run.
# Lets us restore "Remember to save" even after a browser refresh.
save_draft(st.session_state.get("active_profile"), current_config(), dirty)


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------
def collect_folder_files(folder: str):
    return sorted(
        f for f in Path(folder).iterdir()
        if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
    )


if run:
    if not ffmpeg_available():
        st.error(T["ffmpeg_missing_short"])
        st.stop()

    rate = 1.0 + (pitch_percent / 100.0)
    tmp_dir = None

    # ---- Build the file list ----
    if mode == "folder":
        if not input_dir or not Path(input_dir).is_dir():
            st.error(T["invalid_input"])
            st.stop()
        files = collect_folder_files(input_dir)
    else:
        if not uploaded_files:
            st.error(T["no_files_selected"])
            st.stop()
        tmp_dir = Path(tempfile.mkdtemp(prefix="pitch_in_"))
        files = []
        for uf in uploaded_files:
            p = tmp_dir / uf.name
            p.write_bytes(uf.getbuffer())
            files.append(p)

    if not files:
        st.error(T["no_audio_found"])
        st.stop()

    # ---- Output folder ----
    if output_dir and output_dir.strip():
        out_dir = Path(output_dir.strip())
    elif mode == "folder":
        out_dir = Path(input_dir) / "pitched"
    else:
        out_dir = Path.cwd() / "pitched"
    out_dir.mkdir(parents=True, exist_ok=True)

    st.info(T["run_info"].format(
        pct=f"{pitch_percent:+.2f}", rate=f"{rate:.4f}",
        preset=PRESETS_T.get(preset_id, preset_id), out=out_dir,
    ))

    progress = st.progress(0.0, text=T["starting"])
    log_area = st.empty()
    logs = []
    ok = errors = 0

    for i, f in enumerate(files, 1):
        progress.progress((i - 1) / len(files), text=T["processing"].format(name=f.name))
        out_ext, codec_args = resolve_codec(preset_id, f.suffix)
        out_path = out_dir / (f.stem + out_ext)

        # Avoid overwriting the source if same folder + same name/format
        if out_path.resolve() == f.resolve():
            out_path = out_dir / (f.stem + "_pitched" + out_ext)

        try:
            pitch_file(f, out_path, rate, codec_args)
            ok += 1
            logs.append(f"[{i}/{len(files)}] ✅ {f.name} → {out_path.name}")
        except Exception as e:
            errors += 1
            logs.append(f"[{i}/{len(files)}] ❌ {f.name} : {e}")
        log_area.code("\n".join(logs), language=None)

    progress.progress(1.0, text=T["done_progress"])

    if tmp_dir:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if errors == 0:
        st.success(T["success"].format(ok=ok, out=out_dir))
    else:
        st.warning(T["partial"].format(ok=ok, errors=errors, out=out_dir))
    st.balloons()
