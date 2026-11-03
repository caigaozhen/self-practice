import { CFG } from './config.js'

/**
 * WebSocket 客户端
 *
 * 为什么是 WebSocket 而不是 UDP：
 *   uniapp 的 H5 运行在浏览器里，没有 UDP 能力；App 端 plus.net.Socket 只支持 TCP；
 *   只有微信小程序有 wx.createUDPSocket。要让 H5 / App / 小程序三端共用一套代码，
 *   WebSocket 是唯一选择。ESP32 那边跑一个最小的 WS 服务端即可。
 *
 * 协议（一条指令一帧文本）：
 *   {"y":0.62,"x":-0.15}
 *   y = 前后  1 全速前进  -1 全速后退
 *   x = 左右  1 全速右转  -1 全速左转
 *   发送前已经把限速乘进去了，ESP32 收到直接做差速映射。
 */
class CarSocket {
  constructor() {
    this.task = null
    this.connected = false
    this.frame = { y: 0, x: 0 }
    this.timer = null
    this.frames = 0
    this.intentionalClose = false
    this.handlers = {}
  }

  on(evt, fn) {
    if (!this.handlers[evt]) this.handlers[evt] = []
    this.handlers[evt].push(fn)
    return this
  }

  emit(evt, payload) {
    const list = this.handlers[evt]
    if (!list) return
    list.forEach((fn) => {
      try {
        fn(payload)
      } catch (e) {
        console.error('[carSocket] handler error', e)
      }
    })
  }

  get url() {
    return `ws://${this.host || CFG.host}:${this.port || CFG.port}`
  }

  connect(host, port) {
    this.host = host || CFG.host
    this.port = port || CFG.port
    this.close(true)

    this.intentionalClose = false
    const url = this.url

    const task = uni.connectSocket({
      url,
      complete: () => {}
    })

    if (!task) {
      this.emit('error', { errMsg: 'connectSocket 没有返回 SocketTask，检查运行端是否支持 H5/App/小程序' })
      return
    }
    this.task = task

    task.onOpen(() => {
      this.connected = true
      this.frames = 0
      this.startLoop()
      this.emit('open', url)
    })

    task.onMessage((res) => {
      this.emit('message', res.data)
    })

    task.onClose((res) => {
      this.stopLoop()
      this.connected = false
      if (!this.intentionalClose) this.emit('close', res)
    })

    task.onError((err) => {
      this.stopLoop()
      this.connected = false
      if (!this.intentionalClose) this.emit('error', err)
    })
  }

  setFrame(next) {
    this.frame.y = this.round(next.y || 0)
    this.frame.x = this.round(next.x || 0)
  }

  round(v) {
    const f = Math.pow(10, CFG.decimals)
    return Math.round(v * f) / f
  }

  startLoop() {
    this.stopLoop()
    this.timer = setInterval(() => this.tick(), Math.round(1000 / CFG.sendHz))
  }

  stopLoop() {
    if (this.timer) {
      clearInterval(this.timer)
      this.timer = null
    }
  }

  tick() {
    if (!this.connected || !this.task) return
    const data = JSON.stringify(this.frame)
    this.task.send({
      data,
      fail: () => {
        // 单帧发送失败不用管，下一帧 33ms 后就补上了
      }
    })
    this.frames++
    this.emit('tick', this.frames)
  }

  /** 立刻发一帧停车指令，然后按需断开 */
  stopNow(andClose = false) {
    this.setFrame({ y: 0, x: 0 })
    if (this.connected && this.task) {
      this.task.send({ data: JSON.stringify({ y: 0, x: 0 }) })
    }
    if (andClose) {
      setTimeout(() => this.close(), 60)
    }
  }

  pause() {
    this.stopNow(false)
    this.stopLoop()
  }

  resume() {
    this.setFrame({ y: 0, x: 0 })
    if (this.connected) this.startLoop()
  }

  close(silent = false) {
    this.intentionalClose = true
    this.stopLoop()
    if (this.task) {
      try {
        this.task.close({})
      } catch (e) {
        // 已经关了，忽略
      }
    }
    this.task = null
    this.connected = false
    if (!silent) this.emit('close', { reason: 'manual' })
  }
}

export const carSocket = new CarSocket()
export default carSocket
