<template>
  <view class="joy-wrap" :class="{ disabled }">
    <view
      class="joy-base"
      @touchstart.stop.prevent="onStart"
      @touchmove.stop.prevent="onMove"
      @touchend.stop.prevent="onEnd"
      @touchcancel.stop.prevent="onEnd"
    >
      <view class="axis axis-h"></view>
      <view class="axis axis-v"></view>
      <view class="ring ring-mid"></view>
      <view class="ring ring-inner"></view>
      <view class="knob" :style="knobStyle">
        <view class="knob-core"></view>
      </view>
    </view>
  </view>
</template>

<script>
export default {
  name: 'CarJoystick',
  props: {
    // 未连接时禁用，避免用户推摇杆却发现没反应
    disabled: {
      type: Boolean,
      default: false
    },
    // 死区，小于这个幅度直接归零
    dead: {
      type: Number,
      default: 0.08
    },
    // 摇杆直径，单位 rpx，改了要同步 css 里的 .joy-base 尺寸
    sizeRpx: {
      type: Number,
      default: 460
    }
  },
  data() {
    return {
      centerX: 0,
      centerY: 0,
      radius: 0,
      active: false,
      kx: 0,
      ky: 0
    }
  },
  computed: {
    knobStyle() {
      return {
        transform: `translate(${this.kx}px, ${this.ky}px)`
      }
    }
  },
  mounted() {
    this.$nextTick(() => this.measure())
  },
  methods: {
    measure() {
      try {
        uni
          .createSelectorQuery()
          .in(this)
          .select('.joy-base')
          .boundingClientRect((rect) => {
            if (!rect || !rect.width) {
              this.fallbackSize()
              return
            }
            this.centerX = rect.left + rect.width / 2
            this.centerY = rect.top + rect.height / 2
            this.radius = rect.width / 2
          })
          .exec()
      } catch (e) {
        this.fallbackSize()
      }
    },

    // 拿不到节点尺寸时按 rpx 估算，保证摇杆仍可用
    fallbackSize() {
      this.radius = uni.upx2px(this.sizeRpx) / 2
      this.centerX = uni.getSystemInfoSync().windowWidth / 2
      this.centerY = uni.getSystemInfoSync().windowHeight - uni.upx2px(120)
    },

    onStart(e) {
      if (this.disabled) return
      // 元素位置可能因旋转/键盘变化，每次按下重新测量一次
      this.measure()
      this.active = true
      this.$emit('start')
      this.handleTouch(e)
    },

    onMove(e) {
      if (!this.active || this.disabled) return
      this.handleTouch(e)
    },

    handleTouch(e) {
      const t = (e.touches && e.touches[0]) || (e.changedTouches && e.changedTouches[0])
      if (!t || !this.radius) return

      let dx = t.clientX - this.centerX
      let dy = t.clientY - this.centerY

      // 超出圆形范围就贴到边缘，保证方向不变、幅度封顶
      const dist = Math.sqrt(dx * dx + dy * dy)
      if (dist > this.radius) {
        dx = (dx / dist) * this.radius
        dy = (dy / dist) * this.radius
      }

      this.kx = dx
      this.ky = dy

      let x = dx / this.radius
      let y = -dy / this.radius // 屏幕坐标 y 向下为正，这里取反成"上为前进"

      if (Math.sqrt(x * x + y * y) < this.dead) {
        x = 0
        y = 0
      }

      this.$emit('change', {
        x: Number(x.toFixed(3)),
        y: Number(y.toFixed(3))
      })
    },

    onEnd() {
      if (!this.active) return
      this.active = false
      this.kx = 0
      this.ky = 0
      this.$emit('change', { x: 0, y: 0 })
      this.$emit('end')
    },

    reset() {
      this.active = false
      this.kx = 0
      this.ky = 0
    }
  }
}
</script>

<style scoped>
.joy-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  transition: opacity 0.2s;
}

.joy-wrap.disabled {
  opacity: 0.45;
}

.joy-base {
  position: relative;
  width: 460rpx;
  height: 460rpx;
  border-radius: 50%;
  background-color: #edeff2;
  border: 2rpx solid #dfe3e8;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.axis {
  position: absolute;
  background-color: #dfe3e8;
}

.axis-h {
  width: 100%;
  height: 2rpx;
}

.axis-v {
  width: 2rpx;
  height: 100%;
}

.ring {
  position: absolute;
  border-radius: 50%;
  border: 2rpx solid #e2e6eb;
}

.ring-mid {
  width: 300rpx;
  height: 300rpx;
}

.ring-inner {
  width: 130rpx;
  height: 130rpx;
  border-color: #d6dbe2;
}

.knob {
  position: absolute;
  width: 170rpx;
  height: 170rpx;
  border-radius: 50%;
  background-color: #ffffff;
  border: 2rpx solid #d6dbe2;
  box-shadow: 0 6rpx 16rpx rgba(26, 29, 33, 0.12);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.06s linear;
}

.knob-core {
  width: 54rpx;
  height: 54rpx;
  border-radius: 50%;
  background-color: #c3cad3;
}
</style>
