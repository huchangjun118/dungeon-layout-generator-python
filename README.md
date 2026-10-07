# Dungeon Layout Generator

基于 FastAPI 的程序化关卡布局生成服务。

## 快速开始

```bash
uv sync
uv run python main.py          # 启动服务
uv run pytest tests/ -q        # 运行测试（44 个）
```

## 示例

```bash
# 生成（幂等：相同 seed+params+version 永远得到相同布局）
curl -X POST localhost:8000/layouts/generate \
  -H 'content-type: application/json' \
  -d '{"seed": 42, "version": "v1",
       "params": {"width": 64, "height": 64, "room_count": 8,
                  "min_room_size": 4, "max_room_size": 10,
                  "extra_corridors": 1}}'

# 局部再生成 / 状态迁移 / 审计
curl -X POST localhost:8000/layouts/{layout_id}/regenerate \
  -d '{"region": {"x": 4, "y": 4, "w": 16, "h": 16}}'
curl -X POST localhost:8000/layouts/{layout_id}/transition \
  -d '{"target": "locked", "actor": "alice", "role": "editor"}'
curl localhost:8000/layouts/{layout_id}/audit
```

可复现性语义、版本策略、状态机含义、并发与恢复保证详见
[docs/design.md](docs/design.md)。
