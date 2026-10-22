# 物流接口

按运单号查物流状态。

```
GET {LOGISTICS_API_BASE}/track?no=<运单号>
```

响应是 JSON：

```json
{"no": "SF1234567890", "status": "运输中"}
```

- `no`：请求里的运单号
- `status`：物流状态，例如「运输中」「派送中」「已签收」

运单号不存在时返回 404。
