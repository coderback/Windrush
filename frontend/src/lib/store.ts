"use client";

import { useEffect, useReducer } from "react";
import { authFetch } from "@/app/api";

/* A small shared cache for API reads, so the sidebar and the page asking for the same data make
   one request, and a write on one screen (a status change, a persona save) shows everywhere. */

type Listener = () => void;
interface Entry {
  data?: unknown;
  error?: string;
  promise?: Promise<unknown>;
  at?: number;
  listeners: Set<Listener>;
}

const entries = new Map<string, Entry>();

const keyOf = (url: string, init?: RequestInit) => `${init?.method ?? "GET"} ${url}`;

function entry(key: string): Entry {
  let e = entries.get(key);
  if (!e) {
    e = { listeners: new Set() };
    entries.set(key, e);
  }
  return e;
}

function notify(e: Entry) {
  e.listeners.forEach((l) => l());
}

/** fetch + JSON with the session token; throws the server's `detail` on a non-2xx reply. */
export async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await authFetch(url, init);
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {}
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export function load<T>(url: string, opts: { init?: RequestInit; force?: boolean } = {}): Promise<T> {
  const e = entry(keyOf(url, opts.init));
  if (!opts.force) {
    if (e.promise) return e.promise as Promise<T>;
    if (e.data !== undefined) return Promise.resolve(e.data as T);
  }
  const p = requestJson<T>(url, opts.init)
    .then((data) => {
      e.data = data;
      e.error = undefined;
      e.at = Date.now();
      return data;
    }, (err: Error) => {
      e.error = err.message || "Something went wrong";
      throw err;
    })
    .finally(() => {
      if (e.promise === p) e.promise = undefined;
      notify(e);
    });
  e.promise = p;
  notify(e);
  return p;
}

/** Replace cached data (after a successful write) and re-render everyone reading it. */
export function mutate<T>(url: string, update: T | ((prev: T | undefined) => T), init?: RequestInit) {
  const e = entry(keyOf(url, init));
  e.data = typeof update === "function" ? (update as (p: T | undefined) => T)(e.data as T | undefined) : update;
  e.error = undefined;
  e.at = Date.now();
  notify(e);
}

export function peek<T>(url: string, init?: RequestInit): T | undefined {
  return entries.get(keyOf(url, init))?.data as T | undefined;
}

/** Forget everything, e.g. on log out, so the next account never sees this one's data. */
export function clearStore() {
  entries.forEach((e) => {
    e.data = undefined;
    e.error = undefined;
    e.at = undefined;
  });
}

interface Options {
  init?: RequestInit;
  /** Re-fetch on mount when the cached copy is older than this. Infinity: never (costly calls). */
  staleMs?: number;
}

export function useResource<T>(url: string | null, { init, staleMs = 15_000 }: Options = {}) {
  const key = url ? keyOf(url, init) : null;
  const [, rerender] = useReducer((n: number) => n + 1, 0);

  useEffect(() => {
    if (!key || !url) return;
    const e = entry(key);
    e.listeners.add(rerender);
    const stale = e.at === undefined || Date.now() - e.at > staleMs;
    if (!e.promise && (e.data === undefined || stale)) load(url, { init, force: true }).catch(() => {});
    return () => { e.listeners.delete(rerender); };
    // `init` is a literal per call site; the key already captures its method.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const e = key ? entries.get(key) : undefined;
  return {
    data: e?.data as T | undefined,
    error: e?.data === undefined && !e?.promise ? e?.error : undefined,
    loading: !!key && e?.data === undefined && (!e?.error || !!e?.promise),
    refreshing: !!e?.promise,
    reload: () => (url ? load<T>(url, { init, force: true }) : Promise.reject(new Error("no url"))),
  };
}
