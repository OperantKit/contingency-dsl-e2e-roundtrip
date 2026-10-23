# contingency-dsl-e2e-roundtrip

:gb: [English README](README.md)

論文の Method 節がパイプラインを往復して壊れないことを検証する
エンドツーエンド・ラウンドトリップ用ハーネス：

```
paper text T ──▶ contingency-procedure2dsl ──▶ DSL-AST ① (= ast1)
                                               │
                                               ▼
                                     contingency-dsl2procedure
                                               │
                                               ▼
                                         paper text P
                                               │
                                               ▼
                               contingency-procedure2dsl ──▶ DSL-AST ② (= ast2)
```

論文 1 件につき 4 つの判定を記録する。総合 PASS は (a) で決まる。

| キー | 判定内容                                  | PASS 条件                                     |
|------|------------------------------------------|-----------------------------------------------|
| a    | AST 意味等価性                            | `normalize(ast1) == normalize(ast2)`          |
| b    | コンパイル後テキスト `P` の再パース可能性 | `reader(P)` が非 null な AST を返す           |
| c    | `T` と `P` のテキスト類似度               | Jaccard ≥ 閾値（レポートのみ、判定には非関与） |
| d    | DSL 記法等価性（書式①=書式②）             | `canonical_json(ast1) == canonical_json(ast2)` |

## 手続き分類

手続き種別は `contingency-dsl/conformance/**/*.json` から**動的に**検出される。
各 JSON が 1 つの procedure key になる（例：`operant/atomic`・
`operant/stateful/adjusting`・`respondent/elementary`）。DSL 側で
conformance ファイルを追加・リネームすると、本プロジェクトの DOI リスト
レイアウトに自動で伝播する（ハードコード一覧は存在しない）。

procedure key ごとに `corpus/doi-lists/` 配下に markdown ファイルが生成され、
各 DOI がチェックマーク形式でステータス表示される：

```
- [x] 10.1901/jeab.2005.33-03 — PASS (a:✓ b:✓ c:0.82 d:✓)
- [ ] 10.1002/jaba.226        — FAIL (a:✗ b:✓ c:0.41 d:✗)
```

分類の信頼性は層化抽出した N=60 本で確かめた。両評定者とも現行の prompt
（名前だけでは評定者ごとに読みが分かれた key に短い定義を付けたもの）で標本を
分類した。第一評定者は `claude` CLI 経由の Claude haiku、第二評定者は Codex CLI
経由の OpenAI gpt-6.1-sol で、同じ prompt と出力 schema を与えた
（`e2e second-rate --backend claude-cli|codex-cli` の後に
`e2e agreement <second.jsonl> --first <first.jsonl>`。`--first` を付けなければ
`state.json` に保存済みの分類が第一評定者になる）。key ごとの Cohen κ
（付与 / 非付与）を全 key で束ねた micro κ は 0.795 で、両評定者とも 5 本以上に
付与した 14 key のうち最低は `experiment/paper`（κ = 0.343）、最高は
`annotations/measurement` と `annotations/procedure-stimulus`（κ = 1.000）。

## 生成アーティファクト（gitignored）

`e2e run` 実行時、論文ごとにラウンドトリップ中間物を人間可読な表層形で
`corpus/generated/` 配下に書き出す：

```
corpus/generated/
├── dsl/<slug>.dsl        # AST_1 を canonical DSL に整形したもの（例: "FR5"）
├── compiled/<slug>.txt   # P — dsl2procedure による論文テキスト
└── dsl2/<slug>.dsl       # AST_2 を canonical DSL に整形したもの
```

このディレクトリは **gitignore されている**（`corpus/extracted/` から
再生成可能）。Program として整形できない AST（部分的な Experiment /
Paper ノード等）はコメント付き JSON フォールバックで書き出され、
ラウンドトリップ結果が失われることはない。

## 抽出キャッシュ（gitignored）

手続きプレーンテキストは `corpus/extracted/<doi-slug>.txt` にキャッシュされる。
このディレクトリは **gitignore されている**。ファイルが存在すれば抽出は skip される。

キャッシュが無い場合のフォールバック順。2〜4 は `E2E_PAPER_SOURCES_ROOT` が
手元の論文ソースのディレクトリを指しているときだけ使われる：

1. `corpus/extracted/<doi-slug>.txt`（このプロジェクト）
2. `$E2E_PAPER_SOURCES_ROOT/reference/papers/extracted/<doi-slug>.md`
   （論文全体の markdown）— Method 節をスライス
3. `$E2E_PAPER_SOURCES_ROOT/reference/papers/pdf/<doi-slug>.pdf`（生 PDF）
   — Method 節をスライス
4. `$E2E_PAPER_SOURCES_ROOT/notes/papers/*.md`（front-matter に `doi:` を
   持つノート）— 手続き section を使う

`<doi-slug> = doi.replace("/", "_")`。

## セットアップ

手続きの分類体系は
[contingency-dsl](https://github.com/OperantKit/contingency-dsl) の
conformance ツリーから読むため、これも clone して `E2E_CONFORMANCE_ROOT` を
その `conformance/` ディレクトリに向ける：

```bash
git clone https://github.com/OperantKit/contingency-dsl-e2e-roundtrip
git clone https://github.com/OperantKit/contingency-dsl
cd contingency-dsl-e2e-roundtrip
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
# 任意: Anthropic SDK の分類バックエンド（ANTHROPIC_API_KEY が必要）
.venv/bin/python -m pip install -e '.[llm]'

export E2E_CONFORMANCE_ROOT="$PWD/../contingency-dsl/conformance"  # 必須
.venv/bin/python -m pytest -q
```

`pip` が contingency-dsl-py を PyPI から、contingency-procedure2dsl /
contingency-dsl2procedure を GitHub のタグから入れるので、ほかの checkout は
要らない。Python 3.11 以上。

| 環境変数                 | 必須   | 意味                                                                    |
|--------------------------|--------|-------------------------------------------------------------------------|
| `E2E_CONFORMANCE_ROOT`   | はい   | `contingency-dsl/conformance` のパス。未設定なら、この checkout の隣の `../contingency-dsl/conformance` を使う。 |
| `E2E_PAPER_SOURCES_ROOT` | いいえ | 手元の論文ノート・markdown・PDF。上の抽出フォールバック 2〜4 に使う。未設定なら `corpus/extracted/` だけを読む。 |
| `E2E_CLASSIFIER_BACKEND` | いいえ | `anthropic` か `claude-cli` を強制する（下記）。                         |

`corpus/state.json` の元になった論文本文は配布しない。clone 直後の
`corpus/extracted/` は空なので、Method の本文は次節のように自分で置く。

## 30 秒の例

Method の 1 段落をラウンドトリップする。任意の DOI で本文を抽出キャッシュに
書き（ここでは作業用 corpus に仮の DOI で置き、tracked な
`corpus/state.json` は変えない）、実行する：

```bash
mkdir -p demo/corpus/extracted
cat > demo/corpus/extracted/10.0000_demo.txt <<'EOF'
Procedure
Lever presses were reinforced under a fixed-ratio 5 schedule: every fifth response produced a food pellet. Sessions were conducted daily and ended after 60 reinforcers or 60 min, whichever came first. Training continued until response rates were stable across five consecutive sessions.
EOF
.venv/bin/e2e --corpus demo/corpus run --doi 10.0000/demo
# [PASS] 10.0000/demo: a=True b=True c=0.2 d=True
cat demo/corpus/generated/dsl/10.0000_demo.dsl        # FR5
cat demo/corpus/generated/compiled/10.0000_demo.txt   # Responses were reinforced under a fixed-ratio (FR) 5 schedule.
```

キャッシュの本文は 200 字以上の散文が要る。短いファイルは空の雛形とみなされて
捨てられる。`run` は LLM を使わない（モデルを呼ぶのは分類 `classify` だけ）。

### 分類バックエンド

分類器はバックエンドを自動選択する：

| バックエンド | 必要条件                                    | 使われる条件                              |
|--------------|---------------------------------------------|-------------------------------------------|
| `anthropic`  | `ANTHROPIC_API_KEY`、`[llm]` extra          | 環境変数がセットされていれば優先採用      |
| `claude-cli` | `claude` バイナリ（Claude Code CLI）        | フォールバック — 既存 CLI セッションを流用、API キー不要 |

`E2E_CLASSIFIER_BACKEND={anthropic,claude-cli}` で強制指定できる。CLI
バックエンドは呼び出しごとに `cwd=/tmp` と `--no-session-persistence` を
付けて `claude -p` を spawn する。セッションキャッシュを毎回作り直すため、
SDK 経路より遅くトークン消費も大きい。

## CLI

```bash
.venv/bin/e2e list-procedures               # DSL の全 procedure key を表示
.venv/bin/e2e extract --doi <doi>           # extracted/<slug>.txt を用意
.venv/bin/e2e classify --doi <doi>          # LLM で分類（ANTHROPIC_API_KEY か claude CLI が必要）
.venv/bin/e2e classify-prepare              # subagent 消費用の corpus/work/classify-queue.jsonl を書き出し
.venv/bin/e2e next-batch 15                 # 未分類の次の 15 行を corpus/work/pending/*.txt に切り出す
.venv/bin/e2e ingest-batch <file>           # {doi, procedures} 行（'-' は標準入力）を corpus/work/classify-results.jsonl に追記
.venv/bin/e2e classify-ingest [<results>]   # subagent 結果 JSONL を state に折り込み
.venv/bin/e2e regenerate-agent              # procedure-classifier subagent md を (再)公開
.venv/bin/e2e run --doi <doi>               # 単一 DOI のラウンドトリップ
.venv/bin/e2e run --all                     # 分類済み論文すべてをラウンドトリップ
.venv/bin/e2e report                        # state から doi-lists/*.md を再生成
```

## Claude Code サブエージェント経由の分類（API キー不要）

対話的な Claude Code セッション内で走らせる場合、最速経路は `Agent` tool で
サブエージェントに分類をディスパッチすること。`ANTHROPIC_API_KEY` も
`claude -p` サブプロセスも不要。

1. サブエージェント定義を公開／再生成する（本プロジェクト内の `.claude/agents/procedure-classifier.md` に書き出される）：

   ```bash
   .venv/bin/e2e regenerate-agent
   ```

   その後 Claude Code を一度再起動して、新しいエージェントタイプを
   ディスカバーさせる（Claude Code はエージェント定義をセッション起動時
   のみ読むため）。

2. 分類待ちの DOI キューを用意する：

   ```bash
   .venv/bin/e2e classify-prepare          # corpus/work/classify-queue.jsonl を書き出し
   ```

3. Claude Code 内でバッチ分類をセッションに依頼する。セッションが
   `e2e next-batch 15` でプロンプトを切り出し、
   `Agent(subagent_type="procedure-classifier", ...)` を並列で呼び出し、
   1 DOI につき 1 つの JSON オブジェクト `{"doi": "...", "procedures": [...]}`
   を `e2e ingest-batch` で `corpus/work/classify-results.jsonl` に追記する。

4. 結果を state に折り込み、procedure ごとの DOI リストを再生成する：

   ```bash
   .venv/bin/e2e classify-ingest           # corpus/work/classify-results.jsonl を読む
   .venv/bin/e2e report
   ```

新しいエージェントがディスカバーされるまで（手順 1 と再起動が完了する
までの間）は、`subagent_type="general-purpose"` に taxonomy をプロンプト
インラインで渡す形でフォールバックできる。

### `classify-queue` skill による haiku 一括実行

DOI が数百件規模のキューに対しては、Haiku を常駐させて
[`classify-queue` skill](.claude/skills/classify-queue/SKILL.md) を叩くのが
最も安い経路。オーケストレータ（会話を駆動する側）とサブエージェント
（`Agent(model="haiku", ...)`）の両方を Haiku にすることで、トークン
コストを Opus/Sonnet 駆動より大幅に下げられる。skill は本リポジトリに同梱済みで、
skill が使うキュー操作は `e2e next-batch` / `e2e ingest-batch` サブコマンドで行う。

1. サブエージェント定義を refresh し、このプロジェクトで Claude Code を
   再起動してエージェントタイプを再ロードさせる：

   ```bash
   .venv/bin/e2e regenerate-agent
   ```

2. キューを生成：

   ```bash
   .venv/bin/e2e classify-prepare
   ```

3. **このプロジェクトルート**（skill 検出と helper パスが CWD 依存のため、
   ディレクトリを間違えると動かない）から Haiku 専用 session を起動：

   ```bash
   cd <this-package-root>
   claude \
     --model haiku \
     --effort low \
     --permission-mode bypassPermissions
   ```

   フラグの意図：

   - `--effort low` — Haiku の extended thinking を最小化。分類タスクは
     決定論的なので high-effort 推論は過剰（1 バッチ数分の遅延を生む）。
     起動バナーに Haiku のモデル名と low effort が出ていれば成功。
   - `--permission-mode bypassPermissions`（別名 `--dangerously-skip-permissions`）
     — shell パイプやサブシェル `( ... )` のたびに出る承認ダイアログを
     丸ごと skip する。本 skill は project ローカルのファイル操作しか
     しないため、このモードでも実害は無い。Claude Code は起動時に信頼
     確認ダイアログを出すので、そこで「Yes」を選ぶ必要がある。
   - このプロジェクトに閉じた作業である前提で使うこと。外部へのネットワーク
     アクセスや system 変更を伴うタスクを同じ session で混在させない。

4. その session で skill を invoke：

   ```
   /classify-queue
   ```

   skill がやること：

   - DOI 1 件で probe し、JSON オブジェクト以外が返ってきたら停止する
   - 未分類 DOI を `e2e next-batch 15` で 15 件ずつ
     `corpus/work/pending/<slug>.txt` に切り出す
   - 1 メッセージで `Agent(subagent_type="procedure-classifier",
     model="haiku", ...)` を 15 並列発火する
   - 結果 15 行を `Write` tool で `corpus/work/batch-results.jsonl` に書き、
     `.venv/bin/e2e ingest-batch corpus/work/batch-results.jsonl` で
     `corpus/work/classify-results.jsonl` に追記する（単発コマンドで shell の
     パイプを経由しないため、手元の `.claude/settings.local.json` で
     `Bash(.venv/bin/e2e:*)` を許可しておけばバッチごとの承認ダイアログなしに回る）
   - `next-batch` が `remaining=0` を返すまでループし、完了後に
     `classify-ingest` と `report` を自動実行する

5. 再開・再実行の挙動

   - `e2e next-batch` は `corpus/work/classify-results.jsonl` に既にある DOI を
     除外するため、session を落として再起動しても差分から再開する
   - 全件完了後にもう一度 `/classify-queue` を叩いても `remaining=0` で
     即終了する（no-op）
   - 空の `procedures: []` 行も「済」として扱われ、自動では再分類されない。
     やり直したい場合は `corpus/work/classify-results.jsonl` から該当行を削除して
     から skill を再 invoke すること

6. 並列実行についての注意

   同一キューに対して Haiku session を 2 つ走らせると、どちらも同じ 15
   DOI を pick して二重に分類してしまう（ロック機構なし）。原則 1 session
   で回すか、キューを事前に分割してから起動すること。

## 状態管理（state）

DOI ごとのラウンドトリップ結果は JSON として `corpus/state.json`（tracked）
に永続化される。これによりパイプラインを再実行せずともレポートを再生成できる。
