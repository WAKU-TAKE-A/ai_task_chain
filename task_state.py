import json
import os

class TaskStateError(Exception):
    pass

class TaskState:
    def __init__(self, filepath="task_status.json"):
        self.filepath = filepath

    def _load(self):
        if not os.path.exists(self.filepath):
            raise TaskStateError(f"Status JSON file not found: {self.filepath}")
        try:
            with open(self.filepath, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception as exc:
            raise TaskStateError(f"Failed to load status JSON: {exc}")
            
        if not isinstance(data, dict) or "loop" not in data:
            raise TaskStateError("Status JSON must contain a 'loop' array.")
        return data

    def _save(self, data):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def init(self, items: list):
        """
        リストを受け取り、すべて 'pending' 状態で初期化する。
        文字列、数値、辞書など、JSON化可能なあらゆるデータを汎用的に受け付ける。
        """
        if not isinstance(items, list):
            items = [items]
        
        loop_data = [{"item": item, "status": "pending"} for item in items]
        data = {
            "error_flag": False,
            "error_message": "",
            "loop": loop_data
        }
        self._save(data)

    def set_error(self, message: str = "An error occurred"):
        """JSONファイルにエラーフラグを立てて保存する"""
        try:
            data = self._load()
        except TaskStateError:
            # ロード自体が失敗する場合は新規作成して強制上書き
            data = {"error_flag": True, "error_message": message, "loop": []}
            
        data["error_flag"] = True
        data["error_message"] = message
        self._save(data)

    def clear(self):
        """ファイルを削除し、ステータスをクリアする"""
        if os.path.exists(self.filepath):
            os.remove(self.filepath)

    def start_process(self):
        """
        次に処理すべきアイテム（pending）を取得し、ステータスを 'processing' に変更して保存する。
        見つからない場合は None を返す。
        """
        try:
            data = self._load()
            for entry in data.get("loop", []):
                if entry.get("status") == "pending":
                    entry["status"] = "processing"
                    self._save(data)
                    return entry.get("item")
            return None
        except TaskStateError:
            return None

    def complete_process(self, target_item=None):
        """
        現在 'processing' 状態のアイテムを 'completed' にする。
        processing状態のアイテムが存在しない場合は例外（エラー）を発生させる。
        完了処理を行ったアイテムを返す。
        """
        data = self._load()
        updated = False
        marked_item = None

        for entry in data.get("loop", []):
            if entry.get("status") == "processing":
                # ターゲット指定がないか、またはターゲットと一致した場合に更新
                if target_item is None or entry.get("item") == target_item:
                    entry["status"] = "completed"
                    marked_item = entry.get("item")
                    updated = True
                    break
        
        if not updated:
            raise TaskStateError(f"No item is currently 'processing' (target: {target_item}). Cannot mark as completed.")
            
        self._save(data)
            
        return marked_item

    def get_summary(self):
        """
        全件数、完了数、残り件数を返す（Flaskサーバーでの制御用）。
        """
        data = self._load()
        loop_items = data.get("loop", [])
        completed_count = 0
        remaining_count = 0

        for entry in loop_items:
            status = str(entry.get("status", "")).strip().lower()
            if status in ["complete", "completed"]:
                completed_count += 1
            else:
                remaining_count += 1

        return {
            "all_completed": remaining_count == 0,
            "total": len(loop_items),
            "completed": completed_count,
            "remaining": remaining_count,
            "error_flag": data.get("error_flag", False),
            "error_message": data.get("error_message", "")
        }
