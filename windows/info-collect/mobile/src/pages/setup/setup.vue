<template>
  <view class="page">
    <view class="card">
      <view class="title">连接你的 Supabase</view>
      <view class="desc">
        四个值都来自你自己的 Supabase 项目。填一次就行，之后存在手机本地。
      </view>

      <view class="field">
        <text class="label">项目地址</text>
        <input
          class="ipt"
          v-model="url"
          placeholder="https://xxxx.supabase.co"
          placeholder-class="ph"
          :adjust-position="true"
          autocapitalize="off"
          autocorrect="off"
        />
      </view>

      <view class="field">
        <text class="label">anon key</text>
        <textarea
          class="ipt area"
          v-model="key"
          placeholder="eyJhbGciOi..."
          placeholder-class="ph"
          auto-height
          :maxlength="-1"
        />
        <text class="tip">Project Settings → API → anon public</text>
      </view>

      <view class="field">
        <text class="label">邮箱</text>
        <input class="ipt" v-model="email" placeholder="you@example.com" placeholder-class="ph" />
      </view>

      <view class="field">
        <text class="label">密码</text>
        <input class="ipt" v-model="password" password placeholder="Supabase 里创建的用户密码" placeholder-class="ph" />
        <text class="tip">Authentication → Users → Add user（记得勾 Auto Confirm）</text>
      </view>

      <view class="btns">
        <button class="btn primary" :loading="testing" :disabled="testing" @tap="submit">
          {{ testing ? '正在测试…' : '测试并保存' }}
        </button>
        <button class="btn plain" @tap="reset">清除配置</button>
      </view>

      <view class="result" v-if="result">
        <text class="ok" v-if="result.ok">✓ {{ result.text }}</text>
        <text class="bad" v-else>✕ {{ result.text }}</text>
      </view>
    </view>

    <view class="card note">
      <view class="note-title">手机上只读，不写入</view>
      <view class="note-body">
        电脑端负责采集和上传，这里只是查看。所以你看到的永远是最新一次推送的结果
        （默认每 4 小时一次，关机时会再推一次）。
      </view>
    </view>
  </view>
</template>

<script>
import { getCfg, saveCfg, clearCfg, testConnection } from '../../utils/api.js'

export default {
  data() {
    return {
      url: '',
      key: '',
      email: '',
      password: '',
      testing: false,
      result: null
    }
  },

  onLoad() {
    const c = getCfg()
    if (c) {
      this.url = c.url || ''
      this.key = c.key || ''
      this.email = c.email || ''
      this.password = c.password || ''
    }
  },

  methods: {
    async submit() {
      if (!this.url || !this.key || !this.email || !this.password) {
        this.result = { ok: false, text: '四个框都要填' }
        return
      }
      this.testing = true
      this.result = null
      const cfg = {
        url: this.url.trim(),
        key: this.key.trim(),
        email: this.email.trim(),
        password: this.password
      }
      try {
        const { rows, today } = await testConnection(cfg)
        saveCfg(cfg)
        const total = rows.reduce((s, r) => s + (Number(r.seconds) || 0), 0)
        const mins = Math.round(total / 60)
        this.result = {
          ok: true,
          text: '连接成功，今天读到 ' + rows.length + ' 条聚合记录（约 ' + mins + ' 分钟）'
        }
        setTimeout(() => {
          uni.reLaunch({ url: '/pages/index/index' })
        }, 900)
      } catch (e) {
        this.result = { ok: false, text: e.message || '连接失败' }
      } finally {
        this.testing = false
      }
    },

    reset() {
      uni.showModal({
        title: '清除配置',
        content: '会删除本机保存的项目地址、key 和账号，云端数据不受影响。',
        success: (r) => {
          if (!r.confirm) return
          clearCfg()
          this.url = ''
          this.key = ''
          this.email = ''
          this.password = ''
          this.result = { ok: true, text: '已清除' }
        }
      })
    }
  }
}
</script>

<style scoped>
.page {
  padding: 24rpx;
}

.card {
  background: #fff;
  border-radius: 24rpx;
  padding: 32rpx 28rpx;
  box-shadow: 0 2rpx 12rpx rgba(0, 0, 0, 0.04);
  margin-bottom: 24rpx;
}

.title {
  font-size: 34rpx;
  font-weight: 700;
  color: #1a1a1a;
}
.desc {
  font-size: 24rpx;
  color: #8a8f99;
  line-height: 1.6;
  margin: 10rpx 0 26rpx;
}

.field {
  margin-bottom: 24rpx;
}
.label {
  display: block;
  font-size: 24rpx;
  color: #5a6072;
  margin-bottom: 10rpx;
}
.ipt {
  width: 100%;
  min-height: 84rpx;
  background: #f5f6f8;
  border-radius: 14rpx;
  padding: 0 20rpx;
  font-size: 26rpx;
  color: #1a1a1a;
  line-height: 84rpx;
}
.ipt.area {
  min-height: 130rpx;
  line-height: 1.5;
  padding: 18rpx 20rpx;
  font-size: 22rpx;
}
.ph {
  color: #b9bec7;
}
.tip {
  display: block;
  font-size: 21rpx;
  color: #b0b5be;
  margin-top: 8rpx;
}

.btns {
  margin-top: 12rpx;
}
.btn {
  height: 88rpx;
  line-height: 88rpx;
  border-radius: 16rpx;
  font-size: 30rpx;
  margin-bottom: 18rpx;
}
.btn.primary {
  background: #2f6bff;
  color: #fff;
}
.btn.primary[disabled] {
  opacity: 0.6;
  color: #fff;
}
.btn.plain {
  background: #f2f3f5;
  color: #5a6072;
}

.result {
  padding: 18rpx 20rpx;
  border-radius: 14rpx;
  background: #f5f6f8;
  font-size: 24rpx;
  line-height: 1.5;
}
.ok {
  color: #17a673;
}
.bad {
  color: #d64545;
}

.note {
  background: #fbfcfd;
  border: 1rpx solid #eceef2;
}
.note-title {
  font-size: 26rpx;
  font-weight: 600;
  color: #3d4250;
}
.note-body {
  font-size: 23rpx;
  color: #8a8f99;
  line-height: 1.7;
  margin-top: 8rpx;
}
</style>
