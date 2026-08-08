import argparse
import json
import os
import threading
from pathlib import Path

from flask import Flask, Response, request

# ============================================================================
# Flask Application
# ============================================================================
app = Flask(__name__)
VERSION = "0.9.0.0"

# ============================================================================
# Task Chain Flow Configuration
# ============================================================================
# ステップの進行やループをここで簡単に定義できます。
# - next: 通常の次のステップ番号（指定がない場合は終了）
# - check_status: True にすると process_status.json を確認します
# - loop_back_to: check_status の結果、未完了ファイルがある場合に戻るステップ番号
# （全件完了の場合は next に指定されたステップへ進みます）
CHAIN_FLOW = {
    1: {"next": 2},       # 初期化・全体の準備処理
    2: {"next": 3},       # 【ループ開始】個別データの準備
    3: {"next": 4},       # AIによる自律評価・処理
    4: {"next": 5, "check_status": True, "loop_back_to": 2}, # ステータス更新（未完了なら2へ戻る、完了なら5へ）
    5: {"next": None}     # 全件完了後の最終処理（終了）
}

from task_state import TaskState, TaskStateError

# ============================================================================
# Task Chain State
# ============================================================================
STATE_LOCK = threading.Lock()

CHAIN_STATE = {
    "initialized": False,
    "current_step": None,
    "finished": False,
    "error_flag": False,
    "error_message": None,
    "global_step_counter": 0,
}

TASK_STATUS_JSON = None

# ============================================================================
# Step Instructions Configuration
# ============================================================================
import re
from datetime import datetime

def get_step_instructions(step_number, global_step=None):
    instructions = {
        1: """
========================================================================
[Step 1] Initialize
========================================================================
[Objective]
Initialization

[Execution Instructions for AI]
1. Run the following command:
   python step1.py
2. Check the command output. If it outputs [OK], access /next and proceed to Step 2.
   If an error occurs, STOP immediately and report to the user.

[Caution for AI]
- [HIGHEST PRIORITY] Following instructions exactly as written is the most critical requirement.
- NEVER create additional scripts (.py) for work, evaluation, loop control, etc.
- Always use the specified scripts.
""",
        2: """
========================================================================
[Step 2] Step2(loop start)
========================================================================
[Objective]
Loop start

[Execution Instructions for AI]
1. Run the following command:
   python step2.py
2. Check the command output. If it outputs [OK], access /next and proceed to Step 3.

[Caution for AI]
- [HIGHEST PRIORITY] Following instructions exactly as written is the most critical requirement.
- NEVER create additional scripts (.py) for work, evaluation, loop control, etc.
- Always use the specified scripts.   
""",
        3: """
========================================================================
[Step 3] Step3
========================================================================
[Objective]
For example, let AI evaluate

[Execution Instructions for AI]
1. Write the processing tasks you want the AI to perform here.
2. When complete, access /next on the Flask server.

[Caution for AI]
- [HIGHEST PRIORITY] Following instructions exactly as written is the most critical requirement.
- NEVER create additional scripts (.py) for work, evaluation, loop control, etc.
- The AI must perform data processing and judgment directly. NEVER perform evaluation using programs or scripts.
""",
        4: """
========================================================================
[Step 4] Step4(Loop Control)
========================================================================
[Objective]
Check loop termination

[Execution Instructions for AI]
1. Run the following command:
   python step4.py
2. Check the command output. If it outputs [OK], access /next on the Flask server.

[Caution for AI]
- [HIGHEST PRIORITY] Following instructions exactly as written is the most critical requirement.
- NEVER create additional scripts (.py) for work, evaluation, loop control, etc.
- Always use the specified scripts.
""",
        5: """
========================================================================
[Step 5] Finalize
========================================================================
[Objective]
Finalization

[Execution Instructions for AI]
1. Run the following command:
   python step5.py
2. Check the command output. If it outputs [OK], access /next to terminate the chain.

[Caution for AI]
- [HIGHEST PRIORITY] Following instructions exactly as written is the most critical requirement.
- NEVER create additional scripts (.py) for work, evaluation, loop control, etc.
- Always use the specified scripts.
"""
    }

    if step_number not in instructions:
        base_instruction = f"""
========================================================================
[Step {step_number}] Instruction Missing
========================================================================
[Objective]
Instructions are not defined.

[Execution Instructions for AI]
1. No specific instructions are provided for this step in the main script.
2. Report to the user: "Instructions for Step {step_number} seem to be missing." and STOP processing immediately.
3. NEVER proceed autonomously based on your own judgment.

[Caution for AI]
- [HIGHEST PRIORITY] Following instructions exactly as written is the most critical requirement.
- NEVER create additional scripts (.py) for work, evaluation, loop control, etc.
"""
    else:
        base_instruction = instructions[step_number].strip()

    # 表示上のステップ番号を書き換える
    if global_step is not None:
        base_instruction = re.sub(r"\[Step \d+\]", f"[Step {global_step}]", base_instruction)

    # タイムスタンプを付与
    now_str = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    base_instruction += f"\n\n[Timestamp]\n{now_str}"
    
    return base_instruction


# ============================================================================
# Response Generators
# ============================================================================
def make_text_response(text, status_code=200, step=None):
    response = Response(text.rstrip() + "\n", status=status_code, content_type="text/plain; charset=utf-8")
    if step is not None:
        response.headers["X-Task Chain-Step"] = str(step)
    return response

def get_base_url():
    return request.url_root.rstrip("/")


# ============================================================================
# Flask Routes
# ============================================================================
@app.route("/", methods=["GET"])
def show_root():
    if CHAIN_STATE.get("error_flag"):
        state_text = "Error (Task Chain Interrupted)"
    elif CHAIN_STATE["finished"]:
        state_text = "Finished"
    elif CHAIN_STATE["initialized"]:
        state_text = f"Step {CHAIN_STATE['current_step']}"
    else:
        state_text = "Uninitialized"

    return make_text_response(
        f"AI Task Chain v{VERSION}\nState: {state_text}\nInit: {get_base_url()}/init\nNext: {get_base_url()}/next\nStatus File: {TASK_STATUS_JSON}"
    )

@app.route("/status", methods=["GET"])
def get_status():
    with STATE_LOCK:
        current_step = CHAIN_STATE.get("current_step")
        is_init = CHAIN_STATE.get("initialized", False)
        is_finished = CHAIN_STATE.get("finished", False)
        error_flag = CHAIN_STATE.get("error_flag", False)

    status_str = "Error" if error_flag else ("Finished" if is_finished else (f"Running (Step {current_step})" if is_init else "Uninitialized"))
    
    summary_str = ""
    try:
        if TASK_STATUS_JSON and TASK_STATUS_JSON.is_file():
            status_manager = TaskState(TASK_STATUS_JSON)
            summary = status_manager.get_summary()
            summary_str = f"\nItems: {summary['completed']}/{summary['total']} completed ({summary['remaining']} remaining)"
            if summary.get("error_message"):
                summary_str += f"\nError Message: {summary['error_message']}"
    except Exception:
        pass

    return make_text_response(f"Task Chain Status: {status_str}{summary_str}", status_code=200)

@app.route("/init", methods=["GET", "POST"])
def initialize_chain():
    with STATE_LOCK:
        first_step = min(CHAIN_FLOW.keys()) if CHAIN_FLOW else 1

        CHAIN_STATE.update({
            "initialized": True, 
            "current_step": first_step, 
            "finished": False,
            "error_flag": False, 
            "error_message": None,
            "global_step_counter": 1
        })

        if TASK_STATUS_JSON:
            try:
                status_manager = TaskState(TASK_STATUS_JSON)
                status_manager.clear()
            except Exception:
                pass

        return make_text_response(get_step_instructions(first_step, CHAIN_STATE["global_step_counter"]), status_code=200, step=CHAIN_STATE["global_step_counter"])

@app.route("/next", methods=["GET", "POST"])
def next_chain_step():
    if request.method == "HEAD":
        return make_text_response("", status_code=200)

    with STATE_LOCK:
        # 全ステップ共通：JSONのステータス管理ファイルが存在すればエラーを同期する
        try:
            if TASK_STATUS_JSON and TASK_STATUS_JSON.is_file():
                status_manager = TaskState(TASK_STATUS_JSON)
                result = status_manager.get_summary()
                
                if result.get("error_flag"):
                    CHAIN_STATE["error_flag"] = True
                    CHAIN_STATE["error_message"] = result.get("error_message") or "Triggered by script."
        except TaskStateError:
            pass # 初期化前などで読めない場合はスキップ

        if CHAIN_STATE.get("error_flag"):
            err_reason = CHAIN_STATE.get("error_message") or "Unknown error"
            msg = (
                f"[ERROR] Task Chain execution has been interrupted.\n"
                f"Reason: {err_reason}\n\n"
                f"[Action Required]\n"
                f"Please resolve the underlying issue. Then, restart the chain from the beginning by accessing /init."
            )
            return make_text_response(msg, status_code=403)

        if not CHAIN_STATE["initialized"]:
            return make_text_response("[ERROR] Task Chain not initialized. Call /init first.", status_code=409)
            
        if CHAIN_STATE["finished"]:
            return make_text_response("[FINISHED] Task Chain is already complete.", status_code=410)

        current_step = CHAIN_STATE["current_step"]
        step_config = CHAIN_FLOW.get(current_step)

        if not step_config:
            return make_text_response(f"[ERROR] Step {current_step} is not defined in CHAIN_FLOW.", status_code=500)

        # ステータス確認とループ処理
        if step_config.get("check_status"):
            try:
                status_manager = TaskState(TASK_STATUS_JSON)
                result = status_manager.get_summary()
            except TaskStateError as exc:
                return make_text_response(f"[ERROR] Failed to check status JSON.\n{exc}", status_code=500, step=current_step)

            if result["all_completed"]:
                # 全件完了の場合、nextステップに進む（なければ終了）
                next_step = step_config.get("next")
                if next_step is None:
                    CHAIN_STATE["finished"] = True
                    CHAIN_STATE["current_step"] = None
                    return make_text_response("\n[Task Chain finished]\nAll tasks are complete.\n", status_code=200)
                else:
                    CHAIN_STATE["current_step"] = next_step
                    CHAIN_STATE["global_step_counter"] += 1
                    return make_text_response(get_step_instructions(next_step, CHAIN_STATE["global_step_counter"]), status_code=200, step=CHAIN_STATE["global_step_counter"])

            # 未完了があれば指定のステップに戻る
            loop_to = step_config.get("loop_back_to", 1)
            CHAIN_STATE["current_step"] = loop_to
            CHAIN_STATE["global_step_counter"] += 1
            return make_text_response(get_step_instructions(loop_to, CHAIN_STATE["global_step_counter"]), status_code=200, step=CHAIN_STATE["global_step_counter"])
        
        # 通常の次のステップへ
        else:
            next_step = step_config.get("next")
            if next_step is None:
                # next が指定されていない場合は終了とみなす
                CHAIN_STATE["finished"] = True
                CHAIN_STATE["current_step"] = None
                return make_text_response("\n[Task Chain finished]\nAll tasks are complete.\n", status_code=200)

            CHAIN_STATE["current_step"] = next_step
            CHAIN_STATE["global_step_counter"] += 1
            return make_text_response(get_step_instructions(next_step, CHAIN_STATE["global_step_counter"]), status_code=200, step=CHAIN_STATE["global_step_counter"])


@app.route("/error", methods=["POST"])
def set_error_flag():
    """
    外部からエラーフラグを立ててチェーンを中断するためのエンドポイント
    """
    with STATE_LOCK:
        CHAIN_STATE["error_flag"] = True
        error_msg = request.form.get("message") or request.json.get("message") if request.is_json else None
        final_msg = error_msg or "[ERROR] Task Chain execution was externally interrupted."
        CHAIN_STATE["error_message"] = final_msg
        
        # JSON側にもエラーフラグを確実に連動させる
        try:
            if TASK_STATUS_JSON:
                status_manager = TaskState(TASK_STATUS_JSON)
                status_manager.set_error(final_msg)
        except Exception as e:
            print(f"[WARNING] Failed to sync error to JSON: {e}")

        return make_text_response("Error flag has been set and synced to JSON.", status_code=200)


@app.errorhandler(404)
def handle_not_found(_error):
    return make_text_response("404 Not Found", status_code=404)
@app.errorhandler(405)
def handle_method_not_allowed(_error):
    return make_text_response("405 Method Not Allowed", status_code=405)
@app.errorhandler(500)
def handle_internal_server_error(error):
    return make_text_response("500 Internal Server Error", status_code=500)

# ============================================================================
# Main Entry Point
# ============================================================================
def main():
    global TASK_STATUS_JSON
    parser = argparse.ArgumentParser(description="AI Task Chain Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--status_json", default="task_status.json")
    args = parser.parse_args()

    TASK_STATUS_JSON = Path(os.path.abspath(os.path.expanduser(args.status_json)))

    print("========================================================================")
    print("AI Task Chain Server Started")
    print(f"Host/Port: {args.host}:{args.port}")
    print(f"Status File: {TASK_STATUS_JSON}")
    print("========================================================================")

    app.run(host=args.host, port=args.port, debug=False, threaded=True, use_reloader=False)

if __name__ == "__main__":
    main()
