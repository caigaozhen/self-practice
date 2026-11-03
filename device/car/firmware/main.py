"""
ESP32 MicroPython 遥控小车 —— WebSocket 服务端 + 内置网页测试台

配套客户端：F:\\self-practice\\python\\car（uniapp 工程）

一个端口做两件事：连接进来先看请求头
    · 带 Sec-WebSocket-Key  → 走 WebSocket，接收控制指令
    · 普通 HTTP GET         → 返回内置控制网页
所以手机浏览器直接打开 http://192.168.4.1:81 就能点按钮试车，不用装 App。

协议：
    客户端 30Hz 推送文本帧   {"y":0.62,"x":-0.15}
        y = 前后   1 全速前进 / -1 全速后退
        x = 左右   1 全速右转 / -1 全速左转

接线（TB6612FNG）：
    PWMA -> GPIO25   AIN1 -> GPIO26  AIN2 -> GPIO27   左轮
    PWMB -> GPIO33   BIN1 -> GPIO32  BIN2 -> GPIO23   右轮
    STBY -> 3.3V     VCC  -> 3.3V    VM   -> 电池 7.4V
    GND  -> 电池负极 / ESP32 GND（全部共地）
"""

import network
import socket
import machine
import time
import json
import hashlib
import binascii
import struct

# ---------------- 配置区 ----------------
AP_SSID = "RC-CAR"
AP_PASS = "12345678"      # 至少 8 位
PORT = 81                 # 网页和 WebSocket 共用这一个端口

PWMA, AIN1, AIN2 = 25, 26, 27
PWMB, BIN1, BIN2 = 33, 32, 23

PWM_FREQ = 20000          # 20kHz 超出人耳范围，电机不啸叫
TIMEOUT_MS = 400          # 超过这个时间没收到指令就停车
DEADZONE = 0.02           # 固件侧死区，进一步防止中位抖动
SPEED_LIMIT = 1.0         # 全局限速，调试可调低，手机端还有一层限速

DEBUG = False             # 打开后会打印收到的指令，调试协议时用
# ---------------------------------------

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

pwm_a = machine.PWM(machine.Pin(PWMA), freq=PWM_FREQ)
pwm_b = machine.PWM(machine.Pin(PWMB), freq=PWM_FREQ)
pwm_a.duty_u16(0)
pwm_b.duty_u16(0)

a1 = machine.Pin(AIN1, machine.Pin.OUT)
a2 = machine.Pin(AIN2, machine.Pin.OUT)
b1 = machine.Pin(BIN1, machine.Pin.OUT)
b2 = machine.Pin(BIN2, machine.Pin.OUT)


def motor(pwm, p1, p2, v):
    """v: -1.0 ~ 1.0，负值反转。绝对值小于死区时滑行停车。"""
    if v > DEADZONE:
        p1.value(1)
        p2.value(0)
    elif v < -DEADZONE:
        p1.value(0)
        p2.value(1)
    else:
        p1.value(0)
        p2.value(0)
        v = 0.0
    pwm.duty_u16(int(abs(v) * 65535))


def drive(left, right):
    """差速转向：等比缩放到 [-1,1] 内，保证转向关系不变。"""
    m = max(1.0, abs(left), abs(right))
    motor(pwm_a, a1, a2, left / m * SPEED_LIMIT)
    motor(pwm_b, b1, b2, right / m * SPEED_LIMIT)


# ---------------- 内置测试网页 ----------------
INDEX_HTML = '''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>RC Car</title>
<style>
body{margin:0;padding:18px;background:#f4f5f7;font-family:-apple-system,"PingFang SC",sans-serif;
-webkit-user-select:none;user-select:none;-webkit-tap-highlight-color:transparent}
h1{font-size:16px;margin:0 0 4px;color:#1a1d21;font-weight:500}
.st{font-size:12px;color:#6b7280;margin-bottom:18px}
.pad{display:grid;grid-template-columns:repeat(3,1fr);grid-gap:10px;max-width:380px;margin:0 auto}
.btn{height:80px;border-radius:14px;background:#fff;border:1px solid #e5e7eb;display:flex;
align-items:center;justify-content:center;font-size:18px;color:#1a1d21;font-weight:500}
.btn:active{background:#1d9e75;color:#fff;border-color:#1d9e75}
.stop{background:#e24b4a;color:#fff;border-color:#e24b4a}
.sp{margin:20px auto 0;max-width:380px}
.sp label{font-size:12px;color:#6b7280}
input[type=range]{width:100%}
</style>
</head>
<body>
<h1>RC Car 测试台</h1>
<div class="st">状态：<b id="st">连接中…</b></div>
<div class="pad">
<div></div><div class="btn" id="fwd">前进</div><div></div>
<div class="btn" id="left">左转</div><div class="btn stop" id="stop">停</div><div class="btn" id="right">右转</div>
<div></div><div class="btn" id="back">后退</div><div></div>
</div>
<div class="sp">
<label>限速 <span id="sv">60</span>%</label>
<input type="range" id="speed" min="20" max="100" value="60">
</div>
<script>
var ws=null,conn=false,cur={y:0,x:0},sp=0.6;
var el=document.getElementById("st");
function setSt(t,ok){el.textContent=t;el.style.color=ok?"#1d9e75":"#a32d2d"}
function connect(){
ws=new WebSocket("ws://"+location.host+"/");
ws.onopen=function(){conn=true;setSt("已连接",1)};
ws.onclose=function(){conn=false;setSt("已断开，重连中",0);cur={y:0,x:0};setTimeout(connect,1500)};
}
setInterval(function(){
if(conn&&ws.readyState===1){
ws.send(JSON.stringify({y:+(cur.y*sp).toFixed(2),x:+(cur.x*sp).toFixed(2)}));
}
},33);
function hold(id,y,x){
var e=document.getElementById(id);
function set(on){cur.y=on?y:0;cur.x=on?x:0}
e.addEventListener("pointerdown",function(ev){ev.preventDefault();set(1)});
e.addEventListener("pointerup",function(){set(0)});
e.addEventListener("pointercancel",function(){set(0)});
e.addEventListener("pointerleave",function(){set(0)});
}
hold("fwd",1,0);hold("back",-1,0);hold("left",0,-1);hold("right",0,1);
document.getElementById("stop").addEventListener("pointerdown",function(){cur={y:0,x:0}});
document.getElementById("speed").addEventListener("input",function(ev){
sp=ev.target.value/100;document.getElementById("sv").textContent=ev.target.value;
});
connect();
</script>
</body>
</html>
'''


def read_head(conn):
    """读到 HTTP 请求头结束标记，返回 (head, 剩余字节)；失败返回 (None, b'')。"""
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = conn.recv(512)
        if not chunk:
            return None, b""
        buf += chunk
        if len(buf) > 4096:
            return None, b""
    head, _, rest = buf.partition(b"\r\n\r\n")
    return head, rest


def ws_upgrade(conn, head):
    """完成 WebSocket 握手，成功返回 True。"""
    key = b""
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"sec-websocket-key:"):
            key = line.split(b":", 1)[1].strip()
            break
    if not key:
        return False

    accept = binascii.b2a_base64(hashlib.sha1(key + GUID.encode()).digest()).strip()
    conn.send(
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Upgrade: websocket\r\n"
        b"Connection: Upgrade\r\n"
        b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n"
    )
    return True


def http_reply(conn, head):
    """返回内置测试页。favicon 请求直接 204，避免浏览器反复打。"""
    first_line = head.split(b"\r\n", 1)[0]

    if b"favicon" in first_line:
        conn.send(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
        return

    body = INDEX_HTML.encode()
    head_out = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"Connection: close\r\n"
        b"Cache-Control: no-store\r\n\r\n"
    )
    conn.send(head_out + body)


class WsReader:
    """增量式 WebSocket 帧解析。

    必须带缓冲：TCP 会把多个小帧合并成一次 recv，也可能把一帧拆成多次，
    直接按帧长度 recv 迟早会错位。
    """

    def __init__(self, conn, initial=b""):
        self.s = conn
        self.buf = bytearray(initial)

    def poll(self):
        """读一次网络，返回本次解析出的文本消息列表。断开时抛 OSError。"""
        try:
            chunk = self.s.recv(512)
            if not chunk:
                raise OSError("peer closed")
            self.buf.extend(chunk)
        except OSError as e:
            # 11 = EAGAIN，110 = ETIMEDOUT，都表示这一轮没数据，不是断线
            if not (e.args and e.args[0] in (11, 110)):
                raise

        msgs = []
        while True:
            frame = self._next()
            if frame is None:
                break
            op, payload = frame
            if op == 1 and payload:
                msgs.append(payload.decode())
            elif op == 8:
                raise OSError("close frame")
        return msgs

    def _next(self):
        buf = self.buf
        if len(buf) < 2:
            return None

        op = buf[0] & 0x0F
        masked = buf[1] & 0x80
        length = buf[1] & 0x7F
        off = 2

        if length == 126:
            if len(buf) < 4:
                return None
            length = struct.unpack(">H", buf[2:4])[0]
            off = 4
        elif length == 127:
            if len(buf) < 10:
                return None
            length = struct.unpack(">Q", buf[2:10])[0]
            off = 10

        total = off + (4 if masked else 0) + length
        if len(buf) < total:
            return None

        if masked:
            mask = buf[off:off + 4]
            body = buf[off + 4:total]
            payload = bytes(body[i] ^ mask[i & 3] for i in range(len(body)))
        else:
            payload = bytes(buf[off:total])

        del buf[:total]
        return op, payload


# ---------------- 建热点 ----------------
ap = network.WLAN(network.AP_IF)
ap.active(True)
ap.config(ssid=AP_SSID, password=AP_PASS)
ap.ifconfig(("192.168.4.1", "255.255.255.0", "192.168.4.1", "8.8.8.8"))

print("AP:", AP_SSID, "密码:", AP_PASS)
print("网页: http://%s:%d" % (ap.ifconfig()[0], PORT))
print("WS  : ws://%s:%d" % (ap.ifconfig()[0], PORT))

srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", PORT))
srv.listen(2)
srv.settimeout(1.0)

drive(0, 0)

while True:
    # ---- 等待连接 ----
    try:
        conn, addr = srv.accept()
    except OSError:
        drive(0, 0)
        continue

    conn.settimeout(1.0)

    try:
        head, rest = read_head(conn)
    except OSError:
        head, rest = None, b""

    if head is None:
        try:
            conn.close()
        except OSError:
            pass
        continue

    # ---- 普通 HTTP：返回测试网页 ----
    if b"sec-websocket-key" not in head.lower():
        try:
            http_reply(conn, head)
        except OSError:
            pass
        try:
            conn.close()
        except OSError:
            pass
        continue

    # ---- WebSocket：控制通道 ----
    try:
        if not ws_upgrade(conn, head):
            conn.close()
            continue
    except OSError:
        try:
            conn.close()
        except OSError:
            pass
        continue

    print("client:", addr)
    conn.settimeout(0.05)
    reader = WsReader(conn, rest)
    last_rx = time.ticks_ms()
    count = 0

    while True:
        try:
            for msg in reader.poll():
                try:
                    d = json.loads(msg)
                    y = float(d.get("y", 0))
                    x = float(d.get("x", 0))
                except (ValueError, TypeError):
                    continue

                drive(y + x, y - x)
                last_rx = time.ticks_ms()

                if DEBUG:
                    count += 1
                    if count % 30 == 0:
                        print("y=%.2f x=%.2f -> L=%.2f R=%.2f"
                              % (y, x, (y + x), (y - x)))
        except OSError:
            print("client gone")
            break

        # 失联保护：这条比任何功能都重要
        if time.ticks_diff(time.ticks_ms(), last_rx) > TIMEOUT_MS:
            drive(0, 0)

    try:
        conn.close()
    except OSError:
        pass
    drive(0, 0)
