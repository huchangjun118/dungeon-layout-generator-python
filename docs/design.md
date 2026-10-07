# Dungeon Layout Generator — 设计说明

## 可复现性语义（Reproducibility）

布局由三元组 **`(seed, params, generator_version)`** 唯一决定：

- 相同三元组在**任意时刻、任意进程、任意请求顺序**下产出**逐字节一致**的布局
  （以 `content_hash` = 规范化 JSON 的 SHA-256 判定）。
- 所有随机性都经过 `app.rng.derive_seed`（SHA-256 派生，非 Python 内置
  `hash()`，不受进程盐值影响），不使用系统时间、线程调度或字典迭代顺序等
  任何非确定性来源。
- 幂等键 `key = sha256(version | seed | params.canonical_json)`，
  `layout_id = "L-" + key[:16]`，二者都是输入的纯函数，因此缓存命中与否、
  并发先后、进程重启都不影响结果。

## 版本策略（Versioning）

- 每个算法版本是一个实现了 `LayoutGenerator` 协议的类，注册在
  `app.generators` 的注册表中（当前：`v1`、`v2`，默认取最新）。
- **版本一旦发布即冻结**：对已发布版本的任何行为修改都是禁止的，
  由 `test_no_drift_within_version` 与跨进程黄金哈希测试保障。
- 调整生成规则 = 新增一个版本（如 `v3`）。老种子通过显式指定老版本号
  永远可以复现历史布局；布局中持久化了 `generator_version` 字段，可追溯。
- 请求不带版本时使用最新版本；版本号未知返回 404。

## 局部再生成（Regional Regeneration）

`POST /layouts/{id}/regenerate`：

1. 与区域相交的房间/走廊被移除，**区域外内容逐字节保留**；
2. 替换房间由 `(version, seed, params, region)` 派生的独立 RNG 放置，
   再生成本身也是完全确定性的；
3. 连通性修复（`_stitch`）以确定性的最近点对顺序把剩余连通分量缝合起来，
   保证与周边无缝衔接、整体连通；
4. 结果必须通过全部约束校验才会落库，revision 单调递增。
5. 仅 `draft` 状态的布局可再生成。

## 约束校验（Validation）

生成与再生成流程中强制执行，**不通过则拒绝产出**（HTTP 422）：

| 约束 | code | 定位信息 |
|---|---|---|
| 房间重叠 | `overlap` | 重叠区域的每一个瓦片坐标 |
| 越界 | `out_of_bounds` | 越界房间角点 / 走廊瓦片 |
| 连通性 | `disconnected` | 每个连通分量的代表瓦片 |
| 可达性 | `unreachable` | 不可达房间的中心坐标 |

## 并发、超时与中断恢复

- **幂等并发**：`jobs` 表的主键 + `INSERT OR IGNORE` 保证同一 key 只有
  一个执行者；其余请求等待同一行并读取同一份结果。
- **超时隔离**：等待方超时只是停止等待（HTTP 504），不影响执行者；
  执行者失败/被取消时在 `finally` 语义下释放 job 行，**不留半成品**。
- **重试策略**：失败/被取消的 claim 会被清除，后续请求（或同请求的
  有限重试，最多 3 次）重新生成；由于生成是纯函数，重试结果与一次性
  生成完全一致。
- **崩溃恢复**：进程重启后 `recover()`（或 `POST /admin/recover`）清除
  崩溃遗留的 `running` job，下一次请求确定性地重新生成出相同布局。
  持久化使用 SQLite，跨重启保持幂等。

## 状态机与权限（Lifecycle）

```
DRAFT --(editor)--> LOCKED --(admin)--> PUBLISHED
LOCKED --(editor)--> DRAFT        PUBLISHED = 终态
```

- `draft`：可再生成、可锁定；
- `locked`：内容冻结（不可再生成），可发布或解锁回草稿；
- `published`：终态，对外不可变。
- 非法迁移或越权（如 viewer 锁定、editor 发布）一律拒绝（HTTP 409）；
- 状态迁移用 `UPDATE ... WHERE status=expected` 的 CAS 实现：并发下
  **恰好一个**迁移成功，结果确定；每次成功迁移写入 `audit` 表
  （actor、role、from、to、时间戳），可通过 `GET /layouts/{id}/audit`
  查询。

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/versions` | 可用版本与默认版本 |
| POST | `/layouts/generate` | 幂等生成（seed, params, version?, timeout_s?） |
| GET | `/layouts/{id}` | 查询布局 |
| POST | `/layouts/{id}/regenerate` | 局部再生成（region） |
| POST | `/layouts/{id}/transition` | 状态迁移（target, actor, role） |
| GET | `/layouts/{id}/audit` | 审计日志 |
| POST | `/admin/recover` | 恢复崩溃遗留的 job |
