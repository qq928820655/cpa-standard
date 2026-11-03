"""影视界受控 FFmpeg 成片导出服务。"""
import asyncio
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import DATA_DIR
from .models import (
    VideoGenerationTask,
    VideoProjectAudioTask,
    VideoProjectExportTask,
    VideoProjectSubtitleTask,
    VideoProjectTimelineItem,
)


class VideoExportService:
    EXPORT_ROOT = DATA_DIR / "video_exports"
    CACHE_ROOT = EXPORT_ROOT / "cache"
    MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
    DOWNLOAD_TIMEOUT_SECONDS = 300
    EXPORT_TIMEOUT_SECONDS = 1800

    @property
    def ffmpeg_path(self) -> Path:
        package_root = Path(__file__).resolve().parents[2]
        binary_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        bundled = package_root / "tools" / "ffmpeg" / "bin" / binary_name
        return bundled if bundled.is_file() else Path(shutil.which(binary_name) or bundled)

    @property
    def ffprobe_path(self) -> Path:
        binary_name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
        bundled = self.ffmpeg_path.with_name(binary_name)
        return bundled if bundled.is_file() else Path(shutil.which(binary_name) or bundled)

    def probe_media(self, media_path: Path) -> dict:
        if not self.ffprobe_path.is_file():
            raise RuntimeError("未找到 FFprobe，请在 tools/ffmpeg/bin 或 PATH 中安装")
        result = subprocess.run(
            [
                str(self.ffprobe_path), "-v", "error", "-show_entries",
                "format=duration:stream=codec_type", "-of", "json", str(media_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or "FFprobe 媒体探测失败").strip()[:1000])
        data = json.loads(result.stdout or "{}")
        try:
            duration_ms = max(1, round(float(data.get("format", {}).get("duration", 0)) * 1000))
        except (TypeError, ValueError):
            raise RuntimeError("FFprobe 未返回有效媒体时长")
        return {"duration_ms": duration_ms, "has_audio": any(item.get("codec_type") == "audio" for item in data.get("streams", []))}

    def probe_audio_stream(self, media_path: Path) -> bool:
        return self.probe_media(media_path)["has_audio"]

    def probe_duration(self, media_path: Path) -> int:
        return self.probe_media(media_path)["duration_ms"]

    async def extract_audio(self, video_path: Path, output_path: Path) -> Path:
        if not video_path.is_file():
            raise ValueError("待提取的视频文件不存在")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = await asyncio.to_thread(
            subprocess.run,
            [
                str(self.ffmpeg_path), "-y", "-i", str(video_path), "-vn",
                "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            shell=False,
            check=False,
        )
        if result.returncode != 0 or not output_path.is_file():
            raise RuntimeError((result.stderr or "FFmpeg 音频提取失败").strip()[-2000:])
        return output_path

    def preflight(self) -> dict:
        path = self.ffmpeg_path
        if not path.is_file():
            return {
                "available": False,
                "path": str(path),
                "version": None,
                "error": "未找到 FFmpeg，请在 tools/ffmpeg/bin 或 PATH 中安装",
            }
        try:
            result = subprocess.run(
                [str(path), "-version"],
                capture_output=True,
                text=True,
                timeout=15,
                shell=False,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"available": False, "path": str(path), "version": None, "error": f"FFmpeg 预检失败：{exc}"}
        if result.returncode != 0:
            return {"available": False, "path": str(path), "version": None, "error": (result.stderr or "FFmpeg 无法运行").strip()[:500]}
        return {"available": True, "path": str(path), "version": (result.stdout or "").splitlines()[0], "error": None}

    @staticmethod
    def _safe_url(url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not parsed.username and not parsed.password

    @staticmethod
    def _timestamp(milliseconds: int) -> str:
        milliseconds = max(0, milliseconds)
        hours, milliseconds = divmod(milliseconds, 3_600_000)
        minutes, milliseconds = divmod(milliseconds, 60_000)
        seconds, milliseconds = divmod(milliseconds, 1000)
        return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"

    def _merge_subtitles(self, subtitle_items: list[tuple[int, str]], duration_ms: int | None = None) -> str:
        blocks: list[str] = []
        index = 1
        timestamp_pattern = re.compile(r"(\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2},\d{3})")

        def parse_timestamp(value: str) -> int:
            hours, minutes, rest = value.split(":")
            seconds, milliseconds = rest.split(",")
            return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(milliseconds)

        for offset_ms, content in subtitle_items:
            for block in re.split(r"\r?\n\s*\r?\n", content.strip()):
                lines = [line for line in block.splitlines() if line.strip()]
                if len(lines) < 3:
                    continue
                match = timestamp_pattern.fullmatch(lines[1].strip())
                if not match:
                    continue
                start_ms = parse_timestamp(match.group(1)) + offset_ms
                end_ms = parse_timestamp(match.group(2)) + offset_ms
                if end_ms <= start_ms or (duration_ms is not None and start_ms >= duration_ms):
                    continue
                end_ms = min(end_ms, duration_ms) if duration_ms is not None else end_ms
                if end_ms <= start_ms:
                    continue
                start = self._timestamp(start_ms)
                end = self._timestamp(end_ms)
                blocks.append(f"{index}\n{start} --> {end}\n" + "\n".join(lines[2:]))
                index += 1
        return "\n\n".join(blocks)

    async def _resolve_timeline(self, db: AsyncSession, project_id: int) -> tuple[list[dict], list[dict], list[tuple[int, str]], list[str], int]:
        result = await db.execute(
            select(VideoProjectTimelineItem)
            .where(VideoProjectTimelineItem.project_id == project_id)
            .order_by(VideoProjectTimelineItem.track, VideoProjectTimelineItem.position, VideoProjectTimelineItem.id)
        )
        entries = list(result.scalars().all())
        videos: list[dict] = []
        audios: list[dict] = []
        subtitles: list[tuple[int, str]] = []
        errors: list[str] = []
        duration_ms = 0
        for item in entries:
            if item.track == "video" and item.source_type == "video_task":
                task = await db.get(VideoGenerationTask, item.source_id)
                if not task or task.status != "completed" or not task.video_url:
                    errors.append(f"视频轨项目 {item.id} 尚未完成或没有视频地址")
                    continue
                videos.append({"timeline_id": item.id, "url": task.video_url, "offset_ms": item.offset_ms, "duration_ms": item.duration_ms})
                duration_ms = max(duration_ms, item.offset_ms + (item.duration_ms or 0))
            elif item.track == "subtitle" and item.source_type == "subtitle_task":
                task = await db.get(VideoProjectSubtitleTask, item.source_id)
                if not task or task.status != "completed" or not task.srt_content:
                    errors.append(f"字幕轨项目 {item.id} 尚未完成或没有 SRT")
                    continue
                subtitles.append((item.offset_ms, task.srt_content))
            elif item.track == "audio" and item.source_type == "audio_task":
                task = await db.get(VideoProjectAudioTask, item.source_id)
                if not task or task.status != "completed" or not task.local_path or not Path(task.local_path).is_file():
                    errors.append(f"音频轨项目 {item.id} 尚未完成或本地音频不存在")
                    continue
                audios.append({"timeline_id": item.id, "path": Path(task.local_path), "offset_ms": item.offset_ms})
        if not videos:
            errors.append("时间线没有可导出的视频轨")
        return videos, audios, subtitles, errors, duration_ms

    async def _download_video(self, url: str, cache_dir: Path, index: int) -> Path:
        if not self._safe_url(url):
            raise ValueError("视频地址仅允许不含凭据的 HTTP/HTTPS URL")
        parsed = urlparse(url)
        suffix = Path(parsed.path).suffix.lower()
        if suffix not in {".mp4", ".mov", ".mkv", ".webm"}:
            suffix = ".mp4"
        target = cache_dir / f"video-{index}{suffix}"
        if target.is_file() and target.stat().st_size > 0:
            return target
        total = 0
        timeout = httpx.Timeout(connect=30, read=self.DOWNLOAD_TIMEOUT_SECONDS, write=30, pool=30)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            async with client.stream("GET", url, headers={"Accept": "video/*,application/octet-stream"}) as response:
                response.raise_for_status()
                content_type = (response.headers.get("content-type") or "").lower()
                if content_type and not (content_type.startswith("video/") or content_type.startswith("application/octet-stream")):
                    raise ValueError("视频下载响应不是允许的媒体类型")
                with target.open("wb") as output:
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > self.MAX_DOWNLOAD_BYTES:
                            raise ValueError("视频文件超过 500MB 下载限制")
                        output.write(chunk)
        if not total:
            raise ValueError("视频下载为空")
        return target

    async def export(self, db: AsyncSession, task: VideoProjectExportTask) -> VideoProjectExportTask:
        preflight = self.preflight()
        if not preflight["available"]:
            raise RuntimeError(preflight["error"])
        task.status = "running"
        task.error_detail = None
        task.started_at = datetime.utcnow()
        await db.commit()
        output_dir = self.EXPORT_ROOT / str(task.project_id) / str(task.id)
        cache_dir = self.CACHE_ROOT / str(task.id)
        output_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            videos, audios, subtitles, errors, duration_ms = await self._resolve_timeline(db, task.project_id)
            if errors:
                raise ValueError("；".join(errors))
            local_videos = [await self._download_video(item["url"], cache_dir, index) for index, item in enumerate(videos, start=1)]
            source_infos = [self.probe_media(path) for path in local_videos]
            timeline_end = 0
            current_end = 0
            for item, info in zip(videos, source_infos):
                requested = item.get("duration_ms") or info["duration_ms"]
                if requested > info["duration_ms"]:
                    raise ValueError(f"视频轨项目 {item['timeline_id']} 的裁切时长超过源视频时长")
                start = int(item.get("offset_ms") or 0)
                if start < current_end:
                    raise ValueError("视频轨存在重叠，请调整片段偏移或顺序")
                item["duration_ms"] = requested
                current_end = start + requested
                timeline_end = max(timeline_end, current_end)
            duration_ms = timeline_end
            subtitle_content = self._merge_subtitles(subtitles, duration_ms)
            subtitle_path = output_dir / "subtitles.srt"
            if subtitle_content:
                subtitle_path.write_text(subtitle_content, encoding="utf-8-sig")
            output_path = output_dir / "final.mp4"
            command = [str(self.ffmpeg_path), "-y"]
            for path in local_videos:
                command.extend(["-i", str(path)])
            for item in audios:
                command.extend(["-i", str(item["path"])])
            filters: list[str] = []
            video_parts: list[str] = []
            audio_parts: list[str] = []
            cursor_ms = 0
            for index, (item, info) in enumerate(zip(videos, source_infos)):
                start_ms = int(item.get("offset_ms") or 0)
                gap_ms = start_ms - cursor_ms
                if gap_ms:
                    gap = gap_ms / 1000
                    filters.append(f"color=c=black:s=1280x720:r=30:d={gap:.3f}[gapv{index}]")
                    filters.append(f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=duration={gap:.3f},asetpts=N/SR/TB[gapa{index}]")
                    video_parts.append(f"[gapv{index}]")
                    audio_parts.append(f"[gapa{index}]")
                clip_ms = int(item["duration_ms"])
                clip = clip_ms / 1000
                filters.append(f"[{index}:v]trim=duration={clip:.3f},setpts=PTS-STARTPTS,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1[clipv{index}]")
                video_parts.append(f"[clipv{index}]")
                if task.audio_strategy == "mute" or not info["has_audio"]:
                    filters.append(f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=duration={clip:.3f},asetpts=N/SR/TB[clipa{index}]")
                else:
                    filters.append(f"[{index}:a]atrim=duration={clip:.3f},asetpts=N/SR/TB[clipa{index}]")
                audio_parts.append(f"[clipa{index}]")
                cursor_ms = start_ms + clip_ms
            filters.append(f"{''.join(video_parts)}concat=n={len(video_parts)}:v=1:a=0[basev]")
            filters.append(f"{''.join(audio_parts)}concat=n={len(audio_parts)}:v=0:a=1[native]")
            video_output = "[basev]"
            if subtitle_content:
                escaped_path = str(subtitle_path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
                filters.append(f"[basev]subtitles='{escaped_path}'[vsub]")
                video_output = "[vsub]"
            audio_output = "[native]"
            if task.audio_strategy == "overlay" and audios:
                audio_labels = ["[native]"]
                for index, item in enumerate(audios, start=len(local_videos)):
                    delay = max(0, int(item["offset_ms"]))
                    filters.append(f"[{index}:a]adelay={delay}|{delay},atrim=duration={duration_ms / 1000:.3f}[extra{index}]")
                    audio_labels.append(f"[extra{index}]")
                filters.append(f"{''.join(audio_labels)}amix=inputs={len(audio_labels)}:duration=first:dropout_transition=0[a]")
                audio_output = "[a]"
            elif task.audio_strategy == "mute" and audios:
                audio_labels = []
                for index, item in enumerate(audios, start=len(local_videos)):
                    delay = max(0, int(item["offset_ms"]))
                    filters.append(f"[{index}:a]adelay={delay}|{delay},atrim=duration={duration_ms / 1000:.3f}[extra{index}]")
                    audio_labels.append(f"[extra{index}]")
                filters.append(f"{''.join(audio_labels)}amix=inputs={len(audio_labels)}:duration=first:dropout_transition=0[a]")
                audio_output = "[a]"
            command.extend(["-filter_complex", ";".join(filters), "-map", video_output, "-map", audio_output, "-c:a", "aac"])
            command.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output_path)])
            result = await asyncio.to_thread(
                subprocess.run,
                command,
                capture_output=True,
                text=True,
                timeout=self.EXPORT_TIMEOUT_SECONDS,
                shell=False,
                check=False,
            )
            if result.returncode != 0 or not output_path.is_file():
                raise RuntimeError((result.stderr or "FFmpeg 未生成成片").strip()[-2000:])
            actual_duration_ms = self.probe_duration(output_path)
            manifest = {
                "project_id": task.project_id,
                "export_task_id": task.id,
                "created_at": datetime.utcnow().isoformat(),
                "audio_strategy": task.audio_strategy or "preserve",
                "timeline_duration_ms": duration_ms,
                "actual_duration_ms": actual_duration_ms,
                "video_count": len(local_videos),
                "audio_count": len(audios),
                "subtitle_count": len(subtitles),
                "timeline_items": [{"timeline_id": item["timeline_id"], "offset_ms": item["offset_ms"], "duration_ms": item["duration_ms"]} for item in videos],
                "has_subtitles": bool(subtitle_content),
            }
            manifest_path = output_dir / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            task.status = "completed"
            task.output_path = str(output_path)
            task.subtitle_path = str(subtitle_path) if subtitle_content else None
            task.manifest_path = str(manifest_path)
            task.command_summary = f"ffmpeg concat {len(local_videos)} videos; subtitles={bool(subtitle_content)}"
            task.duration_ms = actual_duration_ms
            task.finished_at = datetime.utcnow()
        except Exception as exc:
            task.status = "failed"
            task.error_detail = str(exc)[:4000]
            task.finished_at = datetime.utcnow()
        await db.commit()
        return task


video_export_service = VideoExportService()
