# Python MiniDB：BusTub 四项目教学原型

> PROTOTYPE：这是帮助理解数据库内部状态的抛弃式原型，不是 BusTub 的 Python
> 移植，也不是可用于生产的数据存储。

运行：

```bash
uv run python -m examples.minidb_prototype.demo
```

一次运行会依次展示：

1. P1：7 行数据如何挤进 3 个 frame；可扩展哈希怎样记录
   `page_id -> frame_id`；LRU-K 怎样区分 cold/hot；PageGuard 怎样配平
   Pin/Unpin。
2. P2：唯一主键依次插入 B+ 树后，叶子怎样分裂，内部节点怎样指路，范围
   查询怎样沿叶子链前进。
3. P3：`id = 7` 怎样从全表扫描变成索引点查；`Sort + Limit` 怎样变成
   `TopN`；谓词下推减少多少向上传递的行。
4. P4：两个线程怎样形成 `T1 -> T2 -> T1` 等待环；检测器怎样回滚较年轻
   的事务并唤醒另一个事务。

## 文件对应关系

| 文件 | 对应概念 |
| --- | --- |
| `storage.py` | 可扩展哈希、LRU-K、模拟磁盘、缓冲池、PageGuard |
| `table.py` | 按页保存行、RowId `(page_id, slot)` |
| `index.py` | B+ 树插入、分裂、点查、叶子链范围扫描 |
| `execution.py` | 结构化 Query、执行计划、索引点查、谓词下推、TopN |
| `concurrency.py` | X 锁、等待队列、waits-for 图、死锁回滚 |
| `demo.py` | 一键运行并打印每一层状态 |

## 第一版刻意省略

- 磁盘文件格式、页二进制编码和崩溃恢复；
- SQL Parser、Catalog、统计信息和成本优化器；
- B+ 树删除、节点页持久化和 latch crabbing；
- S/IX/IS/SIX 锁、锁升级和完整 RU/RC/RR 行为；
- WAL、MVCC、网络协议和生产级错误处理。

完整讲解和升级路线见
[`docs/python-minidb-learning-guide.md`](../../docs/python-minidb-learning-guide.md)。
