from __future__ import annotations

from typing import Any

from config import ACTIVE_SEGMENT_PATH, COMPLETED_SEGMENTS_PATH, SEGMENT_QUEUE_PATH
from io_contract import load_json, save_json
from utils import ensure_dict, ensure_list


class QueueManager:
    def load_queue(self) -> dict[str, Any]:
        return load_json(SEGMENT_QUEUE_PATH, {"items": []})

    def save_queue(self, queue: dict[str, Any]) -> None:
        save_json(SEGMENT_QUEUE_PATH, queue)

    def list_items(self) -> list[dict[str, Any]]:
        queue = self.load_queue()
        return ensure_list(queue.get("items"))

    def push(self, item: dict[str, Any]) -> None:
        queue = self.load_queue()
        items = ensure_list(queue.get("items"))
        items.append(item)
        queue["items"] = items
        self.save_queue(queue)

    def push_many(self, items_to_add: list[dict[str, Any]]) -> None:
        queue = self.load_queue()
        items = ensure_list(queue.get("items"))
        items.extend(items_to_add)
        queue["items"] = items
        self.save_queue(queue)

    def peek(self) -> dict[str, Any] | None:
        items = self.list_items()
        return items[0] if items else None

    def pop_activate_next(self) -> dict[str, Any] | None:
        queue = self.load_queue()
        items = ensure_list(queue.get("items"))
        if not items:
            return None

        next_item = items.pop(0)
        queue["items"] = items
        self.save_queue(queue)

        active_payload = {
            "active": True,
            "item": next_item,
        }
        save_json(ACTIVE_SEGMENT_PATH, active_payload)
        return next_item

    def get_active(self) -> dict[str, Any]:
        return load_json(ACTIVE_SEGMENT_PATH, {"active": False, "item": None})

    def clear_active(self) -> None:
        save_json(ACTIVE_SEGMENT_PATH, {"active": False, "item": None})

    def mark_completed(self, completed_item: dict[str, Any]) -> None:
        registry = load_json(COMPLETED_SEGMENTS_PATH, {"items": []})
        items = ensure_list(registry.get("items"))
        items.append(completed_item)
        registry["items"] = items
        save_json(COMPLETED_SEGMENTS_PATH, registry)

    def completed_items(self) -> list[dict[str, Any]]:
        registry = load_json(COMPLETED_SEGMENTS_PATH, {"items": []})
        return ensure_list(registry.get("items"))

    # ------------------------------------------------------------------
    # Compatibility helpers for completion-first CycleManager
    # ------------------------------------------------------------------

    def get_active_item(self) -> dict[str, Any] | None:
        payload = self.get_active()
        if not ensure_dict(payload).get("active"):
            return None
        item = ensure_dict(payload).get("item")
        return ensure_dict(item) if isinstance(item, dict) else item

    def get_next_pending_item(self) -> dict[str, Any] | None:
        return self.peek()

    def enqueue_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """
        Add one queue item if segment_id not already present in queue/active/completed.
        Return the same item for convenience.
        """
        item = ensure_dict(item)
        segment_id = str(item.get("segment_id", "")).strip()
        if not segment_id:
            self.push(item)
            return item

        if self._segment_exists_anywhere(segment_id):
            return item

        self.push(item)
        return item

    def activate_item(self, item: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """
        If item is None:
            pop queue head and make it active.
        If item is provided:
            remove matching item from queue if present, then make it active.
            if already active, just return it.
        """
        current_active = self.get_active_item()
        if current_active:
            current_active_id = str(current_active.get("segment_id", "")).strip()
            requested_id = str(ensure_dict(item).get("segment_id", "")).strip() if item else ""
            if not item or (requested_id and requested_id == current_active_id):
                return current_active

        if item is None:
            return self.pop_activate_next()

        item = ensure_dict(item)
        target_id = str(item.get("segment_id", "")).strip()

        queue = self.load_queue()
        items = ensure_list(queue.get("items"))

        remaining_items: list[dict[str, Any]] = []
        matched_item: dict[str, Any] | None = None

        for queued in items:
            queued = ensure_dict(queued)
            queued_id = str(queued.get("segment_id", "")).strip()
            if target_id and queued_id == target_id and matched_item is None:
                matched_item = queued
                continue
            remaining_items.append(queued)

        queue["items"] = remaining_items
        self.save_queue(queue)

        active_item = matched_item or item
        save_json(ACTIVE_SEGMENT_PATH, {
            "active": True,
            "item": active_item,
        })
        return active_item

    def complete_active_item(self, write_result: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """
        Move current active item into completed registry.
        Merge write_result into completed payload for traceability.
        """
        active_payload = self.get_active()
        if not ensure_dict(active_payload).get("active"):
            return None

        active_item = ensure_dict(active_payload.get("item"))
        completed_item = dict(active_item)

        if isinstance(write_result, dict):
            completed_item["write_result"] = write_result
            completed_item["status"] = "completed"
            if "segment_id" not in completed_item and write_result.get("segment_id"):
                completed_item["segment_id"] = write_result["segment_id"]
        else:
            completed_item["status"] = "completed"

        self.mark_completed(completed_item)
        self.clear_active()
        return completed_item

    def mark_item_completed(
        self,
        queue_item: dict[str, Any],
        write_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Fallback completion method if caller passes queue_item directly.
        Also clears active if it matches the same segment_id.
        """
        queue_item = ensure_dict(queue_item)
        completed_item = dict(queue_item)
        completed_item["status"] = "completed"

        if isinstance(write_result, dict):
            completed_item["write_result"] = write_result

        self.mark_completed(completed_item)

        active_item = self.get_active_item()
        if active_item:
            active_id = str(active_item.get("segment_id", "")).strip()
            queue_id = str(queue_item.get("segment_id", "")).strip()
            if active_id and queue_id and active_id == queue_id:
                self.clear_active()

        return completed_item

    def ensure_segment_queue(
        self,
        story_plan: dict,
        min_pending: int = 3,
        refill_batch_size: int = 5,
    ) -> None:
        """
        Legacy prefill mode.
        For completion-first runtime, this can still be kept as optional behavior.
        """
        queued_items = self.list_items()
        queued_ids = {
            item["segment_id"]
            for item in queued_items
            if "segment_id" in item
        }

        active_item = self.get_active_item()
        active_ids = set()
        if active_item and "segment_id" in active_item:
            active_ids.add(active_item["segment_id"])

        done_ids = {
            item["segment_id"]
            for item in self.completed_items()
            if "segment_id" in item
        }

        existing_ids = queued_ids | done_ids | active_ids
        pending_count = len(queued_items)

        if pending_count >= min_pending:
            return

        sections = ensure_list(story_plan.get("sections"))
        new_items: list[dict[str, Any]] = []

        for section in sections:
            section = ensure_dict(section)
            section_id = str(section.get("section_id", "")).strip()
            if not section_id:
                continue

            section_title = section.get("title", section_id)
            planned_segments = int(section.get("planned_segments", 0) or 0)

            for ordinal in range(1, planned_segments + 1):
                sec_suffix = (
                    section_id.split("_")[-1] if "_" in section_id else section_id
                )
                seg_id = f"seg_{sec_suffix}_{ordinal:02d}"

                if seg_id in existing_ids:
                    continue

                new_items.append({
                    "segment_id": seg_id,
                    "section_id": section_id,
                    "status": "pending",
                    "title": f"{section_title}（Segment {ordinal}）",
                })
                existing_ids.add(seg_id)

                if len(new_items) >= refill_batch_size:
                    break

            if len(new_items) >= refill_batch_size:
                break

        if new_items:
            self.push_many(new_items)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _segment_exists_anywhere(self, segment_id: str) -> bool:
        segment_id = str(segment_id).strip()
        if not segment_id:
            return False

        for item in self.list_items():
            if str(ensure_dict(item).get("segment_id", "")).strip() == segment_id:
                return True

        active_item = self.get_active_item()
        if active_item and str(ensure_dict(active_item).get("segment_id", "")).strip() == segment_id:
            return True

        for item in self.completed_items():
            if str(ensure_dict(item).get("segment_id", "")).strip() == segment_id:
                return True

        return False