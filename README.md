# Dungeon Layout Generator

一个带程序化关卡布局生成能力的 FastAPI 服务。核心保证：**同一个
(seed, 参数, 算法版本) 在任意时刻、任意进程、任意请求顺序下产出完全一致的布局**。

## 运行

```bash
uv sync
uv run python main.py          # 启动服务（监听 127.0.0.1 随机端口）
uv run pytest                  # 运行全部测试
```

## 可复现性语义

- 布局由三元组 `(seed, GenerationParams, algorithm_version)` 完全决定。
- 所有随机性都经过 `app.rng.derive_rng`：对输入做 SHA-256 派生出
  `random.Random` 的种子。不依赖 `PYTHONHASHSEED`、进程状态、字典/集合
  迭代顺序或系统时间，因此跨进程、跨重启、跨请求顺序结果一致
  （`tests/test_determinism.py` 包含子进程复现验证）。
- 幂等键 `layout_id = sha256(seed | canonical(params))`：相同请求的并发或
  重复调用返回同一个布局对象（singleflight），生成工作只执行一次。
- 生成是纯函数，因此**中断恢复零成本**：任何失败/超时/取消之后重新发起
  相同请求，结果与一次性生成逐字节一致。服务只在结果通过全部约束校验后
  才原子地写入存储，失败不会留下半成品。

## 算法版本策略

- 每个算法版本独立实现于 `app/generator/v<N>.py`，并在
  `app/generator/__init__.py` 注册一次。
- **已发布的版本冻结**：任何生成规则的调整必须以新版本（如 `v3`）发布，
  老版本代码不允许修改。这样老种子永远能复现历史布局。
- `tests/test_versioning.py` 中冻结了各版本的金色指纹
  （`GOLDEN_V1` / `GOLDEN_V2`），任何导致已发布版本输出漂移的改动都会
  让测试失败。
- 请求可显式指定 `algorithm_version`；缺省使用 `DEFAULT_ALGORITHM_VERSION`
  （当前为 `v2`）。`GET /api/versions` 列出可用版本。
- 当前版本：
  - `v1`：顺序房间放置 + L 形走廊。
  - `v2`：BSP 划分 + 最小生成树走廊。

## 局部再生成

`POST /api/layouts/{id}/regenerate` 对指定矩形区域重新生成：

- 区域外的格子**逐字节保留**；
- 区域内用与原布局**相同的算法版本**重新生成子布局（风格一致）；
- 连通性通过在**区域内部**补走廊恢复（矩形内两点间的 L 形路径不会越界），
  因此缝合不会改动任何区域外的格子；
- 若区域不与任何可行走格子相邻（再生成会产生不可达孤岛），返回带具体
  坐标的错误，而不是悄悄产出坏布局；
- 再生成是 `(layout, region, sub_seed)` 的纯函数，重试结果完全一致；
- 仅 `draft` 状态、且角色为 `editor` 时可再生成。

## 约束校验

生成与再生成流程都会执行 `app.validation.validate_layout`，检查：

| 约束 | kind | 说明 |
|---|---|---|
| 边界 | `bounds` | 房间不得越出网格 |
| 重叠 | `overlap` | 房间矩形不得相交，违规定位到相交格 |
| 连通性 | `connectivity` | 所有可行走格必须四连通，违规定位到孤立区域代表格 |
| 可达性 | `reachability` | 每个房间中心必须可从 0 号房间到达，违规定位到房间中心 |

每个违规都携带 `(x, y)` 坐标与原因；校验失败时生成流程报错，**不会**
落库任何结果。

## 生命周期状态机

```
draft --(reviewer)--> locked --(publisher)--> published
locked --(reviewer)--> draft        # 解锁
published                            # 终态
```

- `draft`：可编辑（局部再生成）。
- `locked`：内容冻结，等待发布；可解锁回到 `draft`。
- `published`：终态，不可再变更。
- 每次转换校验角色（`TRANSITION_ROLES`），越权返回 403，非法转换返回 409。
- 同一布局的并发转换由 per-layout 锁串行化：结果确定，恰有一个请求成功，
  其余收到 409，绝不出现撕裂状态。
- 所有生成/再生成/状态转换都写入审计日志
  （`GET /api/layouts/{id}/audit`），包含操作者、动作、前后状态与修订号。

## 并发、超时与中断

- 相同 (seed, params) 的并发请求共享同一个 in-flight 任务（singleflight），
  对外幂等。
- 等待者通过 `asyncio.shield` 隔离：任一调用方取消/超时不会取消共享计算，
  也不影响其他等待者的结果。
- `timeout`（秒）作用于单次生成尝试；超时后按 `max_retries` 策略重试
  （默认 2 次额外尝试）。重试安全，因为生成是纯函数且失败不落库。
- 重试耗尽后返回 504，存储与审计中不留任何痕迹；后续健康请求可正常恢复。

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/layouts` | 生成布局（幂等）；body 含 seed、尺寸、房间数、`algorithm_version`、`timeout` |
| GET | `/api/layouts/{id}` | 读取布局 |
| POST | `/api/layouts/{id}/regenerate` | 局部再生成（需 `x-role: editor`，仅 draft） |
| POST | `/api/layouts/{id}/transition` | 状态转换（按目标状态要求角色） |
| GET | `/api/layouts/{id}/audit` | 审计日志 |
| GET | `/api/versions` | 可用算法版本 |

请求头：`x-actor`（操作者标识，写入审计）、`x-role`（`editor` /
`reviewer` / `publisher`，用于权限校验）。

## 测试

`uv run pytest` 覆盖：确定性（含跨进程复现）、版本冻结与区分、局部再
生成（区域外不变/连通性/纯函数）、约束违规定位、并发幂等/取消隔离/超时
重试/无半成品恢复、状态机合法性与并发确定性、HTTP 端到端流程。
