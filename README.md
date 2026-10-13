# System Monitor TUI

リアルタイムのシステムモニター TUI ツール。4 画面分割で CPU、メモリ、GPU、GPU メモリ使用率を表示します。

## 機能

- **左上**: CPU 使用率（パーセント表示）
- **右上**: メモリ使用率（総量・使用中・空き容量）
- **左下**: GPU 使用率（メイン GPU のグラフィックス・メモリ使用率。メイン GPU はディスプレイに接続されている GPU）
- **右下**: GPU メモリ使用率（メイン GPU の VRAM 使用量）
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
- `pynvml` / `nvidia-ml-py` - NVIDIA GPU の温度・使用率取得用

## 要件

- Python 3.12+（pyproject.toml 参照）
- Windows 10/11（GPU 監視は Windows パフォーマンスカウンタ \GPU Engine / \GPU Process Memory を使用。NVIDIA / AMD / Intel いずれの GPU にも対応）

## GPU 監視の仕組み

監視対象は **メイン GPU 1 台のみ**（ディスプレイに接続されている GPU）。ディスプレイ未接続の GPU（内蔵 GPU のみ有効な場合や、使用していない 2 枚目の GPU など）は表示しない。

- **メイン GPU の判定**: `EnumDisplayDevicesW` でアクティブなディスプレイを列挙し、`D3DKMTOpenAdapterFromHdc` でそのディスプレイに接続されている GPU の LUID を特定
- **NVIDIA GPU**: NVML（pynvml）。使用率・温度・メモリを取得
- **その他の GPU（AMD Radeon など）**: NVML が使えない場合、Windows の GPU パフォーマンスカウンタ (PDH) にフォールバック。使用率・VRAM 使用量を取得（温度は非対応）。カウンタの LUID がメイン GPU と一致するもののみ集計
- GPU 名と VRAM 合計は DXGI (IDXGIFactory1) から取得（失敗時は D3DKMT の LUID→名前対応 + レジストリ DriverDesc から取得）

## 停止方法

`Ctrl+C` を押してツールを停止します。

## ライセンス

MIT License
