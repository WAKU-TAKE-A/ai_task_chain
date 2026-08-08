from task_state import TaskState

def main():
    status = TaskState("task_status.json")
    
    # ここに好きな汎用リストを渡すだけでOK
    # 様々なデータ型の混ざったリストを渡すことが可能です
    target_data = [
        "item1",
        "item2",
        "item3"
    ]
    
    status.init(target_data)
        
    print("[OK] step1 finished. task_status.json created using TaskState.")

if __name__ == "__main__":
    main()
