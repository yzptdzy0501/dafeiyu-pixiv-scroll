/**
 * 「优秀作品」记录 —— 评论任务挑出来的好作品，刷图轮优先挑这些。
 *
 * 为什么单独一个文件：comments.jsonl 是流水（一件一条、会重复），
 * favorites.jsonl 是**精选**（同一件只留一条，分数可以被后续评论更新）。
 *
 * 一行一条 JSONL：
 *   { ts, date, id, kind, title, artist, url, rating, score, reason, comment }
 */
import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

/** 上限：超过就压实一次（保留最近 300 条去重后的记录） */
const COMPACT_AT = 600
const COMPACT_KEEP = 300

export function favoritesFile(home) {
  return join(home, 'favorites.jsonl')
}

/** 作品的公开网址（也是给人点开看的地址） */
export function workUrl(kind, id) {
  const k = String(kind || '').trim().toLowerCase()
  const n = Number(id)
  if (!Number.isFinite(n) || n <= 0) return ''
  if (k === 'novel') return `https://www.pixiv.net/novel/show.php?id=${n}`
  if (k === 'manga' || k === 'illust') return `https://www.pixiv.net/artworks/${n}`
  return `https://www.pixiv.net/artworks/${n}`
}

/** 作品 id 的归一化键（插画/漫画共用 artworks 命名空间） */
export function workKey(kind, id) {
  const k = String(kind || '').trim().toLowerCase() === 'novel' ? 'novel' : 'illust'
  return `${k}:${Number(id)}`
}

function line(row) {
  try { return JSON.parse(row) } catch { return null }
}

function readRaw(home) {
  const f = favoritesFile(home)
  if (!existsSync(f)) return []
  const out = []
  for (const t of readFileSync(f, 'utf8').split(/\r?\n/)) {
    if (!t.trim()) continue
    const r = line(t)
    if (r && Number(r.id) > 0) out.push(r)
  }
  return out
}

/**
 * 读精选列表：按 id 去重（后写的覆盖先写的），默认按分数从高到低、
 * 同分按时间从新到旧。
 */
export function readFavorites(home, { limit = 0, kind = '' } = {}) {
  const keep = String(kind || '').trim().toLowerCase()
  const byKey = new Map()
  for (const r of readRaw(home)) {
    const key = workKey(r.kind, r.id)
    if (keep && !key.startsWith(keep === 'novel' ? 'novel:' : 'illust:')) continue
    const prev = byKey.get(key)
    // 同一件出现在两次评论里：保留分数更高的那条；同分保留更新的
    if (!prev) { byKey.set(key, r); continue }
    const a = Number(r.score) || 0
    const b = Number(prev.score) || 0
    if (a > b || (a === b && String(r.ts || '') >= String(prev.ts || ''))) byKey.set(key, r)
  }
  const rows = [...byKey.values()].sort((x, y) => {
    const d = (Number(y.score) || 0) - (Number(x.score) || 0)
    if (d) return d
    return String(y.ts || '').localeCompare(String(x.ts || ''))
  })
  return limit > 0 ? rows.slice(0, limit) : rows
}

/** 已经记过的 id 集合（给刷图轮判重 / 提示用） */
export function favoriteKeys(home) {
  const set = new Set()
  for (const r of readFavorites(home)) set.add(workKey(r.kind, r.id))
  return set
}

/** 写一条精选（同一件重复写也没关系：读的时候按分数收敛） */
export function appendFavorite(home, entry = {}) {
  const id = Number(entry.id)
  if (!Number.isFinite(id) || id <= 0) return { ok: false, error: 'id 不合法' }
  const kind = String(entry.kind || 'illust').trim().toLowerCase() || 'illust'
  const score = Math.max(0, Math.min(5, Number(entry.score) || 0))
  const row = {
    ts: new Date().toISOString(),
    date: new Date().toISOString().slice(0, 10),
    id,
    kind,
    title: String(entry.title || '').trim().slice(0, 200),
    artist: String(entry.artist || '').trim().slice(0, 120),
    url: String(entry.url || '').trim() || workUrl(kind, id),
    rating: String(entry.rating || '').trim(),
    score,
    reason: String(entry.reason || '').trim().slice(0, 500),
    comment: String(entry.comment || '').trim().slice(0, 300),
  }

  mkdirSync(dirname(favoritesFile(home)), { recursive: true })
  try {
    appendFileSync(favoritesFile(home), JSON.stringify(row) + '\n', 'utf8')
  } catch (e) {
    return { ok: false, error: `写 favorites.jsonl 失败：${e?.message ?? e}` }
  }

  // 太长就压实：保留最近的去重结果，避免文件无限增长
  try {
    if (readRaw(home).length > COMPACT_AT) {
      const kept = readFavorites(home, { limit: COMPACT_KEEP })
      const f = favoritesFile(home)
      const tmp = `${f}.tmp`
      writeFileSync(tmp, kept.map((r) => JSON.stringify(r)).join('\n') + '\n', 'utf8')
      renameSync(tmp, f)
    }
  } catch { /* 压实失败不影响写入 */ }

  return { ok: true, row, file: favoritesFile(home) }
}
