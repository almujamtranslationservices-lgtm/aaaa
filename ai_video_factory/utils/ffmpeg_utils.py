"""FFmpegEngine — the single gateway to FFmpeg (spec §17).

No scattered ``subprocess`` calls anywhere else: every media operation goes
through this engine so commands are logged, timed and error-mapped centrally.

Binary resolution order
-----------------------
1. ``AVF_FFMPEG_PATH`` / ``AVF_FFPROBE_PATH`` env vars.
2. ``ffmpeg`` / ``ffprobe`` on the system PATH.
3. The static binary bundled with the optional ``imageio-ffmpeg`` package
   (dev/testing convenience — real installs should use system FFmpeg).

Media operations (image→video, concat, mixing, burning subtitles…) are
implemented in PHASE 12 on top of :meth:`FFmpegEngine.run`.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from ai_video_factory.core.exceptions import FFmpegError, FFmpegNotFoundError

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 600.0


def _even(value: int) -> int:
    return value - (value % 2)


class FFmpegEngine:
    """Central, logged FFmpeg/FFprobe runner."""

    def __init__(self, *, ffmpeg_path: str | None = None, ffprobe_path: str | None = None,
                 default_timeout: float = _DEFAULT_TIMEOUT) -> None:
        self.default_timeout = default_timeout
        self._ffmpeg = self._resolve_explicit(ffmpeg_path, "ffmpeg", "AVF_FFMPEG_PATH")
        self._ffprobe = self._resolve_explicit(ffprobe_path, "ffprobe", "AVF_FFPROBE_PATH")

    @classmethod
    def _resolve_explicit(cls, path: str | None, binary: str, env_var: str) -> str | None:
        """An explicit override is authoritative (no fallback) when given."""
        if path is not None:
            return path if Path(path).exists() else None
        return cls._resolve(binary, env_var)

    # ------------------------------------------------------------ resolution
    @staticmethod
    def _resolve(binary: str, env_var: str) -> str | None:
        override = os.environ.get(env_var)
        if override and Path(override).exists():
            return override
        found = shutil.which(binary)
        if found:
            return found
        if binary == "ffmpeg":  # last-resort static fallback for dev/testing
            try:
                import imageio_ffmpeg

                return imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:  # noqa: BLE001 — optional dependency
                return None
        return None

    @property
    def available(self) -> bool:
        return self._ffmpeg is not None

    @property
    def probe_available(self) -> bool:
        return self._ffprobe is not None

    @property
    def ffmpeg_path(self) -> str:
        if self._ffmpeg is None:
            raise FFmpegNotFoundError(
                "FFmpeg not found. Install it (https://ffmpeg.org) or run: pip install imageio-ffmpeg"
            )
        return self._ffmpeg

    @property
    def ffprobe_path(self) -> str:
        if self._ffprobe is None:
            raise FFmpegNotFoundError("ffprobe not found. Install full FFmpeg to enable media probing.")
        return self._ffprobe

    # --------------------------------------------------------------- commands
    def version(self) -> str | None:
        """First line of ``ffmpeg -version``, or ``None`` when unavailable."""
        if not self.available:
            return None
        result = self.run(["-version"], timeout=15)
        return result.stdout.splitlines()[0] if result.stdout else None

    def run(self, args: list[str], *, timeout: float | None = None,
            cwd: Path | str | None = None) -> subprocess.CompletedProcess[str]:
        """Execute an ffmpeg command (without the leading binary name).

        Raises:
            FFmpegNotFoundError: no binary available.
            FFmpegError: non-zero exit code or timeout.
        """
        command = [self.ffmpeg_path, *args]
        logger.debug("FFmpeg exec: %s", " ".join(command))
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout or self.default_timeout,
                cwd=str(cwd) if cwd else None,
            )
        except subprocess.TimeoutExpired as exc:
            raise FFmpegError(f"FFmpeg timed out after {timeout or self.default_timeout}s: {' '.join(args[:6])}…") from exc
        except OSError as exc:
            raise FFmpegError(f"Failed to launch FFmpeg: {exc}") from exc
        if result.returncode != 0:
            stderr_tail = (result.stderr or "")[-2000:].strip()
            raise FFmpegError(f"FFmpeg exited with code {result.returncode}: {stderr_tail or 'no stderr'}",
                              details={"args": args[:20]})
        return result

    def probe(self, media_path: Path | str) -> dict:
        """Return ffprobe metadata (format + streams) as a parsed dict.

        Raises:
            FFmpegError: when ffprobe is missing or the file cannot be probed.
        """
        command = [
            self.ffprobe_path, "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(media_path),
        ]
        import json

        logger.debug("FFprobe exec: %s", " ".join(command))
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired as exc:
            raise FFmpegError(f"ffprobe timed out on {media_path}") from exc
        if result.returncode != 0:
            raise FFmpegError(f"ffprobe failed on {media_path}: {(result.stderr or '').strip()[:500]}")
        return json.loads(result.stdout or "{}")

    # ------------------------------------------------------- media operations
    # concat / mix / burn land in PHASE 12; image_to_video is delivered with
    # PHASE 8 because the demo video provider animates stills with it.

    def image_to_video(
        self,
        image: Path,
        output: Path,
        *,
        duration: float,
        fps: int,
        width: int,
        height: int,
        motion: str = "zoom_in",
    ) -> Path:
        """Still image → cinematic clip via FFmpeg ``zoompan`` (Ken Burns).

        Args:
            motion: ``zoom_in`` | ``zoom_out`` | ``pan_left`` | ``pan_right`` |
                ``static``.
        """
        image, output = Path(image), Path(output)
        if not image.exists():
            raise FFmpegError(f"image_to_video: source image not found: {image}")
        frames = max(1, int(round(duration * fps)))
        safe_w, safe_h = _even(max(2, width)), _even(max(2, height))

        motion = motion if motion in {"zoom_in", "zoom_out", "pan_left", "pan_right", "static"} else "zoom_in"
        if motion == "zoom_in":
            z = f"min(1+{0.25 / frames:.6f}*on,1.25)"
            x = "iw/2-(iw/zoom/2)"
            y = "ih/2-(ih/zoom/2)"
        elif motion == "zoom_out":
            z = f"max(1.25-{0.25 / frames:.6f}*on,1.001)"
            x = "iw/2-(iw/zoom/2)"
            y = "ih/2-(ih/zoom/2)"
        elif motion == "pan_left":
            z = "1.15"
            x = f"(iw-iw/zoom)*on/{frames}"
            y = "ih/2-(ih/zoom/2)"
        elif motion == "pan_right":
            z = "1.15"
            x = f"(iw-iw/zoom)*(1-on/{frames})"
            y = "ih/2-(ih/zoom/2)"
        else:  # static
            z = "1.001"
            x = "iw/2-(iw/zoom/2)"
            y = "ih/2-(ih/zoom/2)"

        # Upscale 3x before zoompan (smooth sub-pixel motion, no jitter).
        video_filter = (
            f"scale={safe_w * 3}:{safe_h * 3}:force_original_aspect_ratio=increase,"
            f"crop={safe_w * 3}:{safe_h * 3},"
            f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={safe_w}x{safe_h}:fps={fps}"
        )
        self.run([
            "-y",
            "-i", str(image),
            "-vf", video_filter,
            "-frames:v", str(frames),
            "-r", str(fps),
            "-pix_fmt", "yuv420p",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-movflags", "+faststart",
            str(output),
        ], timeout=max(60.0, duration * 4))
        if not output.exists() or output.stat().st_size == 0:
            raise FFmpegError(f"image_to_video: no output produced at {output}")
        return output

    def validate_video(self, video: Path) -> bool:
        """Decode the whole file (``-f null``) — True when the clip is intact."""
        result = self.run(["-v", "error", "-i", str(video), "-f", "null", "-"],
                          timeout=max(30.0, 60.0))
        return result.returncode == 0

    def concat_videos(self, clips: list[Path], output: Path) -> Path:  # pragma: no cover
        """Concatenate same-format clips with stream copying when possible."""
        raise NotImplementedError("concat_videos is planned for PHASE 12 (rendering pipeline)")

    # ------------------------------------------------------------- audio mix
    def mix_audio(
        self,
        output: Path,
        *,
        voice: Path | None = None,
        music: Path | None = None,
        sfx: list[Path] | None = None,
        duration_s: float | None = None,
        voice_volume: float = 1.0,
        music_volume: float = 0.25,
        music_fade_in: float = 2.0,
        music_fade_out: float = 3.0,
        ducking_enabled: bool = True,
        duck_threshold: float = 0.03,
        duck_ratio: float = 8.0,
        sfx_volume: float = 0.6,
        sample_rate: int = 44100,
    ) -> Path:
        """Mix voice-over + background music + SFX into one WAV (spec §14).

        * Music loops automatically (``-stream_loop -1``) and is trimmed to
          ``duration_s`` with fade-in/out.
        * **Ducking**: while the narrator speaks, the music is compressed via
          ``sidechaincompress`` driven by the voice signal, then released.
        * Every input is normalised to stereo/``sample_rate``; the final bus
          runs through ``alimiter`` so the mix never clips.
        """
        output = Path(output)
        sfx = [Path(clip) for clip in (sfx or []) if Path(clip).exists()]
        if voice is not None and not Path(voice).exists():
            raise FFmpegError(f"mix_audio: voice file not found: {voice}")
        if music is not None and not Path(music).exists():
            raise FFmpegError(f"mix_audio: music file not found: {music}")
        if not (voice or music or sfx):
            raise FFmpegError("mix_audio: nothing to mix — provide voice, music or sfx")

        inputs: list[str] = []
        if voice is not None:
            inputs += ["-i", str(voice)]
        if music is not None:
            inputs += ["-stream_loop", "-1", "-i", str(music)]
        for clip in sfx:
            inputs += ["-i", str(clip)]

        fmt = f"aformat=sample_rates={sample_rate}:channel_layouts=stereo"
        chains: list[str] = []
        mix_labels: list[str] = []
        index = 0

        if voice is not None:
            chain = f"[{index}:a]{fmt},volume={voice_volume:.3f}"
            if duration_s is not None:
                chain += f",apad,atrim=end={duration_s:.3f}"
            if ducking_enabled and music is not None:
                # Sidechain signal feeds sidechaincompress on the music bus.
                chain += ",asplit=2[vout][sc]"
            else:
                chain += "[vout]"
            chains.append(chain)
            mix_labels.append("[vout]")
            index += 1

        if music is not None:
            chain = f"[{index}:a]{fmt},volume={music_volume:.3f}"
            if music_fade_in > 0:
                chain += f",afade=t=in:curve=tri:d={music_fade_in:.2f}"
            if duration_s is not None and music_fade_out > 0:
                fade_start = max(0.0, duration_s - music_fade_out)
                chain += f",afade=t=out:curve=tri:st={fade_start:.2f}:d={music_fade_out:.2f}"
            if duration_s is not None:
                chain += f",atrim=end={duration_s:.3f}"
            if ducking_enabled and voice is not None:
                chains.append(chain + "[mprep]")
                chains.append(
                    f"[mprep][sc]sidechaincompress=threshold={duck_threshold}:"
                    f"ratio={duck_ratio:.2f}:attack=60:release=500[mout]"
                )
            else:
                chains.append(chain + "[mout]")
            mix_labels.append("[mout]")
            index += 1

        for clip in sfx:
            chains.append(f"[{index}:a]{fmt},volume={sfx_volume:.3f}[sfx{index}]")
            mix_labels.append(f"[sfx{index}]")
            index += 1

        final = (
            f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=longest:"
            f"normalize=0,alimiter=limit=0.97[aout]"
        )
        filter_complex = ";".join(chains + [final])

        args = [
            "-y", *inputs,
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            "-c:a", "pcm_s16le", "-ar", str(sample_rate),
        ]
        if duration_s is not None:
            args += ["-t", f"{duration_s:.3f}"]
        args += [str(output)]

        output.parent.mkdir(parents=True, exist_ok=True)
        self.run(args, timeout=max(90.0, (duration_s or 30.0) * 8))
        if not output.exists() or output.stat().st_size <= 44:
            raise FFmpegError(f"mix_audio: no WAV produced at {output}")
        return output

    def burn_subtitles(self, video: Path, subtitle_file: Path, output: Path, *,
                       style: dict) -> Path:  # pragma: no cover
        """Burn SRT/ASS subtitles into the video stream."""
        raise NotImplementedError("burn_subtitles is planned for PHASE 11/12")

    def extract_thumbnail(self, video: Path, output: Path, *, time_s: float = 0.0) -> Path:  # pragma: no cover
        """Grab a single frame as a thumbnail image."""
        raise NotImplementedError("extract_thumbnail is planned for PHASE 12")
