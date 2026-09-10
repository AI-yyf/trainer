import { useMemo, useState } from "react";
import { endpointLatencyTier } from "../../../../../shared/src/providerStatus";
import type { ComposerLanguage } from "../../../../../shared/src/types";
import type { ProviderEndpointSpeedTestResult } from "../../lib/types";

interface ProviderEndpointSpeedTestProps {
  language: ComposerLanguage;
  baseUrl: string;
  results: ProviderEndpointSpeedTestResult[];
  pending: boolean;
  onRun: (urls: string[]) => void;
  onAdopt: (url: string) => void;
}

const MAX_ENDPOINTS = 8;

function tierColor(tier: "fast" | "ok" | "slow" | "failed"): string {
  switch (tier) {
    case "fast":
      return "var(--pass, var(--trainer-fallback-success))";
    case "ok":
      return "var(--warning, var(--trainer-fallback-warning))";
    default:
      return "var(--danger, var(--trainer-fallback-danger))";
  }
}

function copy(
  language: ComposerLanguage,
  key: "label" | "detail" | "addPlaceholder" | "run" | "running" | "adoptFastest" | "selected" | "collapse",
): string {
  const zh = {
    label: "⚡ 端点测速",
    detail: "对服务地址做一次轻量测速(不消耗模型额度)。点结果行直接采用该地址。",
    addPlaceholder: "再添加一个端点地址(可选)",
    run: "开始测速",
    running: "测速中…",
    adoptFastest: "采用最快端点",
    selected: "当前",
    collapse: "收起",
  };
  const en = {
    label: "⚡ Endpoint speed test",
    detail: "Lightweight latency test for service addresses (no model quota used). Click a row to adopt that address.",
    addPlaceholder: "Add another endpoint to test (optional)",
    run: "Run speed test",
    running: "Testing…",
    adoptFastest: "Use fastest",
    selected: "current",
    collapse: "Collapse",
  };
  return (language === "zh-CN" ? zh : en)[key];
}

export function ProviderEndpointSpeedTest({
  language,
  baseUrl,
  results,
  pending,
  onRun,
  onAdopt,
}: ProviderEndpointSpeedTestProps) {
  const [open, setOpen] = useState(false);
  const [extraUrlDraft, setExtraUrlDraft] = useState("");
  const [extraUrls, setExtraUrls] = useState<string[]>([]);

  const endpoints = useMemo(() => {
    const list: string[] = [];
    for (const candidate of [baseUrl, ...extraUrls]) {
      const normalized = candidate.trim().replace(/\/+$/, "");
      if (normalized && !list.includes(normalized)) {
        list.push(normalized);
      }
    }
    return list;
  }, [baseUrl, extraUrls]);

  const fastest = useMemo(() => {
    const reachable = results.filter((item) => item.latencyMs !== null);
    if (reachable.length === 0) {
      return null;
    }
    return reachable.reduce((best, item) =>
      (item.latencyMs ?? Infinity) < (best.latencyMs ?? Infinity) ? item : best,
    );
  }, [results]);

  const addExtra = () => {
    const normalized = extraUrlDraft.trim().replace(/\/+$/, "");
    if (
      !normalized ||
      extraUrls.includes(normalized) ||
      normalized === baseUrl.trim() ||
      endpoints.length >= MAX_ENDPOINTS
    ) {
      setExtraUrlDraft("");
      return;
    }
    setExtraUrls((current) => [...current, normalized]);
    setExtraUrlDraft("");
  };

  if (!open) {
    return (
      <div className="settings-endpoint-speed">
        <button type="button" className="toolbar-button" onClick={() => setOpen(true)}>
          {copy(language, "label")}
        </button>
      </div>
    );
  }

  return (
    <div className="settings-field settings-endpoint-speed">
      <span>
        <button type="button" className="toolbar-button" onClick={() => setOpen(false)}>
          {copy(language, "collapse")}
        </button>
        {copy(language, "label")}
      </span>
      <p className="settings-sheet__note settings-sheet__note--compact">{copy(language, "detail")}</p>
      <div className="settings-endpoint-speed__rows">
        {results.map((item) => {
          const tier = endpointLatencyTier(item.latencyMs);
          const selected = item.url === baseUrl;
          return (
            <button
              key={item.url}
              type="button"
              className="settings-endpoint-speed__row"
              title={item.error ?? `${item.latencyMs ?? "?"}ms · HTTP ${item.status ?? "-"}`}
              onClick={() => onAdopt(item.url)}
            >
              <span aria-hidden className="settings-endpoint-speed__dot" style={{ color: tierColor(tier) }}>
                ●
              </span>
              <span className="settings-endpoint-speed__url">{item.url}</span>
              <span className="settings-endpoint-speed__latency">
                {item.latencyMs !== null ? `${item.latencyMs}ms` : (item.error ?? "—")}
              </span>
              {selected ? <span className="settings-endpoint-speed__tag">{copy(language, "selected")}</span> : null}
            </button>
          );
        })}
      </div>
      <div className="settings-endpoint-speed__actions">
        <input
          type="text"
          value={extraUrlDraft}
          placeholder={copy(language, "addPlaceholder")}
          onChange={(event) => setExtraUrlDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              addExtra();
            }
          }}
        />
        <button type="button" className="toolbar-button" onClick={addExtra}>
          +
        </button>
      </div>
      <div className="settings-endpoint-speed__actions">
        <button
          type="button"
          className="toolbar-button"
          disabled={pending || endpoints.length === 0}
          onClick={() => onRun(endpoints)}
        >
          {pending ? copy(language, "running") : copy(language, "run")}
        </button>
        {fastest && fastest.url !== baseUrl ? (
          <button type="button" className="toolbar-button" onClick={() => onAdopt(fastest.url)}>
            {copy(language, "adoptFastest")} ({fastest.latencyMs}ms)
          </button>
        ) : null}
      </div>
    </div>
  );
}
