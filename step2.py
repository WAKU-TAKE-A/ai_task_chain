from task_state import TaskState

def main():
    status = TaskState("task_status.json")
    
    # 未着手のアイテムを1つ取得し、処理中(processing)に移行する
    next_item = status.start_process()

    if next_item is not None:
        print(f"[INFO] Started processing item: {next_item}")
        print("[OK] step2 finished. Target data prepared.")
    else:
        error_msg = "[WARNING] No pending items found."
        print(error_msg)
        status.set_error(error_msg)

if __name__ == "__main__":
    main()
