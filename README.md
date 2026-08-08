# AI Task Chain (v0.9.0.0)

このディレクトリに含まれる `main_template.py` は、AIに対して複雑な処理を小分けのステップで実行させるための、コンパクトなFlaskサーバーのテンプレートです。
実際のプロジェクトで運用する際は、ファイル名を `main.py` 等に変名して利用することをおすすめします。

ループ処理と事後処理に対応しており、AIは各ステップを順に実行することで、バッチ処理や自動評価を効率的に進めることができます。

## テンプレートの特徴
- **5ステップの小分け指示**: 「全体初期化」「個別データ準備」「AI評価」「ステータス更新・ループ」「最終処理」の5つのステップで構成された例です。
- **ループ制御の内包**: `task_status.json` のようなステータス管理ファイルを読み込み、未処理のデータが残っている場合は自動的に指定のステップにループバックする仕組みを備えています。ループ完了後は最終ステップ（Step 5）に進みます。
- **堅牢な状態遷移（TaskState）**: 処理状態（pending -> processing -> completed）の厳格なチェックを `task_state.py` で行い、AIの順番飛ばしなどの不正操作を防止します。
- **柔軟なフロー変更**: `CHAIN_FLOW` という辞書を書き換えるだけで、ステップの増減やループ位置を簡単に変更できます。
- **緊急停止ロック**: スクリプト側でエラーが起きた際、JSON経由で自動的にチェーン全体を凍結（403エラー）し、被害の拡大を防ぎます。手動での中断処理（POST /error）にも対応しています。

## 使用方法

### 1. カスタマイズ (CHAIN_FLOW)
`main_template.py` の上部にある `CHAIN_FLOW` と `get_step_instructions()` 内のテキスト指示文を書き換えることで、独自のワークフローを構築できます。

**デフォルトのフロー定義（5ステップ中、2〜4がループ）:**
```python
CHAIN_FLOW = {
    1: {"next": 2},       # 初期化・全体の準備処理
    2: {"next": 3},       # 【ループ開始】個別データの準備
    3: {"next": 4},       # AIによる自律評価・処理
    4: {"next": 5, "check_status": True, "loop_back_to": 2}, # ステータス更新（未完了なら2へ戻る、完了なら5へ）
    5: {"next": None}     # 全件完了後の最終処理（終了）
}
```

### 2. サーバーの起動
以下のコマンドでサーバーを起動します。
引数でポート番号とステータスJSONファイルのパスを指定できます（デフォルトは `task_status.json`）。

```bash
python main_template.py --port 5000 --status_json task_status.json
```

### 3. AIへの指示（プロンプト）
AIに対しては以下のように初期化URLを渡し、処理を開始させてください。

> 処理を開始します。以下のURLにアクセスして初期化し、指示に従って最後まで進めてください。
> http://127.0.0.1:5000/init

### 4. エラーフラグによる中断処理と復旧
もしスクリプト内で `TaskStateError` 等が発生した場合、`error_flag` が自動的にTrueになりタスクチェーン全体が凍結されます。外部から意図的に止める場合は以下のコマンドを使います。

```bash
# JSONでメッセージを指定して中断する例
curl -X POST http://127.0.0.1:5000/error -H "Content-Type: application/json" -d "{\"message\": \"[ERROR] 処理を中断しました。\"}"
```

**復旧方法**:
エラー原因を取り除いた後、`/init` にアクセスしてタスクチェーンをリセットしてください（この時、古い `task_status.json` は自動的に削除されます）。その後、`step1.py`（初期化スクリプト）を実行してJSONファイルを綺麗な状態に戻してから再開してください。

### 5. ステータスの確認 (/status)
`/status` エンドポイントにアクセスすると、現在のタスクチェーンの進行状況（実行中のステップ）に加えて、`task_status.json` が存在する場合は以下のような進捗状況（完了数や残り件数）も確認できます。

```text
Task Chain Status: Running (Step 2)
Items: 1/3 completed (2 remaining)
```

### 6. ステータスJSONの要件
ループ制御を有効にするには、引数 `--status_json` で指定するJSONファイルが以下の構造を持っている必要があります。このJSONは `task_state.py` (TaskState クラス) によって自動管理されます。

```json
{
    "error_flag": false,
    "error_message": "",
    "loop": [
        {
            "item": "data1.csv",
            "status": "completed"
        },
        {
            "item": "data2.csv",
            "status": "pending"
        }
    ]
}
```
- `error_flag` が `true` の場合、全ステップへのアクセスが遮断されます。
- `status` の値が `pending` または `processing` のものが残っている場合、`check_status: True` に設定されたステップの完了後にサーバーは `loop_back_to` で指定したステップを返してループを継続します。
- すべてが `complete` または `completed` になると、指定された `next` ステップ（上記の例なら Step 5）へと進みます。

### 7. カスタムスクリプトの実装ガイド
フローを変更して新しいPythonスクリプトを作成する場合、`task_state.py` の `TaskState` を使ってステータスを管理してください。
- **ループの開始時**: `item = TaskState().start_process()` で `pending` なアイテムを取得し `processing` にします。
- **ループの完了時**: `TaskState().complete_process()` を呼び出して `completed` にします。
