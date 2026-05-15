# System Monitor TUI

リアルタイムのシステムモニター TUI ツール。4 画面分割で CPU、メモリ、GPU、GPU メモリ使用率を表示します。

## 機能

- **左上**: CPU 使用率（パーセント表示）
- **右上**: メモリ使用率（総量・使用中・空き容量）
- **左下**: GPU 使用率（各 GPU のグラフィックス・メモリ使用率）
- **右下**: GPU メモリ使用率（各 GPU の詳細情報）
- **更新間隔**: 0.5 秒ごと

## インストール

### uv を使用してインストール（推奨）
ツールとしてインストール
```bash
uv tool install .
```
更新
```bash
uv tool install . --force --reinstall
```

## 使用方法

### uv tool run で実行（推奨）

```bash
uv tool run system-monitor
```

### 直接インストールされたコマンドで実行

```bash
system-monitor
```

### Python スクリプトとして直接実行

```bash
uv run python system_monitor.py
```

### 依存パッケージ

以下のパッケージが必要です：

- `psutil` - システム情報取得用
- `rich` - TUI レンダリング用
- `pynvml` / `nvidia-ml-py` - GPU 監視用（NVIDIA GPU の場合）

## 要件

- Python 3.8+
- NVIDIA GPU（GPU 監視機能を使用する場合）

## 停止方法

`Ctrl+C` を押してツールを停止します。

## ライセンス

MIT License
