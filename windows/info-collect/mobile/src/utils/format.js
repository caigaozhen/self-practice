/**
 * 纯函数：时长格式化、日期推算、数据聚合。
 *
 * 这个文件不依赖 uni 的任何 API，所以可以在 Node 里直接跑测试
 * （见 dev/test_format.mjs）。改完记得执行一次。
 */

/** 秒 → 「45 秒 / 2 分 / 1 小时 30 分」 */
export function fmtDuration(sec) {
  const s = Math.max(0, Math.round(Number(sec) || 0))
  if (s < 60) return s + ' 秒'
  const m = Math.round(s / 60)
  if (m < 60) return m + ' 分'
  const h = Math.floor(m / 60)
  const rest = m % 60
  return rest ? h + ' 小时 ' + rest + ' 分' : h + ' 小时'
}

const pad = (n) => String(n).padStart(2, '0')

/** Date → 'YYYY-MM-DD'（本地时区，不用 toISOString，那个是 UTC） */
export function toDayStr(d) {
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
}

export function todayStr() {
  return toDayStr(new Date())
}

/** 'YYYY-MM-DD' 加减天数，返回同样格式。跨月跨年由 Date 自己处理 */
export function shiftDay(day, delta) {
  const p = String(day).split('-').map(Number)
  const d = new Date(p[0], p[1] - 1, p[2])
  d.setDate(d.getDate() + delta)
  return toDayStr(d)
}

/** 'YYYY-MM-DD' → '10月30日 周五' */
export function fmtDay(day) {
  const p = String(day).split('-').map(Number)
  const d = new Date(p[0], p[1] - 1, p[2])
  const wd = '日一二三四五六'[d.getDay()]
  return p[1] + '月' + p[2] + '日 周' + wd
}

/** 总秒数 */
export function totalOf(rows) {
  return (rows || []).reduce((s, r) => s + (Number(r.seconds) || 0), 0)
}

/**
 * 按字段聚合，返回 [{name, seconds, pct}]，按秒数降序。
 * pct 保留一位小数，合计约等于 100。
 */
export function aggregate(rows, key) {
  const total = totalOf(rows)
  const map = new Map()
  for (const r of rows || []) {
    const name = r[key] || '未知'
    map.set(name, (map.get(name) || 0) + (Number(r.seconds) || 0))
  }
  const list = []
  for (const [name, seconds] of map) {
    list.push({ name, seconds, pct: total ? Math.round((seconds / total) * 1000) / 10 : 0 })
  }
  list.sort((a, b) => b.seconds - a.seconds)
  return list
}

/** 设备清单，按时长降序 */
export function deviceList(rows) {
  const map = new Map()
  for (const r of rows || []) {
    const id = r.device_id || ''
    const cur = map.get(id) || { id, name: r.device_name || id || '未知设备', seconds: 0, segments: 0 }
    cur.seconds += Number(r.seconds) || 0
    cur.segments += Number(r.segments) || 0
    if (r.device_name) cur.name = r.device_name
    map.set(id, cur)
  }
  return [...map.values()].sort((a, b) => b.seconds - a.seconds)
}

/** 按设备过滤，id 为空返回全部 */
export function filterDevice(rows, id) {
  if (!id) return rows || []
  return (rows || []).filter((r) => r.device_id === id)
}
