"""药剂出入业务规则：状态流转、字段校验、结存计算与筛选口径都收在这里。

结存口径（列表、详情、导出、概览共用同一份计算，避免各处对不上）：
- 按「药剂名称 + 规格型号」视为同一药剂，按单据编号（id 递增）逐单滚动；
- 出入数量为带符号数量：正数入库、负数出库；
- 只有「已出入库」单据参与结存：待审核、已审核的单据尚未生效，已作废单据整单冲回；
- 因此重复点「确认出入库」不会重复累计，作废后结存自动扣除，无需在行上打补丁。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "chemical"
REQUIRED_FIELDS = ["单据编号", "药剂名称", "规格型号", "出入数量"]
OPTIONAL_FIELDS = ["供应商", "经办人员"]
STATUS_ORDER = ["待审核", "已审核", "已出入库", "已作废"]
EFFECTIVE_STATUS = "已出入库"
# 各动作允许的前置状态：不符合就拦下并说明原因，杜绝跨状态操作与重复提交。
ACTION_FLOW = {
    "审核单据": {"from": ["待审核"], "to": "已审核", "done": "已审核"},
    "确认出入库": {"from": ["已审核"], "to": "已出入库", "done": "已确认出入库"},
    "作废单据": {"from": ["待审核", "已审核", "已出入库"], "to": "已作废", "done": "已作废"},
}
PENDING_STATUSES = ["待审核", "已审核"]


def _to_number(raw: Any) -> float | None:
    """把出入数量转成数字；转不了返回 None，交由调用方给出可读的错误说明。"""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _pretty(value: float) -> int | float:
    """整数数量去掉小数点，和列表里既有展示保持一致。"""
    return int(value) if float(value).is_integer() else round(value, 2)


class ChemicalService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        name: str | None = None,
        spec: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("单据编号", ""))]
        if name:
            rows = [row for row in rows if name in str(row.get("药剂名称", ""))]
        if spec:
            rows = [row for row in rows if spec in str(row.get("规格型号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        balances, _ = self._compute_balances()
        items = [self._decorate(row, balances) for row in rows]
        start = max(page - 1, 0) * size
        return items[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None
        balances, _ = self._compute_balances()
        return self._decorate(row, balances)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        quantity = _to_number(values.get("出入数量"))
        if quantity is None:
            return None, "出入数量必须是数字：正数表示入库，负数表示出库"
        code = str(values.get("单据编号")).strip()
        if any(str(row.get("单据编号", "")).strip() == code for row in store.rows(MODULE)):
            return None, f"单据编号 {code} 已存在，请勿重复登记"
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in ["单据编号", "药剂名称", "规格型号"]:
            entry[field] = str(values.get(field)).strip()
        entry["出入数量"] = _pretty(quantity)
        for field in OPTIONAL_FIELDS:
            entry[field] = values.get(field, "")
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        balances, _ = self._compute_balances()
        return self._decorate(entry, balances), None

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"药剂单据 {entry_id} 不存在或已归档"
        rule = ACTION_FLOW.get(action)
        if rule is None:
            return None, f"动作「{action}」不属于药剂出入可执行范围"
        current = str(entry.get("status"))
        target = rule["to"]
        if current == target:
            return None, f"单据当前已是「{target}」状态，请勿重复提交，结存不会重复累计"
        if current == STATUS_ORDER[-1]:
            return None, "单据已作废，不能再执行该动作；如需调整请重新登记单据"
        if current not in rule["from"]:
            if action == "确认出入库":
                return None, f"单据当前为「{current}」，需先审核单据后才能确认出入库"
            return None, f"单据当前为「{current}」，不能执行「{action}」"
        entry["status"] = target
        entry["pending"] = target in PENDING_STATUSES
        # 药剂出入没有“异常”业务态：作废是正常冲回，不能计入概览异常量。
        entry["abnormal"] = False
        balances, _ = self._compute_balances()
        if action == "作废单据" and current == EFFECTIVE_STATUS:
            message = "药剂单据已作废，其出入数量已从结存冲回"
        else:
            message = f"药剂单据{rule['done']}"
        return self._decorate(entry, balances), message

    def stats(self) -> dict[str, int | float]:
        """页面顶部三张卡片：与列表同一份结存口径，保证概览和列表同步。"""
        rows = store.rows(MODULE)
        balances, stock = self._compute_balances()
        outbound = 0.0
        for row in rows:
            if row.get("status") == EFFECTIVE_STATUS:
                quantity = _to_number(row.get("出入数量"))
                if quantity is not None and quantity < 0:
                    outbound += abs(quantity)
        return {
            "待审核单据": sum(1 for row in rows if row.get("status") == "待审核"),
            "累计药剂出库": _pretty(outbound),
            "结存偏低药剂": sum(1 for value in stock.values() if value <= 0),
        }

    def export_entries(self) -> list[dict[str, Any]]:
        """导出全量清单：结存与列表保持同一口径。"""
        balances, _ = self._compute_balances()
        return [self._decorate(row, balances) for row in store.rows(MODULE)]

    def _compute_balances(
        self,
    ) -> tuple[dict[int, int | float], dict[tuple[str, str], int | float]]:
        """滚动计算每张单据的结存数量，以及每种药剂的当前结存。

        只累计「已出入库」单据；待审核/已审核/已作废单据展示的是当前库存，
        其自身数量不参与，重复确认或作废都不会污染结存。
        """
        balances: dict[int, int | float] = {}
        stock: dict[tuple[str, str], float] = {}
        rows = sorted(store.rows(MODULE), key=lambda row: int(row.get("id", 0)))
        for row in rows:
            key = (str(row.get("药剂名称", "")), str(row.get("规格型号", "")))
            if row.get("status") == EFFECTIVE_STATUS:
                quantity = _to_number(row.get("出入数量"))
                stock[key] = stock.get(key, 0.0) + (quantity or 0.0)
            balances[int(row.get("id", 0))] = _pretty(stock.get(key, 0.0))
        return balances, {key: _pretty(value) for key, value in stock.items()}

    def _decorate(
        self, row: dict[str, Any], balances: dict[int, int | float]
    ) -> dict[str, Any]:
        """列表/详情/导出统一出口：结存取派生值，单据状态取真实状态。"""
        item = dict(row)
        item["结存数量"] = balances.get(int(row.get("id", 0)), 0)
        item["单据状态"] = row.get("status")
        return item
