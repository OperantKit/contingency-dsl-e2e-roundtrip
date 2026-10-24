# contingency-dsl-e2e-roundtrip

:gb: [English README](README.md)

contingency-dsl-e2e-roundtrip は、公刊された論文の Method 節に書かれた手続きが「Method の文章 → スケジュールの式 → 生成した Method の文章 → スケジュールの式」と往復しても崩れないかを、論文 1 本ずつ確かめます。Method 節を読む OperantKit の道具（[contingency-procedure2dsl](https://github.com/OperantKit/contingency-procedure2dsl)）と書く道具（[contingency-dsl2procedure](https://github.com/OperantKit/contingency-dsl2procedure)）を開発・評価する人で、どの種類の手続きを扱えるかを知りたい人に向けたものです。[OperantKit](https://github.com/OperantKit) の中では、この 2 つのパッケージを測る仕組みを担います。

- **論文ごとに 1 つの判定を手続きの種類別に出す。** 読む側・書く側・言語を変えたとき、どの論文が PASS と FAIL の間を動いたかが分かります。
- **途中の産物を残す**（式・生成した文章・読み直した式）。失敗をそのまま調べられます。
- **往復そのものに言語モデルは要らない。** 要るのは論文を手続きの種類に振り分ける工程だけです。

## 何を比べるか

```
Method text T ──▶ contingency-procedure2dsl ──▶ AST₁
                                               │
                                               ▼
                                     contingency-dsl2procedure
                                               │
                                               ▼
                                      generated text P
                                               │
                                               ▼
                               contingency-procedure2dsl ──▶ AST₂
```

AST（抽象構文木）は、スケジュールの式をパースした形です。論文ごとに 4 つの判定を記録し、PASS は (a) だけで決めます。

| キー | 判定 | 条件 |
|---|---|---|
| a | 2 つの AST が同じ手続きを表す | `normalize(AST₁) == normalize(AST₂)`（書く側が文章に戻さない注釈は先に除く） |
| b | 生成した文章をもう一度読める | `AST₂` が空でない |
| c | T と P の語の重なり | 小文字にした語の Jaccard 類似度。報告するだけ |
| d | 2 つの AST の書き方が同一 | `canonical_json(AST₁) == canonical_json(AST₂)` |

## インストール

Python 3.11 以上。OperantKit のパッケージはまだ PyPI に公開されておらず、このパッケージが依存する contingency-dsl-py を pip が GitHub から解決できないので、OperantKit のパッケージは依存の解決を止めて入れ、外部ライブラリを足します。

```bash
G=git+https://github.com/OperantKit
pip install --no-deps $G/contingency-dsl-e2e-roundtrip $G/contingency-dsl-py \
  $G/contingency-procedure2dsl@v0.1.0 $G/contingency-dsl2procedure@v0.1.0
pip install pyyaml pypdf pymupdf
```

pip（と `pip check`）は、contingency-dsl-py の開発版が宣言された版を満たさないという食い違いを報告します。以下のコマンドには影響しません。

手続きの種類は [contingency-dsl](https://github.com/OperantKit/contingency-dsl) の適合テストから読み取るので、それも clone し、`E2E_CONFORMANCE_ROOT` にその `conformance/` ディレクトリを指定します。

```bash
git clone https://github.com/OperantKit/contingency-dsl
export E2E_CONFORMANCE_ROOT="$PWD/contingency-dsl/conformance"
```

## 例

Method の一節を 1 つ往復させます。作業用のコーパスの抽出キャッシュに、仮の DOI で文章を置き、走らせます。

```bash
mkdir -p demo/corpus/extracted
cat > demo/corpus/extracted/10.0000_demo.txt <<'EOF'
Procedure
Lever presses were reinforced under a fixed-ratio 5 schedule: every fifth response produced a food pellet. Sessions were conducted daily and ended after 60 reinforcers or 60 min, whichever came first. Training continued until response rates were stable across five consecutive sessions.
EOF
e2e --corpus demo/corpus run --doi 10.0000/demo
# [PASS] 10.0000/demo: a=True b=True c=0.2 d=True
cat demo/corpus/generated/dsl/10.0000_demo.dsl        # FR5
cat demo/corpus/generated/compiled/10.0000_demo.txt   # Responses were reinforced under a fixed-ratio (FR) 5 schedule.
```

キャッシュの文章には 200 文字以上の本文が要ります。それより短いファイルは空のひな形とみなして捨てます。

## コマンド

| コマンド | すること |
|---|---|
| `e2e run --doi <doi>` / `--all` | 論文 1 本、または分類済みの全論文を往復させる |
| `e2e report` | 保存された結果から `corpus/doi-lists/*.md` を作り直す |
| `e2e list-procedures` | contingency-dsl から読み取った手続きの種類を表示する |
| `e2e extract --doi <doi>` / `--all` | 抽出キャッシュ `corpus/extracted/<slug>.txt` を埋める |
| `e2e classify --doi <doi>` / `--all` | 言語モデルで論文を手続きの種類に振り分ける |
| `e2e classify-prepare`、`next-batch`、`ingest-batch`、`classify-ingest`、`regenerate-agent` | API キーなしで、Claude Code のサブエージェントを通して分類する |
| `e2e second-rate`、`agreement` | 標本を 2 人目の評定者で分類し、手続きの種類ごとに Cohen の κ を出す |

`--corpus <dir>`（コマンドの前に置く）で `corpus/` 以外のコーパスを扱えます。分類とそのバックエンド・信頼性は [docs/ja/classification.md](docs/ja/classification.md) で説明しています。

## ファイル

| パス | 追跡 | 中身 |
|---|---|---|
| `corpus/state.json` | する | DOI ごとの手続きの種類と往復の結果 |
| `corpus/doi-lists/*.md` | する | 手続きの種類ごとの一覧。DOI 1 つにつき判定付きの 1 行。[`index.md`](corpus/doi-lists/index.md) に件数 |
| `corpus/extracted/<slug>.txt` | しない | DOI ごとの Method の文章（`<slug>` は DOI の `/` を `_` に置き換えたもの）。ファイルがあれば抽出は飛ばす |
| `corpus/generated/{dsl,compiled,dsl2}/` | しない | 式にした AST₁、生成した文章 P、式にした AST₂。式に書けない AST はコメント付きの JSON で保存する |

追跡しているコーパスには 580 の DOI があり、そのうち 39 が範囲外と分類されています（`corpus/state.json` で数えた値）。その元になった論文の本文は配布していないので、clone した直後の `corpus/extracted/` は空です。例のように Method の文章を自分で用意してください。

| 変数 | 必須 | 意味 |
|---|---|---|
| `E2E_CONFORMANCE_ROOT` | はい | contingency-dsl の `conformance/` ディレクトリ。未設定なら、この checkout の隣の `../contingency-dsl/conformance` を使う |
| `E2E_PAPER_SOURCES_ROOT` | いいえ | 手元にある論文の写しのディレクトリ。キャッシュが無いときに読む（構成は [docs/ja/classification.md](docs/ja/classification.md) の最後の節） |
| `E2E_CLASSIFIER_BACKEND` | いいえ | 分類のバックエンドを `anthropic` か `claude-cli` に固定する |

## 制限

- PASS は、読む側と書く側が互いに一致したという意味で、式が著者の実際の手続きと一致したという意味ではありません。両方の向きで同じ細部が落ちることがあります。
- 類似度 (c) は語の重なりの指標で、PASS には使いません。生成した文章はスケジュールしか述べないので値は低く、`corpus/state.json` で値のある 419 本の中央値は 0.017 です。
- 測っているのは、固定した contingency-procedure2dsl と contingency-dsl2procedure のタグ（`v0.1.0`）です。それより新しい版は、自分で入れない限りここでは試されません。
- 手続きの種類は言語モデルが付けたもので、その信頼性は 2 つのモデルの間で測ったものです。人の評定者とは比べていません。

## AI のコーディングエージェント向け

AI のコーディングエージェント向けの案内は [AGENTS.md](AGENTS.md) にあります。

## 開発

```bash
python -m venv .venv
G=git+https://github.com/OperantKit
.venv/bin/python -m pip install --no-deps -e . $G/contingency-dsl-py \
  $G/contingency-procedure2dsl@v0.1.0 $G/contingency-dsl2procedure@v0.1.0
.venv/bin/python -m pip install pyyaml pypdf pymupdf pytest
E2E_CONFORMANCE_ROOT=<path to contingency-dsl/conformance> .venv/bin/python -m pytest -q
```

## ライセンス

MIT。[LICENSE](LICENSE) を参照してください。
