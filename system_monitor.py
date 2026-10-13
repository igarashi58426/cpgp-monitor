#!/usr/bin/env python3
"""
システムモニター TUI ツール
4 画面分割で CPU、メモリ、GPU、GPU メモリ使用率を表示
時系列グラフ付き（過去90秒）
0.5 秒ごとに更新
"""

import time
import sys
from collections import deque
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
import psutil
import platform

try:
    import pynvml
except (ImportError, OSError):
    pynvml = None

from gpu_windows import get_monitor as _get_windows_gpu_monitor

# 履歴サイズ（秒数）
HISTORY_SIZE = 180 # データポイント（約90秒分更新）

# グラフ用文字
GRAPH_BARS = "▒"


def init_history():
    """履歴データを初期化"""
    return {
        'cpu': deque(maxlen=HISTORY_SIZE),
        'memory': deque(maxlen=HISTORY_SIZE),
        'gpu': deque(maxlen=HISTORY_SIZE),
        'gpu_memory': deque(maxlen=HISTORY_SIZE),
    }


def draw_graph(history, width=50):
    """
    履歴から縦棒グラフを生成（100%=10文字、罫線付き）
    罫線:
    100% ┌────┐
         │    │
         │    │
         │    │
      50%│    │
         │    │
         │  ▒ │
         │ ▒▒ │
         │▒▒▒ │
      0% └────┘
    """
    if not history:
        return " " * width
    # 履歴サイズが幅を超えないように制限（最大幅に合わせる）
    max_width = min(len(history), width)
    history = list(history)[-max_width:]

    height = 10  # 10分割（10%, 20%, ... 100%）

    # 各列（時間ポイント）の高さを計算
    cols = []
    for v in history:
        # 0-100 を 0-9 のインデックスに変換
        h = int((v / 100) * height)
        if h > height:
            h = height
        cols.append(h)

    # 罫線付きでグラフを構築
    lines = []
    for row in range(height):  # 0=上(100%), 9=下(0%)
        # 左端に目盛り
        if row == 0:
            label = "100%"
        elif row == 5:
            label = " 50%"
        elif row == 9:
            label = "  0%"
        else:
            label = "    "

        # 罫線
        border_left = "│"
        border_right = "│"

        bar = ""
        for col_idx, h in enumerate(cols):
            # この行が表示対象か判定（高い値から表示）
            if h >= (height - row):
                bar += "▒"
            else:
                bar += " "

        # 行を結合
        line = f"{label}{border_left}{bar}{border_right}"
        lines.append(line)

    # 罫線（上下）
    top_border = "    ┌" + "─" * len(cols) + "┐"
    bottom_border = "    └" + "─" * len(cols) + "┘"

    result = top_border + "\n" + "\n".join(lines) + "\n" + bottom_border
    return result


def _get_cpu_name():
    """CPU 名を取得（Windows はレジストリ、その他は platform.processor()）"""
    if platform.system() == "Windows":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as k:
                name, _ = winreg.QueryValueEx(k, "ProcessorNameString")
                return name.strip()
        except OSError:
            pass
    return platform.processor()


def _display_width(text):
    """文字列の表示幅を計算（全角=2、半角=1）"""
    import unicodedata

    return sum(
        2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text
    )


def _truncate_width(text, max_width):
    """表示幅 max_width 以内に文字列を切り詰める（超過時は … を付ける）"""
    import unicodedata

    width = 0
    for i, c in enumerate(text):
        w = 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
        if width + w > max_width - 1:  # … の分を残す
            return text[:i] + "…"
        width += w
    return text


def get_cpu_usage():
    """CPU 使用率を取得（値と文字列を返す）"""
    cpu_percent = psutil.cpu_percent(interval=None)
    # メモリ情報の最大表示幅に合わせて CPU 名を切り詰める（折り返し防止）
    _, mem_info = get_memory_usage()
    mem_width = max(
        _display_width(line.strip()) for line in mem_info.strip().splitlines()
    )
    prefix_width = _display_width("CPU: ")
    name = _truncate_width(_get_cpu_name(), mem_width - prefix_width)
    info = f"""
    CPU: {name}
    使用率：{cpu_percent:.1f}%"""
    return cpu_percent, info


def get_memory_usage():
    """メモリ使用率を取得（値と文字列を返す）"""
    memory = psutil.virtual_memory()
    percent = memory.percent
    total_gb = memory.total / (1024 ** 3)
    available_gb = memory.available / (1024 ** 3)
    used_gb = memory.used / (1024 ** 3)

    info = f"""
       使用中：{used_gb:.1f} GB / {total_gb:.1f} GB ({percent:.1f}%)
       空き：{available_gb:.1f} GB / {total_gb:.1f} GB ({100 - percent:.1f}%)
"""
    return percent, info


def get_gpu_usage():
    """GPU 使用率を取得（最大GPUの百分率と情報を返す）"""
    if pynvml is not None:
        try:
            return _get_nvidia_gpu_usage()
        except pynvml.NVMLError:
            pass
    return _get_windows_gpu_usage()


def _get_nvidia_gpu_usage():
    """NVIDIA GPU 使用率（NVML）"""
    pynvml.nvmlInit()
    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = str(pynvml.nvmlDeviceGetName(handle))
        utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)

        gpu_info = f"  GPU: {name}\n    使用率：{utilization.gpu:.1f}% 温度：{temp}°C"
        return utilization.gpu, gpu_info
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass


def _get_windows_gpu_usage():
    """Windows パフォーマンスカウンタ経由の GPU 使用率（AMD / Intel / NVIDIA 共通）"""
    gpus = _get_windows_gpu_monitor().snapshot()
    if not gpus:
        return 0, "GPU 情報を取得できません"

    name, util, _used, _total = gpus[0]
    gpu_info = f"  GPU: {name}\n    使用率：{util:.1f}%"
    return util, gpu_info


def get_gpu_memory_usage():
    """GPU メモリ使用率を取得（最大GPUの百分率と情報を返す）"""
    if pynvml is not None:
        try:
            return _get_nvidia_gpu_memory_usage()
        except pynvml.NVMLError:
            pass
    return _get_windows_gpu_memory_usage()


def _get_nvidia_gpu_memory_usage():
    """NVIDIA GPU メモリ（NVML）"""
    pynvml.nvmlInit()
    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)

        memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        total_gb = memory_info.total / (1024 ** 3)
        used_gb = memory_info.used / (1024 ** 3)
        free_gb = memory_info.free / (1024 ** 3)
        percent = (memory_info.used / memory_info.total) * 100

        gpu_info = f"""
           使用中：{used_gb:.2f} GB / {total_gb:.2f} GB ({percent:.1f}%)
           空き：{free_gb:.2f} GB/ {total_gb:.2f} GB ({100 - percent:.1f}%)"""

        return percent, gpu_info
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass


def _get_windows_gpu_memory_usage():
    """Windows パフォーマンスカウンタ経由の GPU メモリ（AMD / Intel / NVIDIA 共通）"""
    gpus = _get_windows_gpu_monitor().snapshot()
    if not gpus:
        return 0, "GPU メモリ情報を取得できません"

    _name, _util, used, total = gpus[0]
    if total <= 0:
        return 0, "GPU メモリ情報を取得できません"
    percent = (used / total) * 100
    total_gb = total / (1024 ** 3)
    used_gb = used / (1024 ** 3)
    free_gb = max(0.0, total_gb - used_gb)
    gpu_info = f"""
       使用中：{used_gb:.2f} GB / {total_gb:.2f} GB ({percent:.1f}%)
       空き：{free_gb:.2f} GB/ {total_gb:.2f} GB ({100 - percent:.1f}%)"""
    return percent, gpu_info


def create_layout():
    """レイアウトを作成"""
    layout = Layout()

    layout.split(
        Layout(name="top", size=16),
        Layout(name="bottom")
    )

    layout["top"].split_row(
        Layout(name="left"),
        Layout(name="right")
    )

    layout["bottom"].split_row(
        Layout(name="bottom_left"),
        Layout(name="bottom_right")
    )

    return layout


def update_layout(layout, history, console=None):
    """レイアウトを更新"""
    if console is None:
        console = Console()

    # コンソール幅から動的に計算（2 列分割・ボーダー・ラベルを考慮）
    graph_width = max(10, (console.width // 2) - 10)

    # CPU 取得と履歴追加
    cpu_val, cpu_info = get_cpu_usage()
    history['cpu'].append(cpu_val)

    # メモリ取得と履歴追加
    mem_val, mem_info = get_memory_usage()
    history['memory'].append(mem_val)

    # GPU 取得と履歴追加
    gpu_val, gpu_info = get_gpu_usage()
    history['gpu'].append(gpu_val)

    # GPU メモリ取得と履歴追加
    gpu_mem_val, gpu_mem_info = get_gpu_memory_usage()
    history['gpu_memory'].append(gpu_mem_val)

    # グラフ描画（動的に計算した幅を使用）
    cpu_graph = draw_graph(history['cpu'], width=graph_width)
    mem_graph = draw_graph(history['memory'], width=graph_width)
    gpu_graph = draw_graph(history['gpu'], width=graph_width)
    gpu_mem_graph = draw_graph(history['gpu_memory'], width=graph_width)

    # 左上：CPU 使用率
    cpu_panel = Panel(
        f"[bold cyan]CPU[/bold cyan] {cpu_info.strip()}\n[green]{cpu_graph}[/green]",
        title="[bold]システムモニター[/bold]",
        border_style="green"
    )
    layout["left"].update(cpu_panel)

    # 右上：メモリ使用率
    memory_panel = Panel(
        f"[bold magenta]メモリ[/bold magenta] {mem_info.strip()}\n[green]{mem_graph}[/green]",
        border_style="yellow"
    )
    layout["right"].update(memory_panel)

    # 左下：GPU 使用率
    gpu_panel = Panel(
        f"[bold green]GPU[/bold green] {gpu_info.strip()}\n[green]{gpu_graph}[/green]",
        border_style="cyan"
    )
    layout["bottom_left"].update(gpu_panel)

    # 右下：GPU メモリ使用率
    gpu_mem_panel = Panel(
        f"[bold blue]GPU メモリ[/bold blue] {gpu_mem_info.strip()}\n[green]{gpu_mem_graph}[/green]",
        border_style="magenta"
    )
    layout["bottom_right"].update(gpu_mem_panel)


def main():
    """メイン関数"""
    console = Console()
    layout = create_layout()
    history = init_history()

    # 初期更新
    update_layout(layout, history, console)

    try:
        with Live(layout, console=console, refresh_per_second=2):
            while True:
                time.sleep(0.5)
                update_layout(layout, history, console)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
