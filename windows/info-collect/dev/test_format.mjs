/**
 * 手机端纯函数测试（Node 直接跑，不需要 uni 环境）。
 *
 *   node dev/test_format.mjs
 *
 * 为什么用 data: URL 导入：mobile/src/utils/format.js 是 ESM，
 * 而 mobile/package.json 没有 "type": "module"（uni-app 工程不需要）。
 * 转成 data URL 导入，既不用改工程配置，也不用把文件复制一份。
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const file = path.join(here, '..', 'mobile', 'src', 'utils', 'format.js')
const src = fs.readFileSync(file, 'utf8')
const mod = await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'))

const { fmtDuration, shiftDay, fmtDay, totalOf, aggregate, deviceList, filterDevice } = mod

let pass = 0
let fail = 0
function eq(actual, expected, label) {
  if (JSON.stringify(actual) === JSON.stringify(expected)) {
    pass++
    return
  }
  fail++
  console.log(`  x ${label}\n     期望 ${JSON.stringify(expected)}\n     实际 ${JSON.stringify(actual)}`)
}

console.log('— 时长格式化 —')
eq(fmtDuration(0), '0 秒', '0')
eq(fmtDuration(45), '45 秒', '45秒')
eq(fmtDuration(90), '2 分', '90秒转分')
eq(fmtDuration(3600), '1 小时', '整点')
eq(fmtDuration(5400), '1 小时 30 分', '1.5小时')
eq(fmtDuration(-5), '0 秒', '负数兜底')
eq(fmtDuration('120'), '2 分', '字符串输入')

console.log('— 日期推算 —')
eq(shiftDay('2026-10-31', -1), '2026-10-30', '跨月末向前')
eq(shiftDay('2026-11-01', -1), '2026-10-31', '跨月向前')
eq(shiftDay('2026-03-01', -1), '2026-02-28', '非闰年2月')
eq(shiftDay('2027-01-01', -1), '2026-12-31', '跨年向前')
eq(shiftDay('2026-12-31', 1), '2027-01-01', '跨年向后')
eq(fmtDay('2026-10-30'), '10月30日 周五', '周五')
eq(fmtDay('2026-11-01'), '11月1日 周日', '周日')

console.log('— 聚合与设备 —')
const rows = [
  { device_id: 'a', device_name: '台式机', category: '编码', app: 'code.exe', seconds: 3600 },
  { device_id: 'a', device_name: '台式机', category: '编码', app: 'pycharm64.exe', seconds: 600 },
  { device_id: 'b', device_name: '笔记本', category: '浏览', app: 'msedge.exe', seconds: 1200 },
  { device_id: 'b', device_name: '笔记本', category: '', app: 'x.exe', seconds: 600 }
]
eq(totalOf(rows), 6000, '总时长')
const byCat = aggregate(rows, 'category')
eq(byCat[0], { name: '编码', seconds: 4200, pct: 70 }, '分类首位与占比')
eq(byCat[1].name, '浏览', '分类次序')
eq(byCat[2].name, '未知', '空分类兜底')
eq(Math.round(byCat.reduce((s, x) => s + x.pct, 0)), 100, '占比合计100')
const devs = deviceList(rows)
eq(devs.length, 2, '设备数')
eq(devs[0].name, '台式机', '设备按时长排序')
eq(devs[0].seconds, 4200, '设备时长')
eq(filterDevice(rows, 'b').length, 2, '按设备过滤')
eq(filterDevice(rows, '').length, 4, '不筛选返回全部')

console.log(`\n结果：通过 ${pass}　失败 ${fail}`)
process.exit(fail ? 1 : 0)
