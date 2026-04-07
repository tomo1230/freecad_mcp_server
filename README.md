# FreeCAD MCP Server for AIエージェント

**バージョン: 0.9.0**

このプロジェクトは、**Claude Desktop**または**Codex Desktop**などのAIエージェントが**FreeCAD**を直接操作するためのModel Context Protocol (MCP)サーバーです。このツールをAIエージェントに追加することで、チャットのプロンプトを通じて3Dモデルの作成、編集、情報取得が可能になります。

このサーバーは、FreeCAD内で動作するPythonマクロ（`freecad_mcp_addon.py`）と連携して機能します。

- **作者:** Kanbara Tomonori
- **X (旧Twitter):** [@tomo1230](https://x.com/tomo1230)
- **ライセンス:** MIT License

---

## 概要とアーキテクチャ

このツールは、AIエージェントとの対話を通じて、直感的かつ自然言語ベースでFreeCADのモデリング作業を行うためのブリッジとして機能します。

このREADMEでは、**Claude Desktop** / **Codex** / **Claude Code** の3パターンに分けてセットアップ方法を説明します。

**処理フロー:**
1.  ユーザーがAIエージェントのチャットで自然言語でプロンプトを送信します。（例: `50mmの立方体を作って`）MCPツールはClaudeが自動的に認識・使用するため、特別なプレフィックスは不要です。
2.  AIエージェントは、このNode.jsサーバー（`freecad_mcp_server.js`）を子プロセスとして起動し、`CallToolRequest` を送信します。
3.  Node.jsサーバーはリクエストをJSONコマンドに変換し、`http://127.0.0.1:8765/command` に HTTP POST します。
4.  FreeCAD内で実行中のPythonマクロ（`freecad_mcp_addon.py`）がHTTPサーバーとして待ち受けており、リクエストを受信してFreeCADのPart APIを実行します。
5.  Pythonマクロは実行結果をHTTPレスポンスとして返します。
6.  Node.jsサーバーがレスポンスを受け取り、AIエージェントに結果を返します。
7.  AIエージェントがその結果を解釈し、ユーザーに応答します。

> **ポート設定:** デフォルトは `127.0.0.1:8765`。環境変数 `FREECAD_MCP_HOST` / `FREECAD_MCP_PORT` で変更可能です。

---

## セットアップ

まずは全エージェント共通の準備を行い、その後に使いたいクライアントごとの設定を追加します。

### どのクライアントを使うか

| クライアント | 用途 | このREADMEでの対象 |
|---|---|---|
| **Claude Desktop** | GUIチャットでFreeCADを操作 | MCPサーバー接続手順 |
| **Codex** | Codexアプリ/CLIからFreeCADを操作 | MCPサーバー接続手順 |
| **Claude Code** | ターミナル型エージェントでモデリング手順を安定化 | `SKILL.md` の導入手順 |

### Step 1: 共通の前提条件
- **Node.js**: v18以降がインストールされていること。(<https://nodejs.org/ja/download>)
- **FreeCAD**: バージョン 0.21以降がインストールされていること。(<https://www.freecad.org/>)
- **このリポジトリ**: `freecad_mcp_server.js` と `freecad_mcp_addon.py` を使える状態にしておくこと

### Step 2: 共通のインストール
1. 任意の場所にこのリポジトリをクローンします。
   ```bash
   git clone https://github.com/tomo1230/freecad_mcp_server
   ```
2. ターミナルでディレクトリに移動し、依存関係をインストールします。
   ```bash
   cd freecad_mcp_server
   npm install
   ```

### Step 3: FreeCADでマクロを起動
1. FreeCADを起動します。
2. メニューから **マクロ → マクロを実行...** を選択します。
3. このリポジトリの `freecad_mcp_addon.py` を選択して実行します。
4. FreeCADのコンソールに `[MCP] FreeCAD MCP Addon started. API endpoint: http://127.0.0.1:8765/command` と表示されれば待ち受け状態です。

> **注意:** FreeCADを再起動するたびにマクロの再実行が必要です。

### Step 4: 回帰テストの実行（任意）
FreeCAD MCP の全ツールをまとめて確認したい場合は、`freecad_mcp_addon.py` を起動した状態で次を実行します。

```bash
npm run test:regression
```

PowerShell で `npm` 実行がブロックされる環境では、次を使ってください。

```bash
npm.cmd run test:regression
```

この回帰テストでは以下を確認します。

- 57 個の MCP ツールをすべて実行できること
- 形状作成、ブール演算、計測、スケッチ拘束、保存、エクスポートが成功すること
- `get_edges_info` が複合形状でも失敗しないこと
- `extrude_sketch` が閉じたスケッチで正常動作すること

実行後は作業ディレクトリに次の成果物が生成されます。

- `regression_all_tools_<timestamp>.fcstd`
- `regression_comboAll_<timestamp>.stl`

---

## Claude Desktop のセットアップ

GUI の Claude Desktop から FreeCAD を操作したい場合の手順です。

### 前提
- **Claude Desktop**: アプリケーションがインストールされていること。（<https://claude.ai/download>）

### 設定手順
1. Claude Desktopを開き、左上のツールメニューからファイル＞設定の画面に移動します。
2. 「設定を編集」のボタンをクリックします。
3. `claude_desktop_config.json` に以下を追加します。リポジトリにはサンプルとして `.claude/claude_desktop_config.json` も含まれています。
   ```json
   {
     "mcpServers": {
       "freecad": {
         "command": "node",
         "args": ["/path/to/freecad_mcp_server/freecad_mcp_server.js"],
         "env": {
           "FREECAD_MCP_HOST": "127.0.0.1",
           "FREECAD_MCP_PORT": "8765"
         }
       }
     }
   }
   ```

> **注意:** `env` の設定はデフォルト値なので省略可能です。FreeCADのHTTPサーバーポートを変更した場合のみ指定してください。

### 使用例
- `幅50、奥行き30、高さ20の箱を作って`
- `"MyCube" という名前の立方体を作成して、その寸法を教えて`
- `最後に作ったボディに半径2mmのフィレットを追加して`

---

## Codex のセットアップ

Codex からこの MCP サーバーを呼び出したい場合の手順です。

### 前提
- **Codex**: アプリまたはCLIがインストールされていること

### 設定手順
1. Codex の設定ファイルに `freecad` サーバーを追加します。
2. リポジトリにはサンプルとして `.codex/config.toml` が含まれています。
3. パスを自分の環境に合わせて `freecad_mcp_server.js` へ向けてください。

```toml
approval_policy = "never"

[mcp_servers.freecad]
command = "node"
args = ["C:\\freecad_mcp_server\\freecad_mcp_server.js"]
enabled = true
alwaysAllow = true
```

### 補足
- `alwaysAllow = true` にすると、Codex から FreeCAD MCP ツールを毎回確認なしで使えます。
- FreeCAD 側では、事前に `freecad_mcp_addon.py` を起動しておく必要があります。
- ホストやポートを変える場合は、Codex 側の設定ではなく環境変数 `FREECAD_MCP_HOST` / `FREECAD_MCP_PORT` を使って Node.js サーバー側を調整してください。

### 使用例
- `50mmの立方体を作って`
- `円柱を作ってから上面に半径3mmのフィレットを追加して`
- `いまあるボディ一覧を教えて`

---

## Claude Code のセットアップ

Claude Code では、MCPサーバー設定そのものよりも、`SKILL.md` を導入してモデリング時のツール実行順序を安定させる使い方を想定しています。

> Claude Desktop のチャット設定とは別です。こちらは **Claude Code（ターミナル版）** 向けの説明です。

### `SKILL.md` の役割

| ファイル | 役割 |
|---|---|
| `SKILL.md`（リポジトリ内） | 参照用コピー。内容の確認・バージョン管理に使用 |
| `%APPDATA%\Claude\...\skills\freecad-modeling-order\SKILL.md` | Claude Code が実際に読み込むスキル本体 |

### インストール方法
1. スキルディレクトリを作成します。
   ```
   %APPDATA%\Claude\local-agent-mode-sessions\skills-plugin\<session-id>\<sub-id>\skills\freecad-modeling-order\
   ```
2. 上記ディレクトリに `SKILL.md` をコピーします。
3. 同ディレクトリの `manifest.json` の `"skills"` 配列に以下を追加します。
   ```json
   {
     "skillId": "freecad-modeling-order",
     "name": "freecad-modeling-order",
     "description": "FreeCAD MCPツールを使って3Dモデリングを行う際に、ツールの正しい実行順序を参照・適用するためのスキル。...",
     "creatorType": "user",
     "updatedAt": "2026-03-27T00:00:00.000Z",
     "enabled": true
   }
   ```
4. Claude Code を再起動すると自動的にスキルが有効になります。

### このスキルが有効な場面
- コーヒーカップ・ボトル・容器など複合形状の作成
- ブール演算（結合・切除）とシェル化の組み合わせ
- フィレット・面取り・パターン・ミラーを含む複数ステップ作業
- スウィープ・ロフト形状の作成

---

## モデリングベストプラクティス / ツール実行順序

複雑な形状を確実に作るためには、ツールの実行順序が重要です。
順序を間違えるとブール演算が失敗したり、フィレットが適用できなくなる場合があります。

---

### 🔑 基本原則（全モデルに共通）

```
形状作成・配置 → ブール演算（結合/切除） → シェル化 → パターン/ミラー → フィレット/面取り → 保存/エクスポート
```

| 優先度 | ルール | 理由 |
|---|---|---|
| 🔴 最重要 | **フィレット/面取りは最後** | 丸みのついたエッジは後続のブール演算を失敗させる |
| 🔴 最重要 | **ブール演算（結合）→ シェル化** | ソリッド同士をまず一体化してから中空化する |
| 🟠 重要 | **移動/回転してからブール演算** | 位置確定後に切除・結合する |
| 🟠 重要 | **パターンはブール演算の前か後か意識する** | 目的によって順序が変わる（後述） |
| 🟡 推奨 | **干渉チェックしてからブール演算** | 意図しない切除・結合を防ぐ |
| 🟡 推奨 | **エッジ/面情報を確認してからフィレット** | インデックス指定ミスを防ぐ |

---

### 📋 ケース別ベストプラクティス

#### ① コーヒーカップ（取っ手付きの容器）

> **NG順序:** カップをシェル化 → 取っ手を結合
> → シェル済みの薄肉ボディへのブール演算は失敗しやすい

```
✅ 正しい順序:
1. create_cylinder          ── カップ本体（ソリッド）
2. create_pipe / create_cylinder  ── 取っ手（ソリッド）
3. move_by_name / rotate_by_name  ── 取っ手を正しい位置に配置
4. combine_by_name (join)   ── 本体 + 取っ手 を一体化（ソリッド同士）
5. shell_body               ── 一体化後に中空化（厚み・開口面を指定）
6. add_fillet               ── 最後に角を丸める
7. export_file              ── 完成後にエクスポート
```

---

#### ② ボルト穴パターン（円形配列で複数穴）

> **NG順序:** 穴を1つ切除 → パターン複製
> → 切除後の複雑形状をパターン化するとインデックスがずれる

```
✅ 正しい順序:
1. create_cylinder                    ── 本体
2. create_cylinder                    ── 穴ツール（1個）
3. move_by_name                       ── 穴ツールを1か所目の位置へ
4. create_circular_pattern            ── 穴ツールを円形配列（切除前にパターン化）
                                         axis="z", quantity=4, angle=360
5. combine_selection (cut)            ── 本体からパターン全穴を一括切除
6. add_chamfer                        ── 穴の入り口を面取り（最後）
7. export_file
```

---

#### ③ 左右対称部品（ミラーコピー）

> **NG順序:** フィレット追加 → ミラーコピー → 結合
> → フィレット後の複雑形状を結合すると接合部に問題が起きやすい

```
✅ 正しい順序:
1. create_sketch + draw_*   ── 片側の断面スケッチ
2. add_*_constraint / add_*_dimension  ── 拘束・寸法を確定
3. extrude_sketch            ── 押し出してソリッド化
4. copy_body_symmetric       ── ミラーコピー（フィレット前）
5. combine_by_name (join)    ── 両側を結合（ソリッド同士）
6. add_fillet                ── 結合後に丸め処理（最後）
7. export_file
```

---

#### ④ スイープ/ロフト形状（パイプ継手・ブレンド形状）

> **NG順序:** sweep_sketch を呼ぶ → その後でパスを作成
> → スケッチが存在しないと実行エラーになる

```
✅ 正しい順序:
1. create_sketch (plane=yz) ── 断面プロファイルのスケッチを先に用意
2. draw_circle_in_sketch    ── 断面形状を描く
3. create_sketch (plane=xy) ── パス用スケッチを用意
4. draw_line_in_sketch      ── パス形状を描く
5. sweep_sketch             ── プロファイル + パス の両方が揃ってから実行
6. add_fillet               ── 最後
```

> `loft_sketches` も同様に、**全プロファイルスケッチを先に作成**してから呼び出す。

---

#### ⑤ 干渉チェック → ブール演算

> 位置ずれのまま切除すると意図しない形状になる

```
✅ 正しい順序:
1. create_* / move_by_name  ── ツールボディを配置
2. check_interference       ── 干渉を確認（Trueなら重なっている）
3. combine_by_name (cut)    ── 干渉を確認してから切除
```

---

### ⚙️ ツールごとの推奨呼び出し順序まとめ

```
【形状作成フェーズ】
  create_box / create_cylinder / create_sphere ...
  create_sketch → draw_* → add_*_constraint → add_*_dimension
  extrude_sketch / revolve_sketch / loft_sketches / sweep_sketch

【配置フェーズ】
  move_by_name / rotate_by_name
  ↓ (任意) check_interference で干渉確認

【ブール演算フェーズ】
  combine_by_name / combine_selection / combine_selection_all

【中空化フェーズ】  ← ブール演算（結合）の後
  shell_body

【パターン/ミラーフェーズ】
  create_circular_pattern / create_rectangular_pattern
  copy_body_symmetric

【仕上げフェーズ】  ← 必ず最後
  add_fillet / add_chamfer

【情報確認フェーズ】  ← 任意のタイミングで
  get_all_bodies / get_body_dimensions / get_bounding_box / get_body_center
  get_edges_info / get_faces_info  ← フィレット前にインデックス確認
  get_mass_properties / get_body_relationships
  measure_distance / measure_angle / check_interference

【出力フェーズ】  ← 最後
  save_document / export_file
```

---

### ⚠️ 注意が必要なツール

| ツール | 注意点 |
|---|---|
| `delete_all_features` | モデリング途中では使用禁止。作り直し時の冒頭のみ |
| `shell_body` | **ブール演算で結合してから**呼び出す |
| `add_fillet` / `add_chamfer` | **全ブール演算・パターン完了後**に呼び出す。`add_fillet` は半径が大きすぎると自動縮小してリトライ（最大6回、50%ずつ縮小） |
| `combine_selection_all` | 非表示ボディは対象外。`hide_body`で除外してから使う |
| `create_section_view` | 可視化用途のみ。断面ボディは後続のブール演算に使わない |
| `loft_sketches` | 全プロファイルスケッチが存在していないと失敗 |
| `sweep_sketch` | プロファイルとパスの両スケッチが存在していないと失敗 |

---

## APIリファレンス / 利用可能なツール

Claudeは以下のツールを呼び出すことでFreeCADを操作します。

### 形状作成ツール (10種)

> **配置パラメータ補足:** `cx/cy/cz` は中心座標。`x_placement`（left/center/right）・`y_placement`（front/center/back）・`z_placement`（bottom/center/top）で基準点を変更できます（対応ツールのみ）。

| ツール名 | 説明 | 主なパラメータ |
|---|---|---|
| `create_box` | 直方体を作成 | width, depth, height, cx, cy, cz, x_placement, y_placement, z_placement |
| `create_cube` | 立方体を作成 | size, cx, cy, cz, x_placement, y_placement, z_placement |
| `create_cylinder` | 円柱を作成 | radius, height, cx, cy, cz, z_placement |
| `create_sphere` | 球を作成 | radius, cx, cy, cz |
| `create_cone` | 円錐を作成 | radius, radius2, height, cx, cy, cz, z_placement |
| `create_torus` | トーラス（ドーナツ形状）を作成 | major_radius, minor_radius, cx, cy, cz |
| `create_hemisphere` | 半球を作成 | radius, orientation(positive/negative), cx, cy, cz |
| `create_half_torus` | 半トーラスを作成 | major_radius, minor_radius, sweep_angle, cx, cy, cz |
| `create_polygon_prism` | 多角柱を作成 | num_sides, radius, height, cx, cy, cz, z_placement |
| `create_pipe` | 2点間にパイプ（円筒管）を作成 | radius, x1, y1, z1, x2, y2, z2 |

### スケッチ作成・描画ツール (4種)

| ツール名 | 説明 | 主なパラメータ |
|---|---|---|
| `create_sketch` | スケッチ平面を作成 | sketch_name, plane(xy/xz/yz), cx, cy, cz |
| `draw_rectangle_in_sketch` | スケッチに矩形を描く | sketch_name, x1, y1, x2, y2 |
| `draw_circle_in_sketch` | スケッチに円を描く | sketch_name, cx, cy, radius |
| `draw_line_in_sketch` | スケッチに直線を描く | sketch_name, x1, y1, x2, y2 |

### スケッチ拘束・寸法ツール (8種)

| ツール名 | 説明 | 主なパラメータ |
|---|---|---|
| `add_horizontal_constraint` | 水平拘束を追加 | sketch_name, edge_index |
| `add_vertical_constraint` | 垂直拘束を追加 | sketch_name, edge_index |
| `add_parallel_constraint` | 平行拘束を追加 | sketch_name, edge1, edge2 |
| `add_perpendicular_constraint` | 垂直（直角）拘束を追加 | sketch_name, edge1, edge2 |
| `add_coincident_constraint` | 一致拘束を追加 | sketch_name, edge1, edge2, point1, point2 |
| `add_tangent_constraint` | 接線拘束を追加 | sketch_name, edge1, edge2 |
| `add_linear_dimension` | 線形寸法拘束を追加 | sketch_name, edge_index, distance |
| `add_radius_dimension` | 半径寸法拘束を追加 | sketch_name, edge_index, radius |

### スケッチからソリッド生成ツール (4種)

| ツール名 | 説明 | 主なパラメータ |
|---|---|---|
| `extrude_sketch` | スケッチを押し出してソリッドを作成 | sketch_name, length, symmetric, body_name |
| `revolve_sketch` | スケッチを回転させてソリッドを作成 | sketch_name, axis, angle, body_name |
| `sweep_sketch` | プロファイルをパスに沿ってスイープ | profile_sketch, path_sketch, body_name |
| `loft_sketches` | 複数スケッチをロフトしてソリッドを作成 | sketch_names[], ruled, body_name |

### 編集・修正ツール (6種)

| ツール名 | 説明 | 主なパラメータ |
|---|---|---|
| `add_fillet` | エッジにフィレット（角丸め）を追加。半径が大きすぎる場合は自動的に縮小してリトライ | body_name, radius, edge_indices[] (空=全エッジ) |
| `add_chamfer` | エッジに面取りを追加 | body_name, distance, edge_indices[] (空=全エッジ) |
| `shell_body` | ボディをシェル（中空）化 | body_name, thickness, face_indices[], new_body_name |
| `create_rectangular_pattern` | 矩形パターンで複製 | source_body_name, quantity_one, distance_one, direction_one_axis(x/y/z), quantity_two, distance_two, direction_two_axis(x/y/z), new_body_base_name |
| `create_circular_pattern` | 円形パターンで複製 | source_body_name, quantity, angle, axis(x/y/z), new_body_base_name |
| `create_section_view` | 断面ビュー（カット済みボディ）を作成 | body_name, plane(xy/xz/yz), offset, new_body_name |

### ブール演算ツール (3種)

| ツール名 | 説明 | 主なパラメータ |
|---|---|---|
| `combine_by_name` | 2ボディをブール演算で結合 | target_body, tool_body, operation(join/cut/intersect), new_body_name |
| `combine_selection` | 複数ボディをブール演算で結合 | body_names[], operation, new_body_name |
| `combine_selection_all` | 表示中の全ボディをブール演算で結合 | operation, new_body_name |

### 変換・表示ツール (5種)

| ツール名 | 説明 | 主なパラメータ |
|---|---|---|
| `move_by_name` | ボディを移動 | body_name, x_dist, y_dist, z_dist |
| `rotate_by_name` | ボディを回転 | body_name, axis, angle, cx, cy, cz |
| `copy_body_symmetric` | ボディをミラーコピー | source_body_name, new_body_name, plane(xy/xz/yz) |
| `hide_body` | ボディを非表示にする | body_name |
| `show_body` | ボディを表示する | body_name |

### 情報取得・測定ツール (11種)

| ツール名 | 説明 | 主なパラメータ |
|---|---|---|
| `get_all_bodies` | ドキュメント内の全ボディ一覧を取得 | ― |
| `get_body_dimensions` | ボディの寸法・体積・面積を取得 | body_name |
| `get_bounding_box` | バウンディングボックスを取得 | body_name |
| `get_body_center` | 重心と幾何中心を取得 | body_name |
| `get_mass_properties` | 質量特性（体積・面積・質量・重心）を取得 | body_name, density |
| `get_edges_info` | エッジ情報（長さ・種別）を取得 | body_name |
| `get_faces_info` | 面情報（面積・種別・中心）を取得 | body_name |
| `get_body_relationships` | 2ボディの位置関係（距離・干渉）を取得 | body1, body2 |
| `measure_distance` | 2ボディ間の最短距離を測定 | body1, body2 |
| `measure_angle` | 2ボディの指定面間の角度を測定 | body1, body2, face_index1, face_index2 |
| `check_interference` | 2ボディが干渉しているか確認 | body1, body2 |

### ユーティリティ (6種)

| ツール名 | 説明 | 主なパラメータ |
|---|---|---|
| `execute_macro` | 複数コマンドを順番に実行 | commands[] |
| `save_document` | FreeCADドキュメントを保存 | filename |
| `export_file` | ボディをファイルにエクスポート | body_name, format(step/stl/obj/fcstd), filename |
| `delete_all_features` | ドキュメントの全オブジェクトを削除 | ― |
| `undo` | 直前の操作を1ステップ元に戻す | ― |
| `redo` | `undo` で戻した操作をやり直す | ― |

---

## 使用例

**YouTube モデるんですAI チャンネル**

「しゃべるだけで、世界がカタチになる。」
ことばが、モノになる時代。
『ModerundesuAI』は、AIと会話するだけで3Dモデリングができる、
未来のモノづくり体験をシェアするYouTubeチャンネルです。
Fusion 360やBlenderなどのCADソフトとAI（ChatGPTやClaude）を連携させて、
プロンプト（命令文）でリアルな“カタチ”を自動生成。
初心者からモデリング好きまで、誰でも「つくる楽しさ」に触れられるコンテンツを発信します！

**https://www.youtube.com/@ModerundesuAI**

**「FreeCADでサイコロを設計して」Claude AI＆FreeCAD API 連携🤖AIモデリングチャレンジ！💪**
[![Watch the video](https://img.youtube.com/vi/y1haF5Is68Y/hqdefault.jpg)](https://www.youtube.com/watch?v=y1haF5Is68Y)

**「FreeCADで400mlの水が入るコップを設計して」Claude AI＆Autodesk Fusion API 連携🤖AIモデリングチャレンジ！💪**
[![Watch the video](https://img.youtube.com/vi/te-kNyYsB4U/hqdefault.jpg)](https://www.youtube.com/watch?v=te-kNyYsB4U)

**「FreeCADで手すり付きの螺旋階段を設計して」Claude AI MCP ＆ FreeCAD API 連携🤖AIモデリングチャレンジ！💪**
[![Watch the video](https://img.youtube.com/vi/2ex0zDfI7NM/hqdefault.jpg)](https://www.youtube.com/watch?v=2ex0zDfI7NM)

---

## 🟢 できること
- **基本形状作成** - 直方体、立方体、円柱、球、円錐、トーラス、半球、半トーラス、多角柱、パイプ（10種）
- **スケッチモデリング** - 2D図形描画（矩形・円・直線）＋ 押し出し・回転・スイープ・ロフトでソリッド化
- **スケッチ拘束** - 水平・垂直・平行・垂直（直角）・一致・接線拘束、線形・半径寸法
- **編集操作** - フィレット、面取り、シェル化（中空化）、断面ビュー作成
- **パターン作成** - 円形・矩形配列、ミラーコピー
- **ブール演算** - 結合、切除、交差（2ボディ指定・複数選択・全体一括）
- **変換** - 移動、回転、表示/非表示
- **情報取得** - 寸法、体積、質量特性、エッジ/面情報、2ボディ間距離・角度・干渉チェック
- **ファイル操作** - FreeCAD形式で保存、STEP/STL/OBJ/FCStdでエクスポート
- **Undo/Redo** - 操作単位での元に戻す・やり直し（トランザクション対応）

## 🔴 できないこと
- **自由曲面** - NURBS曲面、有機的な形状
- **アセンブリ** - 複数部品の組み立て・拘束
- **解析・製造** - CAM、FEA（有限要素解析）、レンダリング
- **図面作成** - 2D図面（TechDrawワークベンチ）の自動生成

---

## ライセンス

MIT License - 詳細は [LICENSE](./LICENSE) ファイルを参照してください。
