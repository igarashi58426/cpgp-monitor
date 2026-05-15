#!/usr/bin/env python3
"""
システムモニター TUI ツール
4 画面分割で CPU、メモリ、GPU、GPU メモリ使用率を表示
0.5 秒ごとに更新
"""

import time
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
import psutil
import pynvml


def get_cpu_name():
    """CPU 名を取得"""
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('model name'):
                    return line.split(':')[1].strip()
    except Exception:
        pass
    return "Unknown CPU"


def get_cpu_usage():
    """CPU 使用率を取得"""
    cpu_percent = psutil.cpu_percent(interval=None)
    cpu_freq = psutil.cpu_freq()
    physical_count = psutil.cpu_count(logical=False)
    logical_count = psutil.cpu_count()
    
    return f"""{get_cpu_name()}
  使用率：{cpu_percent:.1f}%
  周波数：{cpu_freq.current/1000:.2f} MHz
  コア数：物理 {physical_count}, 論理 {logical_count}"""


def get_memory_usage():
    """メモリ使用率を取得"""
    memory = psutil.virtual_memory()
    percent = memory.percent
    total_gb = memory.total / (1024 ** 3)
    available_gb = memory.available / (1024 ** 3)
    used_gb = memory.used / (1024 ** 3)
    
    return f"""
  使用率: {percent:.1f}%
  総量：{total_gb:.1f} GB
  使用中：{used_gb:.1f} GB
  空き：{available_gb:.1f} GB
"""


def get_gpu_usage():
    """GPU 使用率を取得"""
    try:
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        
        if device_count == 0:
            return "GPU デバイスが見つかりません"
        
        gpu_info = []
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = str(pynvml.nvmlDeviceGetName(handle))
            utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
            
            gpu_info.append(f"  GPU {i}: {name}")
            gpu_info.append(f"    グラフィックス：{utilization.gpu:.1f} %")
            gpu_info.append(f"    メモリ：{utilization.memory:.1f} %")
        
        return "\n".join(gpu_info)
    
    except pynvml.NVMLError:
        return "GPU 情報を取得できません (NVIDIA GPU が必要)"
    finally:
        try:
            pynvml.nvmlShutdown()
        except:
            pass


def get_gpu_memory_usage():
    """GPU メモリ使用率を取得"""
    try:
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        
        if device_count == 0:
            return "GPU デバイスが見つかりません"
        
        gpu_info = []
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = str(pynvml.nvmlDeviceGetName(handle))
            
            memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            total_gb = memory_info.total / (1024 ** 3)
            used_gb = memory_info.used / (1024 ** 3)
            free_gb = memory_info.free / (1024 ** 3)
            percent = (memory_info.used / memory_info.total) * 100
            
            gpu_info.append(f"  GPU {i}: {name}")
            gpu_info.append(f"    総量：{total_gb:.2f} GB")
            gpu_info.append(f"    使用中：{used_gb:.2f} GB ({percent:.1f} %) ")
            gpu_info.append(f"    空き：{free_gb:.2f} GB")
        
        return "\n".join(gpu_info)
    
    except pynvml.NVMLError:
        return "GPU メモリ情報を取得できません (NVIDIA GPU が必要)"
    finally:
        try:
            pynvml.nvmlShutdown()
        except:
            pass


def create_layout():
    """レイアウトを作成"""
    layout = Layout()
    
    layout.split(
        Layout(name="top", size=10),
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


def update_layout(layout):
    """レイアウトを更新"""
    # 左上：CPU 使用率
    cpu_panel = Panel(
        f"[bold cyan]CPU 使用率[/bold cyan]\n\n{get_cpu_usage()}",
        title="[bold]システムモニター[/bold]",
        border_style="green"
    )
    layout["left"].update(cpu_panel)
    
    # 右上：メモリ使用率
    memory_panel = Panel(
        f"[bold magenta]メモリ使用率[/bold magenta]\n\n{get_memory_usage()}",
        border_style="yellow"
    )
    layout["right"].update(memory_panel)
    
    # 左下：GPU 使用率
    gpu_panel = Panel(
        f"[bold green]GPU 使用率[/bold green]\n\n{get_gpu_usage()}",
        border_style="cyan"
    )
    layout["bottom_left"].update(gpu_panel)
    
    # 右下：GPU メモリ使用率
    gpu_mem_panel = Panel(
        f"[bold blue]GPU メモリ使用率[/bold blue]\n\n{get_gpu_memory_usage()}",
        border_style="magenta"
    )
    layout["bottom_right"].update(gpu_mem_panel)


def main():
    """メイン関数"""
    console = Console()
    layout = create_layout()
    
    # 初期更新
    update_layout(layout)
    
    with Live(layout, console=console, refresh_per_second=2):
        while True:
            time.sleep(0.5)
            update_layout(layout)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nモニターを停止しました")
