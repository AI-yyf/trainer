import { useEffect, useMemo, useRef, useState } from "react";

import WaveSurfer from "wavesurfer.js";
import { workbenchTokens, type WorkbenchThemeName } from "../../../../../shared/src/tokens";

export interface AudioPreviewContentProps {
  src: string;
  title: string;
  className?: string;
  compact?: boolean;
}

interface AudioPalette {
  waveColor: string;
  progressColor: string;
  cursorColor: string;
}

type AudioPreviewStatus = "idle" | "loading" | "ready" | "error";

function resolveWorkbenchThemeName(): WorkbenchThemeName {
  const themeName = document.documentElement.dataset.theme;
  if (themeName === "light" || themeName === "dark") {
    return themeName;
  }
  return "dark";
}

function readAudioPalette(): AudioPalette {
  const theme = workbenchTokens.themes[resolveWorkbenchThemeName()];
  return {
    waveColor: theme.fgMuted,
    progressColor: theme.accent,
    cursorColor: theme.accent,
  };
}

function areAudioPalettesEqual(left: AudioPalette, right: AudioPalette): boolean {
  return (
    left.waveColor === right.waveColor &&
    left.progressColor === right.progressColor &&
    left.cursorColor === right.cursorColor
  );
}

function formatTime(seconds: number | undefined): string {
  if (!seconds || !Number.isFinite(seconds) || seconds < 0) {
    return "0:00";
  }
  const total = Math.floor(seconds);
  const minutes = Math.floor(total / 60);
  const remaining = total % 60;
  return `${minutes}:${remaining.toString().padStart(2, "0")}`;
}

function statusLabel(status: AudioPreviewStatus, error: string | null): string {
  if (status === "error") {
    return error ? `Audio preview failed: ${error}` : "Audio preview failed.";
  }
  if (status === "ready") {
    return "Waveform ready";
  }
  if (status === "loading") {
    return "Decoding waveform...";
  }
  return "Preparing waveform...";
}

export default function AudioPreviewContent({
  src,
  title,
  className,
  compact = false,
}: AudioPreviewContentProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const wavesurferRef = useRef<WaveSurfer | null>(null);
  const [status, setStatus] = useState<AudioPreviewStatus>("idle");
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [palette, setPalette] = useState<AudioPalette>(() => readAudioPalette());

  const statusText = useMemo(() => statusLabel(status, error), [status, error]);

  useEffect(() => {
    let frame = 0;
    const observer = new MutationObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const nextPalette = readAudioPalette();
        setPalette((current) => (areAudioPalettesEqual(current, nextPalette) ? current : nextPalette));
      });
    });

    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme", "style"],
    });

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return undefined;
    }

    let cancelled = false;
    setStatus("loading");
    setCurrentTime(0);
    setDuration(0);
    setIsPlaying(false);
    setError(null);

    const wavesurfer = WaveSurfer.create({
      container,
      height: compact ? 60 : 76,
      waveColor: palette.waveColor,
      progressColor: palette.progressColor,
      cursorColor: palette.cursorColor,
      cursorWidth: 2,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      normalize: true,
      minPxPerSec: 0,
      fillParent: true,
      interact: true,
      dragToSeek: true,
      hideScrollbar: true,
      mediaControls: false,
    });

    wavesurferRef.current = wavesurfer;

    const unsubReady = wavesurfer.on("ready", (readyDuration) => {
      if (cancelled) {
        return;
      }
      setDuration(readyDuration);
      setStatus("ready");
    });
    const unsubPlay = wavesurfer.on("play", () => {
      if (!cancelled) {
        setIsPlaying(true);
      }
    });
    const unsubPause = wavesurfer.on("pause", () => {
      if (!cancelled) {
        setIsPlaying(false);
      }
    });
    const unsubTimeUpdate = wavesurfer.on("timeupdate", (time) => {
      if (!cancelled) {
        setCurrentTime(time);
      }
    });
    const unsubFinish = wavesurfer.on("finish", () => {
      if (!cancelled) {
        setIsPlaying(false);
      }
    });
    const unsubError = wavesurfer.on("error", (waveError) => {
      if (cancelled) {
        return;
      }
      setStatus("error");
      setError(waveError?.message ?? "Unable to decode audio.");
    });

    wavesurfer
      .load(src)
      .catch((loadError: unknown) => {
        if (cancelled) {
          return;
        }
        setStatus("error");
        setError(loadError instanceof Error ? loadError.message : "Unable to load audio.");
      });

    return () => {
      cancelled = true;
      unsubReady();
      unsubPlay();
      unsubPause();
      unsubTimeUpdate();
      unsubFinish();
      unsubError();
      wavesurferRef.current = null;
      wavesurfer.destroy();
    };
  }, [compact, src]);

  useEffect(() => {
    const wavesurfer = wavesurferRef.current;
    if (!wavesurfer) {
      return;
    }
    wavesurfer.setOptions({
      waveColor: palette.waveColor,
      progressColor: palette.progressColor,
      cursorColor: palette.cursorColor,
    });
  }, [palette]);

  async function handleTogglePlayback(): Promise<void> {
    const wavesurfer = wavesurferRef.current;
    if (!wavesurfer || status === "error") {
      return;
    }
    try {
      await wavesurfer.playPause();
    } catch (toggleError) {
      setStatus("error");
      setError(toggleError instanceof Error ? toggleError.message : "Playback could not start.");
    }
  }

  return (
    <div className={`audio-preview ${compact ? "audio-preview--compact" : ""} ${className ?? ""}`.trim()}>
      <div
        className="audio-preview__waveform"
        ref={containerRef}
        aria-label={`${title} waveform`}
      />
      <div className="audio-preview__footer">
        <span>{title}</span>
        <span>{statusText}</span>
      </div>
      <div className="audio-preview__controls">
        <button
          type="button"
          className="audio-preview__play"
          onClick={() => void handleTogglePlayback()}
          disabled={status === "error" || status === "idle"}
        >
          {isPlaying ? "Pause" : "Play"}
        </button>
        <span className="audio-preview__time" aria-label="Current playback time">
          {formatTime(currentTime)}
        </span>
        <span className="audio-preview__time audio-preview__time--total" aria-label="Total duration">
          {formatTime(duration)}
        </span>
      </div>
      {status === "error" ? (
        <div className="audio-preview__fallback">
          <audio controls preload="metadata" src={src} />
        </div>
      ) : null}
    </div>
  );
}
