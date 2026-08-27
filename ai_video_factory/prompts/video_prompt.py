"""Image-to-video motion prompt builder (spec §12)."""

from __future__ import annotations

from ai_video_factory.models.scene import Scene
from ai_video_factory.models.video import MotionParams

_CAMERA_MOTION_WORDS: dict[str, str] = {
    "static": "static camera, subtle natural motion",
    "zoom_in": "slow smooth zoom-in",
    "zoom_out": "slow smooth zoom-out",
    "pan_left": "smooth pan to the left",
    "pan_right": "smooth pan to the right",
    "tilt_up": "slow tilt upward",
    "tilt_down": "slow tilt downward",
    "orbit": "gentle orbital camera movement",
    "dolly_forward": "cinematic dolly forward",
    "handheld": "subtle handheld camera sway",
}


def build_video_prompt(
    scene: Scene,
    *,
    motion: MotionParams | None = None,
) -> str:
    """Compose the image-to-video prompt for one scene.

    Combines the scene's own motion hints with explicit motion parameters,
    and appends consistency guard-rails (no morphing, stable character).
    """
    motion = motion or MotionParams()
    parts: list[str] = []

    base = (scene.video_prompt or "").strip()
    if base:
        parts.append(base)

    camera_words = _CAMERA_MOTION_WORDS.get(motion.camera_motion, motion.camera_motion.replace("_", " "))
    if scene.camera.strip():
        parts.append(f"camera: {scene.camera.strip()} with {camera_words}")
    else:
        parts.append(f"camera: {camera_words}")

    if motion.motion_strength >= 7:
        parts.append("dynamic movement, energetic action")
    elif motion.motion_strength <= 3:
        parts.append("minimal subtle motion")

    parts.append(f"duration about {motion.duration_s:.0f} seconds at {motion.fps} fps")
    parts.append("consistent characters and environment with the reference image, "
                 "no morphing, no warping, no scene change, smooth cinematic motion")
    return ", ".join(parts)
