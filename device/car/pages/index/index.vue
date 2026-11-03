<template>
  <view class="page">
    <view class="status-bar"></view>

    <!-- 顶部状态条 -->
    <view class="topbar">
      <view class="status">
        <view class="dot" :class="connected ? 'ok' : 'off'"></view>
        <text class="status-text">{{ connected ? '已连接' : '未连接' }}</text>
        <text class="status-host">{{ host }}:{{ port }}</text>
      </view>
      <view class="topbar-right">
        <text class="frames" v-if="connected">{{ frames }} 帧</text>
        <view class="icon-btn" @click="toggleSettings">设置</view>
      </view>
    </view>

    <!-- 设置面板 -->
    <view class="settings" v-if="showSettings">
      <view class="field">
        <text class="field-label">控制台地址</text>
        <input class="field-input" v-model="hostInput" placeholder="192.168.4.1" />
      </view>
      <view class="field">
        <text class="field-label">端口</text>
        <input class="field-input" v-model="portInput" type="number" placeholder="81" />
      </view>
      <view class="settings-actions">
        <view class="btn-small ghost" @click="resetHost">恢复默认</view>
        <view class="btn-small primary" @click="saveSettings">保存并连接</view>
      </view>
      <text class="settings-tip">手机需先连上小车热点 RC-CAR（密码 12345678）</text>
    </view>

    <!-- 摇杆 + 功能键 -->
    <view class="main">
      <view class="stick-area">
        <car-joystick ref="stick" :disabled="!connected || estop" :dead="cfg.deadzone" @change="onStickChange" />
        <view class="readout">
          <view class="chip">
            <text class="chip-label">前后</text>
            <text class="chip-value">{{ signed(y) }}</text>
          </view>
          <view class="chip">
            <text class="chip-label">转向</text>
            <text class="chip-value">{{ signed(x) }}</text>
          </view>
        </view>
      </view>

      <view class="side">
        <view class="stop-btn" :class="{ locked: estop }" @click="toggleEstop">
          <text class="stop-text">{{ estop ? '解除' : '急停' }}</text>
        </view>
        <view class="side-btn" :class="connected ? 'warn' : 'primary'" @click="toggleConnect">
          <text class="side-btn-text">{{ connected ? '断开' : '连接' }}</text>
        </view>
        <view class="side-btn ghost" @click="toggleSettings">
          <text class="side-btn-text gray">设置</text>
        </view>
      </view>
    </view>

    <!-- 限速 -->
    <view class="bottombar">
      <view class="speed-head">
        <text class="speed-label">限速</text>
        <text class="speed-value">{{ speedPercent }}%</text>
      </view>
      <slider
        class="speed-slider"
        :value="speedPercent"
        :min="cfg.speedMin"
        :max="cfg.speedMax"
        :step="1"
        activeColor="#1D9E75"
        backgroundColor="#E3E6EA"
        :block-size="26"
        @changing="onSpeedChange"
        @change="onSpeedChange"
      />
      <text class="hint">{{ hint }}</text>
    </view>
  </view>
</template>

<script>
import carSocket from '@/common/car-socket.js'
import { CFG } from '@/common/config.js'

export default {
  data() {
    return {
      cfg: CFG,
      host: CFG.host,
      port: CFG.port,
      hostInput: CFG.host,
      portInput: String(CFG.port),

      connected: false,
      frames: 0,
      hint: '手机连上 RC-CAR 热点后点「连接」',

      rawX: 0,
      rawY: 0,
      x: 0,
      y: 0,

      speedPercent: CFG.speedDefault,
      estop: false,
      showSettings: false
    }
  },

  onLoad() {
    carSocket
      .on('open', () => {
        this.connected = true
        this.hint = '推摇杆控制，松手即停'
      })
      .on('close', () => {
        this.connected = false
        this.frames = 0
        this.hint = '连接已断开'
      })
      .on('error', () => {
        this.connected = false
        this.hint = '连接失败：确认手机已连上 RC-CAR 热点，地址是否正确'
      })
      .on('tick', (n) => {
        this.frames = n
      })

    // 进页面自动尝试连接一次，省掉手动点
    setTimeout(() => this.connect(), 400)
  },

  onShow() {
    // 遥控时锁屏很影响手感
    uni.setKeepScreenOn({ keepScreenOn: true })
    if (this.connected) carSocket.resume()
  },

  onHide() {
    // 退到后台必须停车，否则车会按最后一帧一直跑
    carSocket.pause()
    this.rawX = 0
    this.rawY = 0
    this.applyFrame()
  },

  onUnload() {
    carSocket.close()
  },

  methods: {
    signed(v) {
      const n = Number(v) || 0
      return (n >= 0 ? '+' : '') + n.toFixed(2)
    },

    onStickChange({ x, y }) {
      this.rawX = x
      this.rawY = y
      this.applyFrame()
    },

    // 限速在手机侧乘进去，ESP32 收到的是最终值，改限速不用改固件
    applyFrame() {
      const k = this.speedPercent / 100
      this.x = Number((this.rawX * k).toFixed(3))
      this.y = Number((this.rawY * k).toFixed(3))
      carSocket.setFrame({
        y: this.estop ? 0 : this.y,
        x: this.estop ? 0 : this.x
      })
    },

    onSpeedChange(e) {
      const v = e.detail.value
      if (v === this.speedPercent) return
      this.speedPercent = v
      this.applyFrame()
    },

    toggleEstop() {
      this.estop = !this.estop
      if (this.estop) {
        this.rawX = 0
        this.rawY = 0
        if (this.$refs.stick) this.$refs.stick.reset()
        carSocket.stopNow(false)
        this.hint = '已急停，点「解除」恢复控制'
      } else {
        this.hint = '推摇杆控制，松手即停'
      }
      this.applyFrame()
    },

    toggleConnect() {
      if (this.connected) {
        carSocket.close()
      } else {
        this.connect()
      }
    },

    connect() {
      this.hint = '正在连接…'
      carSocket.connect(this.host, this.port)
    },

    toggleSettings() {
      this.showSettings = !this.showSettings
      if (this.showSettings) {
        this.hostInput = this.host
        this.portInput = String(this.port)
      }
    },

    resetHost() {
      this.hostInput = CFG.host
      this.portInput = String(CFG.port)
    },

    saveSettings() {
      const h = (this.hostInput || '').trim()
      const p = parseInt(this.portInput, 10) || CFG.port
      if (!h) {
        uni.showToast({ title: '地址不能为空', icon: 'none' })
        return
      }
      this.host = h
      this.port = p
      this.showSettings = false
      carSocket.close(true)
      setTimeout(() => this.connect(), 120)
    }
  }
}
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  padding: 16rpx 28rpx 28rpx;
  background-color: #f4f5f7;
}

/* 自定义导航栏时用这个占位，避免内容顶到状态栏下面 */
.status-bar {
  height: var(--status-bar-height);
}

/* ---------- 顶部 ---------- */
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 80rpx;
}

.status {
  display: flex;
  align-items: center;
}

.dot {
  width: 16rpx;
  height: 16rpx;
  border-radius: 50%;
  margin-right: 12rpx;
}

.dot.ok {
  background-color: #1d9e75;
}

.dot.off {
  background-color: #c3cad3;
}

.status-text {
  font-size: 28rpx;
  color: #1a1d21;
  font-weight: 500;
}

.status-host {
  font-size: 24rpx;
  color: #6b7280;
  margin-left: 12rpx;
}

.topbar-right {
  display: flex;
  align-items: center;
}

.frames {
  font-size: 22rpx;
  color: #9aa1ab;
  margin-right: 16rpx;
}

.icon-btn {
  font-size: 26rpx;
  color: #6b7280;
  padding: 8rpx 20rpx;
  border-radius: 999rpx;
  background-color: #ffffff;
  border: 2rpx solid #e5e7eb;
}

/* ---------- 设置 ---------- */
.settings {
  margin-top: 16rpx;
  padding: 24rpx;
  background-color: #ffffff;
  border-radius: 24rpx;
  border: 2rpx solid #e5e7eb;
}

.field {
  display: flex;
  align-items: center;
  margin-bottom: 16rpx;
}

.field-label {
  width: 170rpx;
  font-size: 26rpx;
  color: #6b7280;
}

.field-input {
  flex: 1;
  height: 72rpx;
  padding: 0 20rpx;
  font-size: 28rpx;
  color: #1a1d21;
  background-color: #f4f5f7;
  border-radius: 14rpx;
}

.settings-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 8rpx;
}

.btn-small {
  font-size: 26rpx;
  padding: 14rpx 28rpx;
  border-radius: 999rpx;
  margin-left: 16rpx;
}

.btn-small.ghost {
  color: #6b7280;
  background-color: #f4f5f7;
}

.btn-small.primary {
  color: #ffffff;
  background-color: #1d9e75;
}

.settings-tip {
  display: block;
  margin-top: 16rpx;
  font-size: 22rpx;
  color: #9aa1ab;
}

/* ---------- 主区 ---------- */
.main {
  flex: 1;
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
}

.stick-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.readout {
  display: flex;
  margin-top: 24rpx;
}

.chip {
  display: flex;
  align-items: center;
  padding: 8rpx 20rpx;
  margin: 0 8rpx;
  background-color: #ffffff;
  border-radius: 999rpx;
  border: 2rpx solid #e5e7eb;
}

.chip-label {
  font-size: 22rpx;
  color: #9aa1ab;
  margin-right: 10rpx;
}

.chip-value {
  font-size: 24rpx;
  color: #1a1d21;
  font-weight: 500;
}

.side {
  width: 190rpx;
  display: flex;
  flex-direction: column;
  justify-content: center;
  margin-left: 20rpx;
}

.stop-btn {
  height: 210rpx;
  border-radius: 28rpx;
  background-color: #e24b4a;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 4rpx solid #e24b4a;
}

.stop-btn.locked {
  background-color: #ffffff;
}

.stop-text {
  font-size: 40rpx;
  font-weight: 500;
  color: #ffffff;
  letter-spacing: 2rpx;
}

.stop-btn.locked .stop-text {
  color: #a32d2d;
}

.side-btn {
  height: 92rpx;
  border-radius: 20rpx;
  margin-top: 20rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.side-btn.primary {
  background-color: #1d9e75;
}

.side-btn.warn {
  background-color: #ffffff;
  border: 2rpx solid #e5e7eb;
}

.side-btn.ghost {
  background-color: #ffffff;
  border: 2rpx solid #e5e7eb;
}

.side-btn-text {
  font-size: 28rpx;
  font-weight: 500;
  color: #ffffff;
}

.side-btn.warn .side-btn-text {
  color: #a32d2d;
}

.side-btn-text.gray {
  color: #6b7280;
}

/* ---------- 底部 ---------- */
.bottombar {
  padding-top: 8rpx;
}

.speed-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.speed-label {
  font-size: 24rpx;
  color: #6b7280;
}

.speed-value {
  font-size: 30rpx;
  font-weight: 500;
  color: #1d9e75;
}

.speed-slider {
  margin: 4rpx 0 0;
}

.hint {
  display: block;
  font-size: 22rpx;
  color: #9aa1ab;
  text-align: center;
  margin-top: 4rpx;
}
</style>
