#!/usr/bin/env python3
"""
pitch_batch.py

Pitches (speed + pitch, like "Change Speed" in Audacity) every audio file in an
input folder and exports them to an output folder.

Requires ffmpeg installed and available in PATH.
  -> Windows : https://ffmpeg.org/download.html (or "winget install ffmpeg")
  -> Mac     : brew install ffmpeg
  -> Linux   : sudo apt install ffmpeg

Usage:
    python pitch_batch.py "C:/path/input_folder" "C:/path/output_folder" --rate 1.02

By default --rate is 1.02 (i.e. +2%).
"""

import argparse
import subprocess
import sys
from pathlib import Path

# Supported audio extensions
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".aiff", ".aif", ".m4a", ".ogg", ".wma"}

def check_ffmpeg():
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("ERREUR : ffmpeg n'est pas installé ou n'est pas dans le PATH.")
        print("Installe-le puis relance le script.")
        sys.exit(1)

def get_sample_rate(filepath: Path) -> int:
    """Get the file's sample rate via ffprobe."""
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
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 44100  # default value if detection fails

def pitch_file(input_path: Path, output_path: Path, rate: float, out_ext: str):
    sample_rate = get_sample_rate(input_path)
    new_rate = int(sample_rate * rate)

    # asetrate = replay the file at a different sample rate (changes speed + pitch)
    # aresample = go back to the standard sample rate for player compatibility
    filter_chain = f"asetrate={new_rate},aresample={sample_rate}"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-filter:a", filter_chain,
        "-vn",
    ]

    # Quality settings depending on the output format
    if out_ext == ".mp3":
        cmd += ["-codec:a", "libmp3lame", "-q:a", "0"]  # max VBR quality
    elif out_ext == ".flac":
        cmd += ["-codec:a", "flac"]
    elif out_ext == ".wav":
        cmd += ["-codec:a", "pcm_s16le"]

    cmd.append(str(output_path))

    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

def main():
    parser = argparse.ArgumentParser(description="Pitch en masse de fichiers audio (vitesse + hauteur).")
    parser.add_argument("input_dir", help="Dossier contenant les musiques d'origine")
    parser.add_argument("output_dir", help="Dossier où exporter les musiques pitchées")
    parser.add_argument("--rate", type=float, default=1.02, help="Facteur de pitch (défaut: 1.02 = +2%%)")
    parser.add_argument("--ext", default=None, help="Forcer le format de sortie (ex: mp3, wav, flac). Par défaut : garde le format d'origine.")
    args = parser.parse_args()

    check_ffmpeg()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = [f for f in input_dir.iterdir() if f.suffix.lower() in AUDIO_EXTENSIONS]

    if not files:
        print(f"Aucun fichier audio trouvé dans {input_dir}")
        return

    print(f"{len(files)} fichier(s) trouvé(s). Pitch x{args.rate} en cours...\n")

    for i, f in enumerate(files, 1):
        out_ext = f".{args.ext.lstrip('.')}" if args.ext else f.suffix
        out_path = output_dir / (f.stem + out_ext)
        print(f"[{i}/{len(files)}] {f.name} -> {out_path.name}")
        try:
            pitch_file(f, out_path, args.rate, out_ext.lower())
        except Exception as e:
            print(f"   Erreur sur {f.name} : {e}")

    print("\nTerminé ! Fichiers exportés dans :", output_dir)

if __name__ == "__main__":
    main()
