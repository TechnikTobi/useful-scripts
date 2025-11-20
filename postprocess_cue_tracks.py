#!/usr/bin/env python3
"""
python postprocess_cue_tracks.py /path/to/album.cue \
   --tracks-dir "/path/to/generated/tracks" \
   --pattern "*.wav" \
   --output-format m4a \
   --dry-run

What it does:
- Reads the .cue and extracts global PERFORMER (album artist), TITLE (album),
  and per-track TRACK number, TITLE, PERFORMER.
- Scans the tracks directory for files whose names start with the track number
  (e.g. "01 - Song Title.wav" or "1_Song Title.wav").
- Removes the numeric prefix from the filename (so "01 - Foo.wav" -> "Foo.m4a").
- Invokes ffmpeg to rewrite the file and embed metadata (title, artist, ...)
- By default converts to `m4a` (ALAC) which is fully supported by iTunes.
  You can change --output-format to "flac" or "wav" if you prefer. For WAV,
  tags are limited; prefer m4a or flac for reliable metadata.
"""

import argparse
import re
import shlex
import subprocess
import sys
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Regex that captures track filenames that start with a number, e.g.
# * 01 - Song Title.wav
# * 1. Song Title.flac
# * 002_Song Title.mp3
TRACK_PREFIX_RE = re.compile(r'^\s*0*(\d{1,3})\s*[-_.\s]+\s*(.+)$')

def parse_cue(
    cue_path: Path
) -> Dict:

    """
    Parse minimal .cue metadata. Returns dict with album info and tracks list.
    """

    album = {
        'PERFORMER': None, 
        'TITLE':     None, 
        'REM':       {}, 
        'FILE':      None
    }
    tracks        = []
    current_track = None

    with cue_path.open("r", encoding="utf-8", errors="ignore") as f:

        for raw in f:

            line = raw.strip()
            if not line:
                continue

            parts = shlex.split(line) if '"' in line else line.split(maxsplit=2)
            key   = parts[0].upper()

            if key == "REM":
                # store remainder as REM key/value
                if len(parts) >= 3:
                    # REM GENRE "Rock" or REM DATE 1995
                    album["REM"][parts[1]] = parts[2].strip('"')
                continue

            if key == "PERFORMER" and current_track is None:
                # album-level performer
                album["PERFORMER"] = line.partition(' ')[2].strip().strip('"')

            elif key == "TITLE" and current_track is None:
                album["TITLE"] = line.partition(' ')[2].strip().strip('"')

            elif key == "FILE":
                # FILE "name.wav" WAVE
                m = re.search(r'\"([^\"]+)\"', line)
                album["FILE"] = m.group(1) if m else parts[1].strip('"')

            elif key == "TRACK":
                # begin new track block
                if current_track:
                    tracks.append(current_track)
                num = int(parts[1])
                current_track = {
                    "number":    num, 
                    "TITLE":     None, 
                    "PERFORMER": None, 
                    "INDEX":     None
                }

            elif key == "PERFORMER" and current_track is not None:
                current_track["PERFORMER"] = line.partition(' ')[2].strip().strip('"')
            elif key == "TITLE" and current_track is not None:
                current_track["TITLE"] = line.partition(' ')[2].strip().strip('"')
            elif key == "INDEX" and current_track is not None:
                current_track["INDEX"] = parts[1:]

    if current_track:
        tracks.append(current_track)

    return {"album": album, "tracks": tracks}



def find_track_file(
    tracks_dir: Path, 
    track_num:  int, 
    pattern:    str
) -> Optional[Path]:

    """
    Search tracks_dir for a file that starts with the track number or contains the padded num.
    """

    padded = f"{track_num:02d}"
    candidates = list(tracks_dir.glob(pattern))

    # Prefer files that start with the number
    for candidate in candidates:
        m = TRACK_PREFIX_RE.match(candidate.name)
        if m and int(m.group(1)) == track_num:
            return candidate

    # Otherwise look for padded number anywhere in name
    for candidate in candidates:
        if padded in candidate.name:
            return candidate

    # Lastly, if there is exactly one file and only one track, return it
    if len(candidates) == 1 and len(list(tracks_dir.glob(pattern))) == 1:
        return candidates[0]

    return None



def build_ffmpeg_command(
    input_path:  Path, 
    output_path: Path, 
    tags:        Dict[str, str], 
    copy_audio:  bool = True
) -> List[str]:
    
    """
    Construct ffmpeg command for embedding metadata.
    - copy_audio: if True, use -c:a copy when converting between containers that support metadata;
                  otherwise fallback to encoding (not done by default).
    """

    cmd = ["ffmpeg", "-y", "-i", str(input_path)]

    # Metadata
    for key, value in tags.items():
        if value is None:
            continue
        cmd += ['-metadata', f'{key}={value}']

    # Choose codec behavior: try to copy audio to be fast and lossless when possible
    if copy_audio:
        cmd += ['-c', 'copy']
    else:
        cmd += ['-c:a', 'alac']  # encoding fallback if requested in future

    cmd += [str(output_path)]
    return cmd



def sanitize_filename(
    name: str
) -> str:

    # Remove problematic chars for filenames and trim spaces
    return re.sub(r'[\/\?%:\*\|"<>\u0000-\u001F]+', '', name).strip()



def process(cue_file: Path, tracks_dir: Path, pattern: str = '*.*', output_format: Optional[str] = 'm4a', dry_run: bool = False):
    if not cue_file.exists():
        raise FileNotFoundError(f"cue file not found: {cue_file}")
    meta = parse_cue(cue_file)
    album = meta['album']
    tracks = meta['tracks']

    print(f'Parsed album: {album.get("TITLE")!r} by {album.get("PERFORMER")!r}')
    print(f'Found {len(tracks)} tracks in cue. Scanning folder: {tracks_dir} with pattern {pattern}')

    for t in tracks:
        tn         = t['number']
        ttitle     = t.get('TITLE') or f'Track {tn}'
        tperformer = t.get('PERFORMER') or album.get('PERFORMER')

        found = find_track_file(tracks_dir, tn, pattern)
        if not found:
            # Alternative search path
            found = find_track_file(
                Path(os.path.dirname(cue_file) + "/tracks"),
                tn,
                pattern
            )

        if not found:
            print(f'WARN: No file found for track {tn:02d} - "{ttitle}"')
            continue
        print(f'Found file for track {tn:02d}: {found.name}')

        # new base name -> remove leading number
        # e.g. "01 - Foo.wav" -> "Foo.m4a" (output format applied)
        base_title = re.sub(r'^\s*0*%d\s*[-_.\s]+' % tn, '', found.name, flags=re.IGNORECASE)
        
        # if above didn't match, also try to strip a leading "01 " without delimiter
        base_title = re.sub(r'^\s*0*%d\s+' % tn, '', base_title, flags=re.IGNORECASE)
        
        # remove extension then sanitize and add new extension
        stem = Path(base_title).stem if Path(base_title).stem else ttitle
        stem = sanitize_filename(stem or ttitle)
        out_ext = output_format if output_format.startswith('.') else f'.{output_format}' if output_format else found.suffix
        out_name = f"{stem}{out_ext}"
        output_path = found.with_name(out_name)

        # build metadata dict for ffmpeg - keys are ffmpeg metadata keys
        tags = {
            'title': ttitle,
            'artist': tperformer,
            'album': album.get('TITLE'),
            'track': f"{tn}/{len(tracks)}" if len(tracks)>0 else str(tn),
        }
        # optional REM metadata
        if 'DATE' in album.get('REM', {}):
            tags['date'] = album['REM']['DATE']
        if 'GENRE' in album.get('REM', {}):
            tags['genre'] = album['REM']['GENRE']

        print(f"--> Will write: {output_path.name} | tags: title='{tags['title']}', artist='{tags['artist']}', track='{tags['track']}'")
        if dry_run:
            continue

        # build and run ffmpeg command
        cmd = build_ffmpeg_command(found, output_path, tags, copy_audio=True)
        print('Running ffmpeg:', ' '.join(shlex.quote(p) for p in cmd))
        try:
            res = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            print('ffmpeg failed with exit code', e.returncode)
            print(e.stderr.decode(errors='ignore'))
            # Try fallback: convert to m4a with ALAC encoding (if copy failed)
            print('Attempting fallback: encode to m4a (alac) with metadata')
            fallback = ['ffmpeg', '-y', '-i', str(found)]
            for k, v in tags.items():
                if v is None: continue
                fallback += ['-metadata', f"{k}={v}"]
            fallback += ['-c:a', 'alac', str(output_path)]
            print('Running:', ' '.join(shlex.quote(p) for p in fallback))
            try:
                subprocess.run(fallback, check=True)
            except subprocess.CalledProcessError as e2:
                print('Fallback also failed. Skipping this track. Error output:')
                print(e2.stderr.decode(errors='ignore') if e2.stderr else 'no stderr')
                continue

        # if ffmpeg succeeded, optionally remove the original if extension changed
        if output_path.exists():
            # if output path same as input (unlikely), nothing to do
            if output_path.resolve() != found.resolve():
                # delete original if you want; here we keep original and optionally you can uncomment to remove
                # found.unlink()
                pass
            print(f'Wrote: {output_path}')

    print('All done. Review files in:', tracks_dir)


def main():
    p = argparse.ArgumentParser(description='Tag and rename split tracks using a .cue file and ffmpeg.')
    p.add_argument('cue',             type=Path,                    help='Path to the .cue file')
    p.add_argument('--tracks-dir',    type=Path, default=Path('.'), help='Directory containing split tracks (default: current dir)')
    p.add_argument('--pattern',       type=str,  default='*.*',     help='Glob pattern to find audio files (default: "*.*" )')
    p.add_argument('--output-format', type=str,  default='m4a',     help='Output file extension (m4a, flac, wav, mp3). Default: m4a (Apple Lossless)')
    p.add_argument('--dry-run', action='store_true',                help='Show actions without running ffmpeg')
    args = p.parse_args()

    try:
        process(args.cue, args.tracks_dir, args.pattern, args.output_format, args.dry_run)
    except Exception as e:
        print('Error:', e)
        sys.exit(1)


if __name__ == '__main__':
    main()
