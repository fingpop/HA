# inSona 本地网关 TCP 对接协议  
版本：V4（2021-05-26）  
通信方式：TCP（端口 8091）  
数据格式：UTF-8 JSON，每条消息以 `\r\n` 结尾  

---

## 1. 连接流程

| 步骤 | 动作 |
| --- | --- |
| ① | 通过 inSona APP 获取网关 IP |
| ② | `socket(AF_INET, SOCK_STREAM)` 连接网关 `IP:8091` |
| ③ | 按下面协议收发 JSON |

---

## 2. 通用帧结构

```json
{
  "version": 1,
  "uuid": 1234,              // 请求唯一标识，响应/事件带回同一 uuid
  "method": "c.query|s.query|c.control|s.control|s.event",
  ...                         // 其余字段见下文
}\r\n
```

---

## 3. 设备信息同步

### 3.1 请求（客户端 → 网关）

```json
{"version":1,"uuid":1234,"type":"all","method":"c.query"}
```

### 3.2 响应（网关 → 客户端）

```json
{
  "version":1,
  "uuid":1234,
  "method":"s.query",
  "result":"ok",
  "rooms":[
    {"roomId":6,"name":"办公区"},
    {"roomId":14,"name":"会议室"}
  ],
  "devices":[
    {
      "did":"ECC57F1031F100",
      "pid":256,
      "ver":"61706",
      "type":1984,          // 1984=灯具, 1218=面板, 1344=传感器, 1860=窗帘
      "alive":1,            // 1在线 0离线
      "roomId":26,
      "name":"会议过道",
      "func":4,             // 当前生效功能
      "funcs":[2,3,4,11],   // 支持的全部功能
      "value":[0,100,8]     // 功能对应的状态值
    }
  ]
}
```

#### 3.2.1 灯具类型辨识（funcs 字段）

| funcs 包含 | 类型 |
| --- | --- |
| `[2,11]` | 继电器开关 |
| `[2,3,11]` | 单色温调光 |
| `[2,3,4,11]` | 双色温灯 |
| `[2,3,5,11]` | RGB |
| `[2,3,4,5,11]` | RGB + 双色温 |

---

## 4. 设备控制

### 4.1 请求（客户端 → 网关）

```json
{
  "version":1,
  "uuid":1,
  "method":"c.control",
  "did":"ECC57F1031F100",   // 设备或组地址
  "action":"onoff|level|ctl|hsl|curtainstop|curtainangel",
  "value":[...],
  "transition":0            // 过渡时间 ms
}
```

#### 4.1.1 控制示例

| 动作 | action | value |
| --- | --- | --- |
| 开关 | `onoff` | `[0]` 关 `[1]` 开 |
| 亮度 | `level` | `[30]` 30% |
| 亮度+色温 | `ctl` | `[80,60]` 亮度 80%，色温 60% |
| RGB | `hsl` | `[100,120,100]` 亮度 100%，色相 120°，饱和度 100% |
| 窗帘停止 | `curtainstop` | `[]` |
| 梦幻帘角度 | `curtainangel` | `[90]` 角度 0-180 |

### 4.2 响应（网关 → 客户端）

```json
{"version":1,"uuid":1,"method":"s.control","result":"ok"}
```

---

## 5. 场景

### 5.1 获取场景列表

#### 请求
```json
{"version":1,"uuid":1234,"method":"c.query.scene"}
```

#### 响应
```json
{
  "version":1,
  "uuid":1234,
  "method":"s.query.scene",
  "scenes":[
    {"sceneId":2,"name":"喝茶"},
    {"sceneId":4,"name":"会议"}
  ]
}
```

### 5.2 执行场景

```json
{
  "version":1,
  "uuid":1,
  "method":"c.control",
  "action":"scene",
  "value":["2"],      // sceneId
  "transition":0
}
```

---

## 6. 网关主动事件（s.event）

网关会在以下场景主动推送：

| 事件类型 | evt | 说明 |
| --- | --- | --- |
| 设备状态 | `status` | 开关/亮度/色温/RGB 变化 |
| 传感器 | `sensor` | 人感、光感触发 |
| 面板按键 | `switch.key` | 面板按键动作 |

### 6.1 示例

```json
// 设备关闭
{"version":1,"uuid":14,"method":"s.event","evt":"status","did":"F0ACD777770300","func":2,"value":[0]}

// 人感触发
{"version":1,"uuid":4,"method":"s.event","evt":"sensor","did":"F0ACD760002D00","func":10,"value":[1,1]}

// 面板第 3 键按下
{"version":1,"uuid":1632,"method":"s.event","evt":"switch.key","did":"ECC57F108F3BFF","func":9,"value":[3,0]}
```

---

## 7. 字段速查表

| 字段 | 取值示例 | 含义 |
| --- | --- | --- |
| `type` | 1984 / 1218 / 1344 / 1860 | 灯具 / 面板 / 传感器 / 窗帘 |
| `func` | 2 / 3 / 4 / 5 / 10 | 开关 / 亮度 / 亮度色温 / RGB / 传感器 |
| `value` | `[1]` / `[30]` / `[80,60]` / `[100,120,100]` | 开关 / 亮度 / 亮度色温 / HSL |
| `transition` | 0-4294967295 | 渐变时间，毫秒 |

---

## 8. Python 最小示例

```python
from socket import *

HOST = '192.168.1.100'   # 网关 IP
PORT = 8091

sock = socket(AF_INET, SOCK_STREAM)
sock.connect((HOST, PORT))

# 1. 获取设备列表
query = b'{"version":1,"uuid":1,"type":"all","method":"c.query"}\r\n'
sock.sendall(query)
print(sock.recv(4096))

# 2. 关闭某灯
ctrl = b'{"version":1,"uuid":2,"method":"c.control","did":"ECC57F1031F100","action":"onoff","value":[0],"transition":0}\r\n'
sock.sendall(ctrl)
print(sock.recv(1024))

sock.close()
```

---

以上即为 inSona 本地网关 TCP 协议完整对接文档，可直接用于二次开发。