<template>
  <view class="page">
    <!-- 顶部：日期 + 总时长 + 设备筛选 -->
    <view class="card head">
      <view class="daterow">
        <view class="navbtn" @tap="shift(-1)"><text class="chev">‹</text></view>
        <view class="datebox">
          <text class="day">{{ dayLabel }}</text>
          <text class="hint" v-if="isToday">今天</text>
          <text class="hint tap" v-else @tap="goToday">点这里回到今天</text>
        </view>
        <view class="navbtn" :class="{ off: isToday }" @tap="shift(1)">
          <text class="chev">›</text>
        </view>
      </view>

      <view class="total">
        <text class="num">{{ totalText }}</text>
        <text class="sub">{{ rows.length ? rows.length + ' 段记录' : '暂无记录' }}</text>
      </view>

      <scroll-view class="chips" scroll-x :show-scrollbar="false">
        <view class="chip" :class="{ on: !device }" @tap="pickDevice('')">全部</view>
        <view
          class="chip"
          :class="{ on: device === d.id }"
          v-for="d in devices"
          :key="d.id"
          @tap="pickDevice(d.id)"
        >
          {{ d.name }}
        </view>
      </scroll-view>
    </view>

    <!-- 三个页签 -->
    <view class="tabs">
      <view class="tab" :class="{ on: tab === 'category' }" @tap="tab = 'category'">分类</view>
      <view class="tab" :class="{ on: tab === 'app' }" @tap="tab = 'app'">程序</view>
      <view class="tab" :class="{ on: tab === 'device' }" @tap="tab = 'device'">设备</view>
    </view>

    <!-- 列表 -->
    <view class="card list">
      <view class="loading" v-if="loading">加载中…</view>
      <view class="empty" v-else-if="!list.length">
        <text>{{ err || '这一天没有采集到数据' }}</text>
        <text class="empty-sub" v-if="!err">换一天看看，或确认电脑端在运行</text>
      </view>
      <view class="row" v-for="(r, i) in list" :key="i">
        <view class="r1">
          <text class="name">{{ r.name }}</text>
          <text class="dur">{{ dur(r.seconds) }}</text>
        </view>
        <view class="bar">
          <view class="fill" :style="{ width: barWidth(r) }"></view>
        </view>
        <text class="pct">{{ r.pct }}%</text>
      </view>
    </view>

    <view class="foot">
      <text class="foot-btn" @tap="goSetup">连接设置</text>
      <text class="foot-sep">·</text>
      <text class="foot-btn" @tap="reload">刷新</text>
    </view>
  </view>
</template>

<script>
import { fmtDuration, fmtDay, todayStr, shiftDay, totalOf, aggregate, deviceList, filterDevice } from '../../utils/format.js'
import { isConfigured, initSession, fetchDay, fetchDevices } from '../../utils/api.js'

export default {
  data() {
    return {
      day: todayStr(),
      rows: [],
      devices: [],
      device: '',
      tab: 'category',
      loading: false,
      err: ''
    }
  },

  computed: {
    dayLabel() {
      return fmtDay(this.day)
    },
    isToday() {
      return this.day === todayStr()
    },
    totalText() {
      return fmtDuration(totalOf(this.scoped()))
    },
    list() {
      const rows = this.scoped()
      if (!rows.length) return []
      if (this.tab === 'category') return aggregate(rows, 'category')
      if (this.tab === 'app') return aggregate(rows, 'app')
      return aggregate(rows, 'device_name')
    }
  },

  onShow() {
    if (!isConfigured()) {
      uni.redirectTo({ url: '/pages/setup/setup' })
      return
    }
    initSession()
    this.load()
  },

  onPullDownRefresh() {
    this.load().then(() => uni.stopPullDownRefresh())
  },

  methods: {
    // 当前筛选范围内的原始行
    scoped() {
      return filterDevice(this.rows, this.device)
    },

    dur(sec) {
      return fmtDuration(sec)
    },

    // 条形长度按"最大项"归一，比按总量归一更容易看出差距
    barWidth(r) {
      const max = this.list.length ? this.list[0].seconds : 0
      if (!max) return '0%'
      return Math.max(2, Math.round((r.seconds / max) * 100)) + '%'
    },

    pickDevice(id) {
      this.device = id
    },

    shift(delta) {
      if (delta > 0 && this.isToday) return
      this.day = shiftDay(this.day, delta)
      this.load()
    },

    goToday() {
      this.day = todayStr()
      this.load()
    },

    reload() {
      this.load()
    },

    goSetup() {
      uni.navigateTo({ url: '/pages/setup/setup' })
    },

    async load() {
      this.loading = true
      this.err = ''
      try {
        const [rows, devices] = await Promise.all([fetchDay(this.day), fetchDevices()])
        this.rows = rows
        this.devices = deviceList(devices.length ? this.withSeconds(devices) : rows)
        // 选中设备如果这天没数据，自动回到"全部"，否则界面会空着让人困惑
        if (this.device && !this.devices.some((d) => d.id === this.device)) this.device = ''
      } catch (e) {
        this.rows = []
        this.devices = []
        this.err = e.message || '加载失败'
        uni.showToast({ title: this.err, icon: 'none', duration: 2500 })
      } finally {
        this.loading = false
      }
    },

    // v_devices 没有 seconds 字段，补 0 好让 deviceList 复用同一套排序
    withSeconds(list) {
      return list.map((d) => ({ ...d, seconds: 0, segments: d.sessions || 0 }))
    }
  }
}
</script>

<style scoped>
.page {
  padding: 24rpx 24rpx 60rpx;
}

.card {
  background: #fff;
  border-radius: 24rpx;
  padding: 28rpx;
  box-shadow: 0 2rpx 12rpx rgba(0, 0, 0, 0.04);
}

/* ---------- 头部 ---------- */
.daterow {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.navbtn {
  width: 72rpx;
  height: 72rpx;
  border-radius: 36rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f2f3f5;
}
.navbtn.off {
  opacity: 0.28;
}
.chev {
  font-size: 40rpx;
  color: #3d4250;
  line-height: 40rpx;
}
.datebox {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.day {
  font-size: 32rpx;
  font-weight: 600;
  color: #1a1a1a;
}
.hint {
  font-size: 22rpx;
  color: #9aa0aa;
  margin-top: 4rpx;
}
.hint.tap {
  color: #2f6bff;
}

.total {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 32rpx 0 26rpx;
}
.num {
  font-size: 66rpx;
  font-weight: 700;
  letter-spacing: -1rpx;
  color: #1a1a1a;
}
.sub {
  font-size: 24rpx;
  color: #9aa0aa;
  margin-top: 8rpx;
}

.chips {
  white-space: nowrap;
  width: 100%;
}
.chip {
  display: inline-block;
  padding: 10rpx 24rpx;
  margin-right: 14rpx;
  border-radius: 999rpx;
  background: #f2f3f5;
  font-size: 24rpx;
  color: #5a6072;
}
.chip.on {
  background: #2f6bff;
  color: #fff;
}

/* ---------- 页签 ---------- */
.tabs {
  display: flex;
  margin: 22rpx 0 14rpx;
  background: #e9ebef;
  border-radius: 16rpx;
  padding: 6rpx;
}
.tab {
  flex: 1;
  text-align: center;
  padding: 14rpx 0;
  font-size: 26rpx;
  color: #5a6072;
  border-radius: 12rpx;
}
.tab.on {
  background: #fff;
  color: #1a1a1a;
  font-weight: 600;
}

/* ---------- 列表 ---------- */
.list {
  padding: 10rpx 28rpx;
}
.row {
  padding: 22rpx 0;
  border-bottom: 1rpx solid #f0f1f4;
  position: relative;
}
.row:last-child {
  border-bottom: none;
}
.r1 {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 12rpx;
}
.name {
  font-size: 28rpx;
  color: #1a1a1a;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-right: 20rpx;
}
.dur {
  font-size: 26rpx;
  color: #3d4250;
  font-weight: 600;
}
.bar {
  height: 10rpx;
  border-radius: 999rpx;
  background: #eef0f4;
  margin-right: 88rpx;
  overflow: hidden;
}
.fill {
  height: 100%;
  border-radius: 999rpx;
  background: linear-gradient(90deg, #2f6bff, #37c2b4);
}
.pct {
  position: absolute;
  right: 0;
  bottom: 20rpx;
  font-size: 22rpx;
  color: #9aa0aa;
}

/* ---------- 状态 ---------- */
.loading,
.empty {
  padding: 70rpx 0;
  text-align: center;
  color: #9aa0aa;
  font-size: 26rpx;
  display: flex;
  flex-direction: column;
  gap: 10rpx;
}
.empty-sub {
  font-size: 22rpx;
  color: #b9bec7;
}

.foot {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16rpx;
  padding: 36rpx 0 10rpx;
  font-size: 24rpx;
  color: #9aa0aa;
}
.foot-btn {
  color: #6b7280;
}
.foot-sep {
  color: #ccd0d6;
}
</style>
