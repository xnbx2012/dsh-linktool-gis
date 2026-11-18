import { spawn } from 'node:child_process';
import { join } from 'node:path';
import type { Context } from '@deepseek-ai/cordis';
import { guardFields, packageRoot, resourceRoot } from './catalog.js';
import { childEnvironment } from './paths.js';
import { atomicJson } from './tools.js';

/**
 * Five-engine switch surface shared by the settings page, the MCP server, and
 * the engine probes.
 *
 * The settings page writes flat volatile `engine*` config fields; the loader
 * commits them into the running fiber's refs (no plugin restart). The manager
 * mirrors them into `<packageRoot>/.runtime/engine-switches.json`, which the
 * MCP server re-reads on every `execute_gis_tool` call — so flips apply to
 * live sessions immediately.
 */
export const ENGINE_FIELDS = ['engineArcgis', 'engineQgis', 'engineWhitebox', 'engineGdal', 'engineInner'] as const;
export type EngineField = (typeof ENGINE_FIELDS)[number];

/** MCP-server engine key ↔ flat config field. */
export const ENGINE_KEYS: Record<string, EngineField> = {
  arcpy: 'engineArcgis', qgis: 'engineQgis', wbt: 'engineWhitebox', gdal: 'engineGdal', inner: 'engineInner',
};

/** Shipped defaults: ArcGIS Pro off, the other four on (availability auto-off overrides these on first probe). */
export const ENGINE_DEFAULTS: Record<EngineField, boolean> = {
  engineArcgis: false, engineQgis: true, engineWhitebox: true, engineGdal: true, engineInner: true,
};

/** Read one switch honoring the live volatile ref object written by the settings page. */
export function engineSwitch(overrides: Record<string, unknown>, field: EngineField): boolean {
  const value = overrides[field];
  if (value && typeof value === 'object' && typeof (value as { get?: unknown }).get === 'function') {
    const resolved = (value as { get(): unknown }).get();
    if (typeof resolved === 'boolean') return resolved;
  }
  if (typeof value === 'boolean') return value;
  return ENGINE_DEFAULTS[field];
}

/** 输出路径严格限制（pathRestrict）实时值：镜像给 MCP 进程的路径底线。
 *  Shipped default is off（switchesOf），关 = 输入/输出路径不作任何限制。 */
export function pathRestrictSwitch(overrides: Record<string, unknown>): boolean {
  const value = overrides[guardFields.pathRestrict];
  if (value && typeof value === 'object' && typeof (value as { get?: unknown }).get === 'function') {
    const resolved = (value as { get(): unknown }).get();
    if (typeof resolved === 'boolean') return resolved;
  }
  if (typeof value === 'boolean') return value;
  return false;
}

/** Switch file the MCP server consults per tool call (injected as LINKTOOL_ENGINE_SWITCHES). */
export const engineSwitchesFile = (): string => join(packageRoot, '.runtime', 'engine-switches.json');

/** Mirror the five live switches + the path-restriction switch for the MCP server. Idempotent and cheap. */
export function writeEngineSwitches(overrides: Record<string, unknown>): void {
  const payload: Record<string, boolean> = {};
  for (const [key, field] of Object.entries(ENGINE_KEYS)) payload[key] = engineSwitch(overrides, field);
  payload.pathRestrict = pathRestrictSwitch(overrides);
  atomicJson(engineSwitchesFile(), payload);
}

export interface EngineProbe { available: boolean; detail?: string; version?: string }
export interface EngineStatus { engines: Record<string, EngineProbe>; checkedAt?: string }

/** Parse the current detection snapshot from the live volatile config ref. */
export function engineStatus(overrides: Record<string, unknown>): EngineStatus | undefined {
  const raw = overrides.engineStatus;
  const value = raw && typeof raw === 'object' && typeof (raw as { get?: unknown }).get === 'function'
    ? (raw as { get(): unknown }).get()
    : raw;
  if (typeof value !== 'string' || !value.trim()) return undefined;
  try {
    const parsed = JSON.parse(value) as EngineStatus;
    if (parsed && typeof parsed.engines === 'object' && parsed.engines) return parsed;
  } catch {
    // Corrupt snapshot is treated as "never probed".
  }
  return undefined;
}

interface SettingsFace {
  update(ns: string, patch: object, expectedRevision?: number): Promise<void>;
}

/**
 * Host-side engine lifecycle: mirrors switches, runs availability probes on
 * demand, and folds results back into the settings page through the same
 * volatile config fields the page reads.
 *
 * First probe (empty `engineStatus`) additionally turns every unavailable
 * engine's switch off — the shipped-defaults-then-auto-off contract. Later
 * probes only refresh status; the user's toggles always win afterwards.
 */
export function createEngineManager(ctx: Context, overrides: Record<string, unknown>) {
  let child: ReturnType<typeof spawn> | undefined;
  let disposed = false;
  let running = false;
  let queued = false;
  const scriptDir = join(resourceRoot, 'scripts', 'arcgis-mcp-server');

  /**
   * Persist a probe snapshot through the host settings service.
   *
   * The write races with the loader's startup reconcile window: on freshly
   * mounted profiles (and notably on dsh ≥0.2.2 / cordis 4.1) an early write
   * fails with "cannot get required service in inactive context" — and a
   * failure in that window can leave the config service unavailable for the
   * rest of the process, so the page would stay 探测中 forever. Probe results
   * are therefore never dropped: resolve + write are retried with backoff
   * until the host settles, and only then reported as a warning.
   */
  async function writeStatus(status: EngineStatus, patch: Record<string, unknown> = {}): Promise<void> {
    const payload = { engineStatus: JSON.stringify(status), ...patch };
    const attempts = 12;
    const retryDelayMs = 5_000;
    let lastError: unknown;
    for (let attempt = 1; attempt <= attempts; attempt++) {
      let settings: SettingsFace | undefined;
      try {
        settings = ctx.get('settings') as SettingsFace | undefined;
      } catch {
        settings = undefined;
      }
      if (!settings?.update) {
        lastError = new Error('settings service unavailable');
      } else {
        try {
          // Volatile-only patch: the loader commits into running refs and
          // forwards settings/document-updated, so open settings pages
          // refresh their badges.
          await settings.update('linktool-plugin', payload, undefined);
          return;
        } catch (error) {
          lastError = error;
        }
      }
      if (attempt < attempts) await new Promise(resolve => setTimeout(resolve, retryDelayMs));
    }
    ctx.logger?.warn?.(`[linktool] engine probe result could not be recorded after ${attempts} attempts: ${(lastError as Error)?.message ?? lastError}`);
  }

  function spawnDetect(): Promise<EngineStatus> {
    return new Promise((resolve, reject) => {
      let stdout = '';
      let stderr = '';
      let settled = false;
      const proc = spawn('uv', ['run', '--project', scriptDir, 'python', join(scriptDir, 'detect_engines.py')], {
        cwd: scriptDir,
        env: {
          ...childEnvironment(process.cwd()),
          // Share the MCP server's uv env so probes see the exact dependency set.
          UV_PROJECT_ENVIRONMENT: join(packageRoot, '.runtime', 'mcp', 'arcgis-mcp-server'),
          LINKTOOL_ENGINE_SWITCHES: engineSwitchesFile(),
        },
        windowsHide: true,
      });
      child = proc;
      const finish = (error: Error | undefined, value?: EngineStatus) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        child = undefined;
        if (error) reject(error);
        else resolve(value!);
      };
      const timer = setTimeout(() => {
        proc.kill();
        finish(new Error('engine probe timed out after 900s (first WhiteboxTools download can take long; retry)'));
      }, 900_000);
      proc.stdout.on('data', (chunk: Buffer) => { stdout += chunk.toString('utf8'); });
      proc.stderr.on('data', (chunk: Buffer) => { stderr += chunk.toString('utf8'); });
      proc.on('error', error => finish(error));
      proc.on('exit', code => {
        // detect_engines.py prints one JSON line, but uv/Python banners may
        // precede it and warnings may trail it. Try each '{' as a document
        // start (full tail first, then up to the last '}') before giving up.
        const lastBrace = stdout.lastIndexOf('}');
        for (let start = stdout.indexOf('{'); start >= 0; start = stdout.indexOf('{', start + 1)) {
          for (const end of [stdout.length, lastBrace + 1]) {
            if (end <= start) continue;
            try {
              const parsed = JSON.parse(stdout.slice(start, end)) as EngineStatus;
              if (parsed && typeof parsed.engines === 'object' && parsed.engines) return finish(undefined, parsed);
            } catch {
              // Malformed candidate; try the next one.
            }
          }
        }
        finish(new Error(`detect_engines.py exited with ${code}: ${(stderr || stdout).slice(-400)}`));
      });
    });
  }

  async function detect(): Promise<void> {
    if (disposed) return;
    if (running) { queued = true; return; }
    running = true;
    try {
      const status = await spawnDetect();
      const patch: Record<string, unknown> = {};
      if (!engineStatus(overrides)) {
        // First probe on this install: unavailable engines switch off automatically.
        for (const [key, field] of Object.entries(ENGINE_KEYS)) {
          const probe = status.engines[key];
          if (probe && !probe.available) patch[field] = false;
        }
      }
      // Commit status (+ any first-run switch flips) into the live refs first,
      // then mirror the now-current switches for the MCP server.
      await writeStatus(status, patch);
      writeEngineSwitches(overrides);
    } catch (error) {
      ctx.logger?.warn?.(`[linktool] engine probe failed: ${(error as Error)?.message ?? error}`);
    } finally {
      running = false;
      if (queued && !disposed) {
        queued = false;
        void detect();
      }
    }
  }

  return {
    /** Launch one probe (single-flight; a request during a run re-runs once it settles). */
    requestDetection(): void {
      void detect();
    },
    /** Kill an in-flight probe; the detached uv child finishes its env sync harmlessly. */
    dispose(): void {
      disposed = true;
      child?.kill();
      child = undefined;
    },
  };
}

