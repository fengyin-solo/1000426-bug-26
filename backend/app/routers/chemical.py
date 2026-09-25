"""药剂出入接口：维护药剂单据，覆盖审核单据、确认出入库、作废单据等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.chemical import ChemicalService

router = APIRouter(prefix="/api/chemical", tags=["药剂出入"])

service = ChemicalService()

LIST_FIELDS = ["单据编号", "药剂名称", "规格型号", "出入数量", "结存数量", "供应商", "经办人员", "单据状态"]
STATUSES = ["待审核", "已审核", "已出入库", "已作废"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按单据编号检索"),
    name: str | None = Query(default=None, description="按药剂名称检索"),
    spec: str | None = Query(default=None, description="按规格型号检索"),
    status: str | None = Query(default=None, description="待审核、已审核、已出入库、已作废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按单据编号、药剂名称、规格型号与状态过滤药剂出入列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword, name=name, spec=spec, status=status, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def entry_stats() -> dict[str, Any]:
    """药剂出入概览卡片：结存口径与列表完全一致。"""
    return service.stats()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出药剂出入清单：返回当前全量数据，结存与列表同源。"""
    items = service.export_entries()
    return {"module": "chemical", "total": len(items), "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条药剂单据明细；不存在时给出可读的错误说明。

    结存数量与列表走同一套计算，刷新或重新进入不会出现详情、列表不一致。
    """
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"药剂单据 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条药剂单据，缺字段或数量非法时说明原因而不是静默丢弃。"""
    entry, message = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message or "药剂单据登记失败")
    return ActionResult(ok=True, message="药剂单据已登记，等待审核", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条药剂单据执行审核单据、确认出入库、作废单据；不允许的动作会被拦下并说明原因。

    重复提交同一动作返回明确提示且不重复计算结存；已出入库单据作废时结存自动冲回。
    """
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
