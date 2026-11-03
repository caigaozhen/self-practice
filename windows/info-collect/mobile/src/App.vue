<script>
export default {
  onLaunch() {
    // 启动时不做任何网络请求：没配置过就先让用户去设置页，
    // 配过的由首页 onShow 自行加载，避免启动卡顿。
  }
}
</script>

<style>
/* 全局基础样式。uni-app 里每个页面共享这段，页面内再写自己的 scoped 样式。 */
page {
  background-color: #f2f3f5;
  color: #1a1a1a;
  font-size: 28rpx;
  font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

view,
text {
  box-sizing: border-box;
}
</style>
