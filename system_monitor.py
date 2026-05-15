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
import pynvml
import platform

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


def get_cpu_usage():
    """CPU 使用率を取得（値と文字列を返す）"""
    cpu_percent = psutil.cpu_percent(interval=None)
    info = f"""
    CPU: {platform.processor()}
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
    try:
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()

        if device_count == 0:
            return 0, "GPU デバイスが見つかりません"

        gpu_info = []
        max_util = 0
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = str(pynvml.nvmlDeviceGetName(handle))
            utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)

            if utilization.gpu > max_util:
                max_util = utilization.gpu

            gpu_info.append(f"  GPU {i}: {name}")
            gpu_info.append(f"    使用率：{utilization.gpu:.1f}% 温度：{temp}°C")

        return max_util, "\n".join(gpu_info)

    except pynvml.NVMLError:
        return 0, "GPU 情報を取得できません (NVIDIA GPU が必要)"
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass


def get_gpu_memory_usage():
    """GPU メモリ使用率を取得（最大GPUの百分率と情報を返す）"""
    try:
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()

        if device_count == 0:
            return 0, "GPU デバイスが見つかりません"

        gpu_info = []
        max_percent = 0
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = str(pynvml.nvmlDeviceGetName(handle))

            memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            total_gb = memory_info.total / (1024 ** 3)
            used_gb = memory_info.used / (1024 ** 3)
            free_gb = memory_info.free / (1024 ** 3)
            percent = (memory_info.used / memory_info.total) * 100

            if percent > max_percent:
                max_percent = percent
            gpu_info = f"""
           使用中：{used_gb:.2f} GB / {total_gb:.2f} GB ({percent:.1f}%)
           空き：{free_gb:.2f} GB/ {total_gb:.2f} GB ({100 - percent:.1f}%)"""

        return max_percent, gpu_info

    except pynvml.NVMLError:
        return 0, "GPU メモリ情報を取得できません (NVIDIA GPU が必要)"
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass


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
