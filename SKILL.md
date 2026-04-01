---
name: freecad-modeling-order
description: >
  FreeCAD MCPツールを使って3Dモデリングを行う際に、ツールの正しい実行順序を参照・適用するためのスキル。
  複数ステップのモデリング（コーヒーカップ・ボトル・穴あきプレート・スイープ形状など）を行うとき、
  ブール演算・シェル化・フィレット・パターン・ミラーを組み合わせるときは必ずこのスキルを参照すること。
  FreeCAD MCPツール（create_box, combine_by_name, shell_body, add_fillet, extrude_sketch など）を
  1つ以上呼び出す可能性があるモデリング作業であれば、迷わずこのスキルを使うこと。
---

# FreeCAD モデリング実行順序ガイド

FreeCAD MCPツールは **順序依存**が強い。間違った順序で呼ぶとブール演算失敗・フィレット不可・スケッチ未定義エラーが発生する。
このスキルでは「なぜその順序なのか」を理解したうえで正しい順序でツールを呼び出すことを目的とする。

---

## 基本原則：フェーズ順に進む

```
① 形状作成・スケッチ
    ↓
② 配置（移動・回転）
    ↓
③ ブール演算（結合 join / 切除 cut）
    ↓
④ シェル化（中空化）     ← join の後でないと薄肉ボディへのブール演算が失敗する
    ↓
⑤ パターン・ミラー       ← ブール演算の前後どちらかは意図による（後述）
    ↓
⑥ フィレット・面取り     ← 必ず最後。ここより前にブール演算を入れると失敗する
    ↓
⑦ 確認（情報取得・干渉チェック）
    ↓
⑧ 保存・エクスポート
```

---

## 最重要ルール

### ルール1：フィレット・面取りは絶対に最後

add_fillet / add_chamfer の後にブール演算（combine_*）を呼んではいけない。
丸みのついたエッジは後続のブール演算カーネルを失敗させる。

  OK:  combine_by_name(cut) → add_fillet
  NG:  add_fillet → combine_by_name(cut)

### ルール2：ブール結合（join）→ シェル化（shell_body）

shell_body はソリッドの状態で呼ぶ。取っ手付き容器のような複合形状は、
必ず全パーツを combine_by_name(join) で1つのソリッドにしてから shell_body を呼ぶ。
薄肉シェル状態のボディに対してブール演算を行うと形状が破綻する可能性が高い。

  OK:  combine(join) → shell_body → add_fillet
  NG:  shell_body → combine(join) → add_fillet

### ルール3：移動・回転してからブール演算

ツール形状を正しい位置に配置してからブール演算を行う。

  OK:  create_cylinder → move_by_name → combine_by_name(cut)
  NG:  create_cylinder → combine_by_name(cut) → move_by_name

### ルール4：スウィープ・ロフトは全スケッチを先に用意する

sweep_sketch はプロファイルスケッチとパススケッチ両方が存在しないと失敗する。
loft_sketches は全プロファイルスケッチが揃ってから呼ぶ。

  OK:  create_sketch(profile) → create_sketch(path) → sweep_sketch
  NG:  sweep_sketch を呼んでから path スケッチを作る

### ルール5：干渉チェックしてからブール演算

check_interference で重なりを確認してから combine_by_name(cut/join) を呼ぶと
意図しない形状生成を防げる。干渉なし(False)のまま cut を呼んでも形状は変化しない。

---

## ケース別ベストプラクティス

### ① 取っ手付き容器（コーヒーカップ・マグカップ等）

```
1. create_cylinder          カップ本体（ソリッド）
2. create_pipe              取っ手（ソリッド）
3. move_by_name             取っ手を正しい位置へ
4. check_interference       重なりを確認
5. combine_by_name(join)    本体＋取っ手を一体化（ソリッド同士）
6. shell_body               一体化後に中空化（開口面・厚みを指定）
7. add_fillet               最後に角を丸める
8. export_file
```

### ② ボルト穴パターン（円形配列で複数穴を一括切除）

パターン化→一括切除の方が、1穴ずつ切除を繰り返すより安定する。

```
1. create_cylinder          本体
2. create_cylinder          穴ツール（1個）
3. move_by_name             1か所目の位置へ配置
4. create_circular_pattern  穴ツールを円形配列（切除前にパターン化）
5. combine_selection(cut)   本体からパターン全穴を一括切除
6. add_chamfer              穴の入り口を面取り（最後）
7. export_file
```

### ③ 左右対称部品（ミラーコピー）

フィレット前にミラー＆結合することで、接合ラインに問題が起きにくい。

```
1. create_sketch + draw_*            片側の断面スケッチ
2. add_*_constraint / add_*_dimension   拘束・寸法を確定
3. extrude_sketch                    片側をソリッド化
4. copy_body_symmetric               フィレット前にミラーコピー
5. combine_by_name(join)             両側を結合（ソリッド同士）
6. add_fillet                        結合後に丸め（最後）
7. export_file
```

### ④ スウィープ形状（パイプ継手・曲管等）

```
1. create_sketch(plane=yz)   断面プロファイルを先に用意
2. draw_circle_in_sketch     断面形状を描く
3. create_sketch(plane=xy)   パス用スケッチを用意
4. draw_line_in_sketch       パス形状を描く
5. sweep_sketch              両スケッチが揃ってから実行
6. add_fillet                最後
```

### ⑤ 矩形パターン（格子状穴・リブ配列等）

```
1. create_cylinder / create_box     ツール形状（1個）
2. move_by_name                     基準位置へ配置
3. create_rectangular_pattern       X/Y方向に配列（切除前）
4. combine_selection(cut)           一括切除
5. add_fillet / add_chamfer         最後
```

---

## ツール別注意事項

| ツール | 注意点 |
|---|---|
| delete_all_features | モデリング途中では絶対に使わない。新規作業開始・作り直し時のみ冒頭で使用 |
| shell_body | ブール結合（join）後に呼ぶ。シェル化前に全パーツを join しておく |
| add_fillet / add_chamfer | 全ブール演算・パターン完了後に呼ぶ |
| combine_selection_all | 非表示ボディは対象外。hide_body で除外してから使う |
| create_section_view | 可視化・確認用途のみ。断面ボディを後続ブール演算に使わない |
| loft_sketches | 全プロファイルスケッチが存在してから呼ぶ |
| sweep_sketch | プロファイルとパスの両スケッチが存在してから呼ぶ |
| get_edges_info | add_fillet 前に呼んでエッジインデックスを確認するとミスを防げる |
| check_interference | ブール演算前の確認に使う。False（干渉なし）の状態で cut しても形状は変わらない |

---

## スケッチワークフロー順序

```
create_sketch
  → draw_rectangle_in_sketch / draw_circle_in_sketch / draw_line_in_sketch
  → add_horizontal_constraint / add_vertical_constraint / add_parallel_constraint
  → add_perpendicular_constraint / add_coincident_constraint / add_tangent_constraint
  → add_linear_dimension / add_radius_dimension
  → extrude_sketch / revolve_sketch / sweep_sketch / loft_sketches
```

拘束・寸法は図形を描いた後に追加する。先に拘束を追加しても図形がないので適用できない。

---

## クイックリファレンス

```
【形状作成】
  create_box / create_cylinder / create_sphere / create_cone /
  create_torus / create_hemisphere / create_half_torus /
  create_polygon_prism / create_pipe / create_cube
  create_sketch → draw_* → add_*_constraint → add_*_dimension
  extrude_sketch / revolve_sketch / loft_sketches / sweep_sketch

【配置】
  move_by_name / rotate_by_name → (任意) check_interference

【ブール演算】
  combine_by_name / combine_selection / combine_selection_all

【中空化】← ブール結合の後
  shell_body

【パターン・ミラー】
  create_circular_pattern / create_rectangular_pattern / copy_body_symmetric

【仕上げ】← 必ず最後
  add_fillet / add_chamfer

【情報確認】← 任意のタイミング
  get_all_bodies / get_body_dimensions / get_bounding_box / get_body_center /
  get_mass_properties / get_edges_info / get_faces_info /
  measure_distance / measure_angle / check_interference

【出力】← 最後
  save_document / export_file
```
