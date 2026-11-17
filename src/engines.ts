import { spawn } from 'node:child_process';
import { join } from 'node:path';
import type { Context } from '@deepseek-ai/cordis';
import { packageRoot, resourceRoot } from './catalog.js';
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

/** Switch file the MCP server consults per tool call (injected as LINKTOOL_ENGINE_SWITCHES). */
export const engineSwitchesFile = (): string => join(packageRoot, '.runtime', 'engine-switches.json');

/** Mirror the five live switches for the MCP server. Idempotent and cheap. */
export function writeEngineSwitches(overrides: Record<string, unknown>): void {
  const payload: Record<string, boolean> = {};
  for (const [key, field] of Object.entries(ENGINE_KEYS)) payload[key] = engineSwitch(overrides, field);
  atomicJson(engineSwitchesFile(), payload);
}

export interface EngineProbe { available: boolean; detail?: string }
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

  async function writeStatus(status: EngineStatus, patch: Record<string, unknown> = {}): Promise<void> {
    let settings: SettingsFace | undefined;
    try {
      settings = ctx.get('settings') as SettingsFace | undefined;
    } catch {
      settings = undefined;
    }
    if (!settings?.update) {
      ctx.logger?.warn?.('[linktool] settings service unavailable; engine probe result not recorded');
      return;
    }
    // Volatile-only patch: the loader commits into running refs and forwards
    // settings/document-updated, so open settings pages refresh their badges.
    await settings.update('linktool-plugin', { engineStatus: JSON.stringify(status), ...patch }, undefined);
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
        const start = stdout.indexOf('{');
        if (start >= 0) {
          try {
            const parsed = JSON.parse(stdout.slice(start)) as EngineStatus;
            if (parsed && typeof parsed.engines === 'object' && parsed.engines) return finish(undefined, parsed);
          } catch {
            // Fall through to the exit-code error below.
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

