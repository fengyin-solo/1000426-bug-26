"""药剂出入业务规则：状态流转、字段校验、结存口径都收在这里。

结存数量不作为外部提交值：每次状态变化后按「同药剂名称 + 同规格型号」分组，
依据已出入库单据的出入数量做一次全量重算，因此：
- 确认出入库后结存必然随出入数量变化；
- 已作废单据不参与结存；
- 任何动作重复提交结果都一样，不会多算一次；
- 列表与详情读取的是同一份重算结果，不会出现两个结存值。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "chemical"
REQUIRED_FIELDS = ["单据编号", "药剂名称", "规格型号"]
OPTIONAL_FIELDS = ["出入数量", "出入类型", "供应商", "经办人员"]
STATUS_ORDER = ["待审核", "已审核", "已出入库", "已作废"]
ACTION_RULES = {"审核单据": "已审核", "确认出入库": "已出入库", "作废单据": "已作废"}
# 待审核、已审核都属于等待后续处理；已出入库、已作废均为终态。
PENDING_STATUSES = {"待审核", "已审核"}
DIRECTION_SIGNS = {"入库": 1, "出库": -1}
LOW_STOCK_THRESHOLD = 10

# 状态机：既有审核动作保持不变，只允许沿合法路径流转，
# 终态重复提交会被拦下，从根上避免结存重复累计。
ALLOWED_ACTIONS: dict[str, set[str]] = {
    "待审核": {"审核单据", "作废单据"},
    "已审核": {"确认出入库", "作废单据"},
    "已出入库": {"作废单据"},
    "已作废": set(),
}


class ChemicalService:
    # ---- 读取 ----------------------------------------------------------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        self.recompute_balances()
        rows = store.rows(MODULE)
        if keyword:
            keyword = keyword.strip()
            rows = [
                row
                for row in rows
                if keyword in str(row.get("单据编号", ""))
                or keyword in str(row.get("药剂名称", ""))
                or keyword in str(row.get("规格型号", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        self.recompute_balances()
        return store.find(MODULE, entry_id)

    def get_stats(self) -> dict[str, int]:
        balances = self.recompute_balances()
        rows = store.rows(MODULE)
        consumed = 0
        for row in rows:
            if row.get("status") == "已出入库" and str(row.get("出入类型") or "入库") == "出库":
                consumed += self._to_number(row.get("出入数量"))
        return {
            # 概览口径与列表一致：待审核按 status 统计，异常量不再把作废单据算进去。
            "pending_audit": sum(1 for row in rows if row.get("status") == "待审核"),
            "consumed": self._display(consumed),
            "low_stock": sum(1 for value in balances.values() if value < LOW_STOCK_THRESHOLD),
        }
    # ---- 写入 ----------------------------------------------------------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        doc_no = str(values.get("单据编号")).strip()
        if any(str(row.get("单据编号") or "").strip() == doc_no for row in store.rows(MODULE)):
            return None, f"单据编号「{doc_no}」已存在，重复登记会导致结存多算，请核对后再提交"

        quantity, message = self._parse_quantity(values.get("出入数量"))
        if message:
            return None, message
        direction = str(values.get("出入类型") or "入库").strip() or "入库"
        if direction not in DIRECTION_SIGNS:
            return None, "出入类型只允许填写「入库」或「出库」"

        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in OPTIONAL_FIELDS:
            if field in ("出入数量", "出入类型"):
                continue
            entry[field] = values.get(field)
        entry["出入类型"] = direction
        entry["出入数量"] = self._display(quantity)
        # 未审核单据不参与结存，结存数量统一交给重算逻辑回填。
        entry["结存数量"] = 0
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        self.recompute_balances()
        return entry, ""

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"药剂单据 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于药剂出入可执行范围"

        current = str(entry.get("status") or "")
        if action not in ALLOWED_ACTIONS.get(current, set()):
            target = ACTION_RULES[action]
            if current == target:
                return None, f"单据已是「{current}」状态，请勿重复提交，结存不会重复计算"
            if current == "已作废":
                return None, "已作废单据不可再执行任何动作，也不会计入结存"
            return None, f"当前状态「{current}」不允许执行「{action}」，请按审核、出入库的顺序流转"

        if action == "确认出入库":
            quantity, message = self._parse_quantity(entry.get("出入数量"))
            if message:
                return None, f"确认出入库失败：{message}"
            direction = str(entry.get("出入类型") or "入库").strip() or "入库"
            if direction not in DIRECTION_SIGNS:
                return None, "确认出入库失败：出入类型只允许「入库」或「出库」"
            if direction == "出库":
                balances = self.recompute_balances()
                key = self._group_key(entry)
                stock = balances.get(key, 0)
                if quantity > stock:
                    return None, f"出库数量 {self._display(quantity)} 大于当前结存 {self._display(stock)}，请先补足库存"

        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target in PENDING_STATUSES
        # 作废是正常的终态处置，不是异常；异常量因此不会再随作废累加。
        entry["abnormal"] = False
        self.recompute_balances()
        done = "作废" if action == "作废单据" else action
        return entry, f"药剂单据已{done}，结存已按最新出入数量刷新"

    # ---- 结存口径 ------------------------------------------------------
    def recompute_balances(self) -> dict[tuple[str, str], float]:
        """按已出入库单据重算每个药剂（名称+规格）的结存。

        作废、待审核、已审核单据一律不参与；重复调用是幂等的，
        所以任何动作重复触发都不会让结存多算。
        """
        rows = sorted(store.rows(MODULE), key=lambda row: int(row.get("id", 0)))
        balances: dict[tuple[str, str], float] = {}
        for row in rows:
            key = self._group_key(row)
            balances.setdefault(key, 0.0)
            if row.get("status") != "已出入库":
                continue
            direction = str(row.get("出入类型") or "入库").strip() or "入库"
            sign = DIRECTION_SIGNS.get(direction, 1)
            balances[key] = round(
                balances[key] + sign * self._to_number(row.get("出入数量")), 6
            )
            # 已入账单据：记录入库/出库发生后的累计结存快照。
            row["结存数量"] = self._display(balances[key])

        for row in rows:
            if row.get("status") == "已出入库":
                continue
            key = self._group_key(row)
            if row.get("status") == "已作废":
                # 作废单据不参与结存，列表/详情统一展示为「—」。
                row["结存数量"] = None
            else:
                # 待审核、已审核单据展示所在药剂的当前结存，方便核对出入数量。
                row["结存数量"] = self._display(balances.get(key, 0.0))
        return balances

    # ---- 工具 ----------------------------------------------------------
    @staticmethod
    def _group_key(row: dict[str, Any]) -> tuple[str, str]:
        return str(row.get("药剂名称") or ""), str(row.get("规格型号") or "")

    @staticmethod
    def _to_number(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _parse_quantity(self, value: Any) -> tuple[float, str]:
        text = str(value if value is not None else "").strip()
        if not text:
            return 0.0, "出入数量未填写，请补充非负数字后再提交"
        try:
            quantity = float(text)
        except ValueError:
            return 0.0, f"出入数量「{text}」不是有效数字，请填写非负数字"
        if quantity < 0:
            return 0.0, "出入数量不能为负数，出库请通过出入类型选择"
        return quantity, ""

    @staticmethod
    def _display(value: float) -> int | float:
        return int(value) if float(value).is_integer() else round(value, 6)
