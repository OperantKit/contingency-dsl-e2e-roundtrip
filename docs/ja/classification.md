# 論文を手続きの種類で分類する

:gb: [English](../en/classification.md)

往復そのもの（`e2e run`）には言語モデルは要りません。要るのは分類、つまり論文の Method 節がどの種類の手続きを使っているかを決める工程です。このページでは、手続きの種類、分類の走らせ方、分類の信頼性を説明します。

## 手続きの種類

手続きの種類は [contingency-dsl](https://github.com/OperantKit/contingency-dsl) の適合テストの木から読み取ります。`conformance/**/*.json` のファイル 1 つが 1 つのキーになります（例: `operant/atomic`、`operant/stateful/adjusting`、`respondent/elementary`）。そちらでファイルが足されたり名前が変わったりすると、ここのキーもそれに従います。固定の一覧はありません。`e2e list-procedures` が現在のキーを表示します。

`e2e report` は `corpus/doi-lists/` の下に、キーごとに 1 つの Markdown ファイルを書きます。DOI 1 つにつき 1 行です。

```
- [x] 10.1901/jeab.2005.33-03 — PASS (a:✓ b:✓ c:0.82 d:✓)
- [ ] 10.1002/jaba.226        — FAIL (a:✗ b:✓ c:0.41 d:✗)
```

`corpus/doi-lists/index.md` には、すべてのキーと、それぞれの合格数が並びます。

## バックエンドで分類する

`e2e classify --doi <doi>`（または `--all`）は論文を直接分類します。バックエンドは自動で選ばれます。

| バックエンド | 必要なもの | 使われるとき |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` と `anthropic` パッケージ | `ANTHROPIC_API_KEY` が設定されているとき |
| `claude-cli` | `claude` コマンド（Claude Code） | それ以外で、`claude` が PATH にあるとき |

`E2E_CLASSIFIER_BACKEND=anthropic` または `=claude-cli` で強制できます。`claude-cli` バックエンドは論文 1 本ごとに `claude -p` を、作業ディレクトリ `/tmp`・`--no-session-persistence` 付きで起動します。API キーは要りませんが、SDK より遅く、トークンも多く使います。

## Claude Code のサブエージェントで分類する

対話中の Claude Code のセッションの中では、分類をサブエージェントに任せられます。API キーも `claude -p` の子プロセスも要りません。

1. 現在の手続きの種類からサブエージェントの定義を書き出し、それが読み込まれるよう Claude Code を再起動します（エージェントの定義はセッションの開始時にしか読まれません）。

   ```bash
   .venv/bin/e2e regenerate-agent     # writes .claude/agents/procedure-classifier.md
   ```

2. 分類する論文の待ち行列を作ります。

   ```bash
   .venv/bin/e2e classify-prepare     # writes corpus/work/classify-queue.jsonl
   ```

3. セッションに待ち行列の分類を頼みます。セッションは `e2e next-batch 15` で次のプロンプトを取り、`Agent(subagent_type="procedure-classifier", ...)` を並列に走らせ、論文 1 本につき 1 行の `{"doi": "...", "procedures": [...]}` を `e2e ingest-batch` で `corpus/work/classify-results.jsonl` に追記します。

4. 結果を状態に取り込み、一覧を作り直します。

   ```bash
   .venv/bin/e2e classify-ingest      # reads corpus/work/classify-results.jsonl
   .venv/bin/e2e report
   ```

再起動したセッションが `procedure-classifier` を読み込むまでは、キーの一覧をプロンプトに貼り付けた `subagent_type="general-purpose"` でも代わりになります。

### 長い待ち行列: `classify-queue` スキル

数百本の論文の待ち行列には、このリポジトリに入っている [`classify-queue` スキル](../../.claude/skills/classify-queue/SKILL.md) を使います。セッションとそのサブエージェントの両方を Haiku で走らせると（`claude --model haiku` で起動し、`/classify-queue`）、大きいモデルのセッションよりはるかに少ないトークンで済みます。セッションはこのリポジトリのルートから起動してください。スキルとその補助のパスは作業ディレクトリからの相対で探されます。

スキルは次のことをします。

- 最初に 1 本だけ試し、返事が JSON のオブジェクトでなければ止まる。
- 残りの論文を `e2e next-batch 15` で 15 本ずつ取る（プロンプトは `corpus/work/pending/<slug>.txt` に置かれる）。
- `Agent(subagent_type="procedure-classifier", model="haiku", ...)` を 15 本並列に走らせる。
- 15 行の結果を `corpus/work/batch-results.jsonl` に書き、`e2e ingest-batch` で `corpus/work/classify-results.jsonl` に追記する（シェルのパイプを使わない 1 つのコマンドなので、`.venv/bin/e2e` への許可の規則 1 つで全部の回をまかなえる）。
- `next-batch` が `remaining=0` を返すまで繰り返し、最後に `classify-ingest` と `report` を走らせる。

再起動と再実行:

- `e2e next-batch` は `corpus/work/classify-results.jsonl` に既にある論文を飛ばすので、落ちたセッションは止まったところから再開します。
- 待ち行列が終わった後に `/classify-queue` をもう一度走らせると、`remaining=0` ですぐに終わります。
- `procedures: []` の行も済んだものとして数えます。その論文を分類し直すには、`corpus/work/classify-results.jsonl` からその行を消してスキルを走らせ直します。
- 排他制御はありません。同じ待ち行列に 2 つのセッションを走らせると、同じ 15 本を取って二重に分類します。セッションは 1 つにするか、先に待ち行列を分けてください。

## 信頼性

`e2e second-rate <file>` は、ファイルに 1 行ずつ書いた DOI を 2 人目の評定者で分類し、`state.json` には触れずに結果を JSONL ファイルに追記します（`--backend claude-cli` または `codex-cli`）。続いて `e2e agreement <second.jsonl>` が、`state.json` の分類と 2 人目の評定者の間の Cohen の κ をキーごとに（付けた／付けなかった）報告します。`--first <first.jsonl>` を付けると、2 つの JSONL ファイルどうしを比べます。

分類の信頼性は、層別に抜き出した N=60 本の論文で確かめました。両方の評定者が、現在のプロンプトでこの標本を分類しました。このプロンプトは、名前だけでは評定者によって読み方が分かれたキーに短い定義を付けています。1 人目の評定者は `claude` CLI 経由の Claude haiku、2 人目の評定者は Codex CLI 経由の OpenAI gpt-6.1-sol で、プロンプトと出力の形式は同じです（`e2e second-rate --backend claude-cli|codex-cli` の後に `e2e agreement <second.jsonl> --first <first.jsonl>`。`--first` を付けないときは `state.json` に保存された分類が 1 人目になります）。キーごとの Cohen の κ（付けた／付けなかった）を全キーでまとめると micro κ = 0.795 です。両方の評定者が 5 本以上の論文に付けた 14 のキーのうち、最も低いのは `experiment/paper`（κ = 0.343）、最も高いのは `annotations/measurement` と `annotations/procedure-stimulus`（κ = 1.000）です。

この一致は 2 つの言語モデルの間のもので、モデルと人の評定者の間のものではありません。

## 手元のファイルから Method 節を読む

`corpus/extracted/<slug>.txt` が無いとき、`E2E_PAPER_SOURCES_ROOT` が次のような構成のディレクトリを指していれば、`e2e extract` は手元にある論文の写しから Method 節を取り出せます。上から順に試します（`<slug>` は DOI の `/` を `_` に置き換えたもの）。

```
$E2E_PAPER_SOURCES_ROOT/reference/papers/extracted/<slug>.md   # whole paper as Markdown; the Method section is cut out
$E2E_PAPER_SOURCES_ROOT/reference/papers/pdf/<slug>.pdf        # PDF; the Method section is cut out
$E2E_PAPER_SOURCES_ROOT/notes/papers/*.md                      # notes with a doi: field in the front matter
```
