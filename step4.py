from task_state import TaskState, TaskStateError

def main():
    status = TaskState("task_status.json")
    
    try:
        # 処理中(processing)のものを完了(completed)にする。なければエラー。
        marked_item = status.complete_process()
        print(f"Completed '{marked_item}'.")
        print("[OK] step4 finished. Status advanced.")
        
    except TaskStateError as e:
        error_msg = f"[ERROR] {e}"
        print(error_msg)
        status.set_error(error_msg)
    except Exception as e:
        error_msg = f"[ERROR] Unexpected error: {e}"
        print(error_msg)
        status.set_error(error_msg)

if __name__ == "__main__":
    main()
