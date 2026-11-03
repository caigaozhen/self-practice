/**
 * Supabase 访问层（uni-app 版）。
 *
 * 和网页版的三处差别：
 *   1. fetch → uni.request（App 端没有 fetch）
 *   2. localStorage → uni.getStorageSync
 *   3. 多了 token 过期自动续期（App 常驻后台很久，醒来时 token 早过期了）
 *
 * 认证模型：邮箱密码登录拿 access_token，之后所有查询带 Bearer。
 * 桌面端只写不读，手机端登录后只读——权限由 Supabase 的 RLS 决定，这里只是客户端。
 */

const LS_KEY = 'infocollect_cfg'

// ---------------------------------------------------------------- 配置存取

export function getCfg() {
  try {
    return uni.getStorageSync(LS_KEY) || null
  } catch (e) {
    return null
  }
}

export function saveCfg(cfg) {
  try {
    uni.setStorageSync(LS_KEY, cfg)
  } catch (e) {
    /* 存储满了也不能让界面崩 */
  }
}

export function clearCfg() {
  try {
    uni.removeStorageSync(LS_KEY)
  } catch (e) {}
  S = { cfg: null, access: '', refresh: '', exp: 0 }
}

export function isConfigured() {
  const c = getCfg()
  return !!(c && c.url && c.key && c.email && c.password)
}

// ---------------------------------------------------------------- 会话状态

let S = { cfg: null, access: '', refresh: '', exp: 0 }

export function initSession() {
  const c = getCfg()
  S = {
    cfg: c,
    access: (c && c.access) || '',
    refresh: (c && c.refresh) || '',
    exp: (c && c.exp) || 0
  }
  return c
}

function persist() {
  if (!S.cfg) return
  S.cfg.access = S.access
  S.cfg.refresh = S.refresh
  S.cfg.exp = S.exp
  saveCfg(S.cfg)
}

// ---------------------------------------------------------------- 底层请求

function base(url) {
  let u = String(url || '').trim().replace(/\/+$/, '')
  if (u && !/^https?:\/\//i.test(u)) u = 'https://' + u
  return u
}

function request(opts) {
  return new Promise((resolve, reject) => {
    uni.request({
      timeout: 15000,
      ...opts,
      success: resolve,
      fail: (e) => {
        const msg = (e && e.errMsg) || '网络请求失败'
        reject(new Error(msg.indexOf('timeout') >= 0 ? '请求超时，检查网络或项目地址' : msg))
      }
    })
  })
}

/** 从 Supabase 的错误体里挖出人能看懂的一句话 */
function errText(res) {
  const d = res && res.data
  if (d && typeof d === 'object') {
    return d.error_description || d.msg || d.message || d.hint || 'HTTP ' + res.statusCode
  }
  if (typeof d === 'string' && d) return d.slice(0, 160)
  return 'HTTP ' + (res && res.statusCode)
}

// ---------------------------------------------------------------- 登录

async function doLogin(cfg) {
  const c = cfg || S.cfg
  if (!c) throw new Error('还没有配置连接')
  const res = await request({
    url: base(c.url) + '/auth/v1/token?grant_type=password',
    method: 'POST',
    header: { 'Content-Type': 'application/json', apikey: c.key },
    data: { email: c.email, password: c.password }
  })
  if (res.statusCode !== 200 || !res.data || !res.data.access_token) {
    throw new Error(errText(res))
  }
  S.cfg = c
  S.access = res.data.access_token
  S.refresh = res.data.refresh_token || ''
  // 提前 60 秒判定过期，避免"刚好卡在边界"的请求失败
  S.exp = Date.now() + (Number(res.data.expires_in) || 3600) * 1000 - 60000
  persist()
}

async function doRefresh() {
  if (!S.refresh || !S.cfg) throw new Error('登录已过期')
  const res = await request({
    url: base(S.cfg.url) + '/auth/v1/token?grant_type=refresh_token',
    method: 'POST',
    header: { 'Content-Type': 'application/json', apikey: S.cfg.key },
    data: { refresh_token: S.refresh }
  })
  if (res.statusCode !== 200 || !res.data || !res.data.access_token) {
    throw new Error('登录已过期')
  }
  S.access = res.data.access_token
  S.refresh = res.data.refresh_token || S.refresh
  S.exp = Date.now() + (Number(res.data.expires_in) || 3600) * 1000 - 60000
  persist()
}

async function ensureToken() {
  if (!S.cfg) initSession()
  if (!S.cfg) throw new Error('还没有配置连接')
  if (S.access && Date.now() < S.exp) return
  if (S.refresh) {
    try {
      await doRefresh()
      return
    } catch (e) {
      /* 续期失败就重新登录 */
    }
  }
  await doLogin()
}

// ---------------------------------------------------------------- 查询

async function restGet(path, params, retried) {
  await ensureToken()
  const res = await request({
    url: base(S.cfg.url) + '/rest/v1/' + path,
    method: 'GET',
    data: params || {},
    header: { apikey: S.cfg.key, Authorization: 'Bearer ' + S.access }
  })
  if (res.statusCode === 401 && !retried) {
    // token 被服务端判过期（本地时间不准时会这样），强制续一次再试
    S.exp = 0
    return restGet(path, params, true)
  }
  if (res.statusCode !== 200) throw new Error(errText(res))
  return Array.isArray(res.data) ? res.data : []
}

/** 某天的聚合数据：[{day, device_id, device_name, app, category, seconds, segments}] */
export function fetchDay(day) {
  return restGet('v_daily', {
    select: 'day,device_id,device_name,app,category,seconds,segments',
    day: 'eq.' + day,
    order: 'seconds.desc'
  })
}

/** 设备清单 */
export function fetchDevices() {
  return restGet('v_devices', { select: 'device_id,device_name,last_seen' })
}

// ---------------------------------------------------------------- 首次配置 / 自检

/**
 * 用给定配置试一次完整链路：登录 → 查今天的聚合视图。
 * 成功返回 { devices, rows, today }，失败抛异常。
 */
export async function testConnection(cfg) {
  S = { cfg: null, access: '', refresh: '', exp: 0 }
  await doLogin(cfg)
  const today = new Date()
  const p = (n) => String(n).padStart(2, '0')
  const day = today.getFullYear() + '-' + p(today.getMonth() + 1) + '-' + p(today.getDate())
  const rows = await restGet('v_daily', {
    select: 'day,device_id,device_name,app,category,seconds,segments',
    day: 'eq.' + day
  })
  return { rows, today: day }
}
