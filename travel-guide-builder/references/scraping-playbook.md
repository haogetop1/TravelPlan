# 抓价与采集实战手册

2026-09 贵州项目实测记录。**能抓到什么、抓不到什么，心里要有底**，别在同一个坑上反复试。

## 一、小红书登录（最容易浪费时间的一环）

**直接扫码，不要试图复用本机浏览器的登录态。** 完整失败链条记录在
`~/.workbuddy/skills/xhs-humanized-collect/SKILL.md` 的「踩坑⑤」，摘要：

| 尝试 | 结果 |
|---|---|
| Chrome 运行中直接复制 Cookies 库 | ❌ 文件被进程独占锁 |
| robocopy `/B` 备份模式强制读取 | ❌ 无权限 |
| 复制到新 `user-data-dir` 后启动 | ❌ Cookie 被清零（1661 → 14 条），Chrome 152 的 App-Bound Encryption，密钥无法随 profile 迁移 |
| 用默认 profile 开远程调试 | ❌ `DevTools remote debugging requires a non-default data directory` |
| Playwright 默认参数启动 | ❌ `--use-mock-keychain` 破坏系统级 Cookie 解密 |

**可行解**：`launch_persistent_context` 独立 profile + 扫码一次（实测 35 秒完成），
登录态永久保存在项目 `.workbuddy/` 下，后续复用。

两个配套要点：
- 登录判据**必须用 `id_token` 存在**，不能用 `web_session` 长度 —— 未登录时 `web_session`
  也是 38 位匿名值，用长度判断会**误判成已登录**。
- 二维码**每 20s 重新截图覆盖同一个 `qrcode.png`**，再 `present_files` 展示该文件，
  用户看到的永远是最新的，避免「码过期了」的往返。

## 二、携程机票 ✅ 可抓

**关键：`sleep` + `subprocess.Popen` 启动原生 Chrome，再用 `connect_over_cdp` 连上去。**
直接用 Playwright 启动会被拦截，页面只显示 `whaleguard block`。

```python
proc = subprocess.Popen([CHROME, "--remote-debugging-port=9337",
                         "--user-data-dir=<独立 profile>",
                         "--no-first-run", "--disable-extensions", "about:blank"], ...)
time.sleep(7)
br = p.chromium.connect_over_cdp("http://127.0.0.1:9337")
```

注意：**必须在同一个 Bash shell 内启停**。用 `run_in_background` 起 Chrome 再单独跑脚本，
Chrome 会随前一个 shell 退出而被杀掉。写成「一条命令里 Popen → 采集 → terminate」。

可用 URL：`https://flights.ctrip.com/online/list/oneway-<from>-<to>?depdate=YYYY-MM-DD&cabin=Y`
页面自带**低价日历**，一次能拿到前后 7 天价格，非常适合做「节假日 vs 平日」对比。

抓价基准日怎么选：用户要「平日参考价」时，取**紧邻节假日之后那周的周三/周四**
（如国庆 → 取 10/14-10/16），可比性最强。

## 三、携程酒店 ⚠️ 成功率低

已试过的路：
- `hotels.ctrip.com` 搜索框能输入城市并弹出下拉建议，但**点击建议项后拿不到 cityId**
- `m.ctrip.com/webapp/hotel/D<省>_<city>` 移动端 URL —— 需先知 cityId
- `trip.com/hotels/<城市>-hotels-list-<id>` —— 页面为纯 JS 渲染，取不到结构化价格

已知 cityId（供参考）：西江千户苗寨 = `21286`（属雷山县）。

**降级方案**：用早前抓到的价格区间 + 小红书实测帖提到的住宿区域与价位，
并在交付时**如实说明这是区间估算而非实时抓取**。别硬凑一个精确数字。

## 四、神州租车 ❌ 抓不到

| 入口 | 结果 |
|---|---|
| `zuche.com/gz/carlist/?cityId=...` | ❌ "您访问的连接过期或无效" |
| `zuche.com/gz/`、`zuche.com/carlist/list?...` | ❌ 空壳页（约 228 字） |
| `m.zuche.com` | ❌ 空白 SPA，需 App 端交互 |
| `car.ctrip.com` | ❌ 空壳页 |

**替代：用神州官方公开价目计算**，并在预算表里明确标注口径。神州收费结构：

- 车辆租赁及服务费（按日）：经济型 ¥120-200 / 中型 ¥200-300 / **SUV ¥300-500**
- **基础服务费 ≈ ¥40/天**（必购，覆盖 1500 元以内车损）← 这就是「最低档保险」
- 尊享服务费 ≈ ¥50/天（可选，含轮胎玻璃，7 天封顶）← 更高档
- 手续费 ≈ ¥20/单，车辆整备费 ≈ ¥20/单
- 夜间取还车（21:00-08:00）¥35-50/次；未满油还车补差价 + ¥100 加油服务费；
  清洁费约 ¥100；超时超 4h 按 1 天计
- 节假日价格**上浮 20%-50%**，热门车型可能翻倍
- 7 天以上享周租折扣 5%-15%

用户说「每天额外购买最低档位的保险」 → 取**基础服务费 ¥40/天**，且**必须计入总预算**，
不能只报裸车租金。

## 五、通用防坑

- **永远同时落盘 `.txt`（inner_text）和 `.png`（截图）**。纯 JS 页面文本为空时，
  看截图比反复猜选择器快得多（本次就是靠 `hotel_dropdown.png` 一眼看清下拉结构）。
- **不要在同一个入口上反复重试**：同一个 URL 连续三次失败就换入口或直接降级，
  重试次数的边际收益极低，浪费的是 token 和等待时间。
- **并行而非串行**：多城市、多站点的抓价一次性批量发起，总耗时取决于最慢的那个，
  不要一个一个排队等。
- 抓取脚本统一放 `<项目>/prices/`，输出文件名带上业务标识
  （如 `flight_szx_kwe_1001.txt`），方便回读。
