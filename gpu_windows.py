#!/usr/bin/env python3
r"""
Windows GPU バックエンド（ベンダー非依存: NVIDIA / AMD / Intel 共通）

- GPU 使用率 / VRAM 使用量: PDH パフォーマンスカウンタ
    \GPU Engine(*)\Utilization Percentage
    \GPU Process Memory(*)\Local Usage / \Non Local Usage
- GPU 名 / VRAM 合計: DXGI (IDXGIFactory1::EnumAdapters1)
    DXGI が使えない環境では LUID ラベルで表示（機能は生かす）
"""

import ctypes
import re
import struct
from ctypes import wintypes

PDH_MORE_DATA = 0x800007D2
PDH_FMT_DOUBLE = 0x00000200

_pdh = ctypes.WinDLL("pdh.dll")
_pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, wintypes.WPARAM, ctypes.POINTER(ctypes.c_void_p)]
_pdh.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.WPARAM, ctypes.POINTER(ctypes.c_void_p)]
_pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
_pdh.PdhGetFormattedCounterArrayW.argtypes = [
    ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
]

_RE_LUID = re.compile(r"luid_0x([0-9a-fA-F]+)_0x([0-9a-fA-F]+)")


def _parse_instance_name(name):
    """カウンタインスタンス名から (luid_key, engtype) を取り出す"""
    m = _RE_LUID.search(name)
    if not m:
        return None, None
    luid = (int(m.group(2), 16), int(m.group(1), 16))  # (LowPart, HighPart)
    parts = name.split("_")
    engtype = None
    for i, p in enumerate(parts):
        if p == "engtype" and i + 1 < len(parts):
            engtype = parts[i + 1]
    return luid, engtype


def _read_counter_array(counter):
    """ワイルドカードカウンタの全インスタンス値を {name: value} で返す"""
    size = wintypes.DWORD(0)
    count = wintypes.DWORD(0)
    ret = _pdh.PdhGetFormattedCounterArrayW(
        counter, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), None
    ) & 0xFFFFFFFF
    if ret != PDH_MORE_DATA:
        return {}
    for _ in range(4):  # インスタンス増加でのリトライ
        buf = ctypes.create_string_buffer(size.value)
        ret = _pdh.PdhGetFormattedCounterArrayW(
            counter, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), buf
        ) & 0xFFFFFFFF
        if ret == PDH_MORE_DATA:
            size.value *= 2
            continue
        if ret != 0:
            return {}
        # PDH_FMT_COUNTERVALUE_ITEM_W = { LPWSTR szName; { DWORD CStatus; double value } }
        #   → 1 項目 24 バイト (x64)、名前は +0、値は +16
        items = []
        for i in range(count.value):
            off = i * 24
            name_ptr = ctypes.c_void_p.from_buffer_copy(buf, off).value
            value = struct.unpack_from("<d", buf, off + 16)[0]
            items.append((ctypes.wstring_at(name_ptr), value))
        return dict(items)
    return {}


class _Adapter:
    def __init__(self, name, luid, dedicated, shared, has_outputs=True):
        self.name = name
        self.luid = luid  # (high, low)
        self.dedicated = dedicated
        self.shared = shared
        self.has_outputs = has_outputs  # ディスプレイ接続の有無


def _enum_adapters_dxgi():
    """DXGI 経由でアダプタ (名前, LUID, VRAM) を列挙"""
    import uuid

    dxgi = ctypes.WinDLL("dxgi.dll")

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", ctypes.c_ulong), ("HighPart", ctypes.c_long)]

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8),
        ]

    class DXGI_ADAPTER_DESC1(ctypes.Structure):
        _fields_ = [
            ("Description", ctypes.c_wchar * 128),
            ("Flags", ctypes.c_uint),
            ("DedicatedVideoMemory", ctypes.c_uint64),
            ("DedicatedSystemMemory", ctypes.c_uint64),
            ("SharedSystemMemory", ctypes.c_uint64),
            ("AdapterLuid", LUID),
            ("NumSubDevices", ctypes.c_uint),
        ]

    def call_vt(obj, index, restype, *args):
        vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))[0]
        fn = ctypes.cast(vtbl + index * 8, ctypes.POINTER(ctypes.c_void_p))[0]
        # byref() 等は c_void_p として渡す
        proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *([ctypes.c_void_p] * len(args)))
        return proto(fn)(obj, *args)

    u = uuid.UUID("50c83a1c-e072-4c48-87b0-3630fa36a6d0")  # IID_IDXGIFactory2
    iid = GUID(u.time_low, u.time_mid, u.time_hi_version, tuple(u.bytes_le[8:16]))
    factory = ctypes.c_void_p()
    hr = dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory))
    if hr != 0 or not factory:
        return None

    adapters = []
    i = 0
    while True:
        adapter = ctypes.c_void_p()
        hr = call_vt(factory, 8, ctypes.c_long, i, ctypes.byref(adapter))  # EnumAdapters1
        if hr != 0:
            break
        desc = DXGI_ADAPTER_DESC1()
        hr = call_vt(adapter, 6, ctypes.c_long, ctypes.byref(desc))  # GetDesc1
        if hr == 0:
            # ソフトウェアアダプタ（WARP 等）は除外
            software = desc.Flags & 2  # DXGI_ADAPTER_FLAG_SOFTWARE
            # ディスプレイ出力の有無を確認
            has_outputs = False
            if not software:
                output = ctypes.c_void_p()
                if call_vt(adapter, 3, ctypes.c_long, 0, ctypes.byref(output)) == 0:  # EnumOutputs
                    has_outputs = True
                    call_vt(output, 2, ctypes.c_long)  # Release
            luid = (desc.AdapterLuid.LowPart, desc.AdapterLuid.HighPart)
            adapters.append(_Adapter(
                desc.Description,
                luid,
                desc.DedicatedVideoMemory,
                desc.SharedSystemMemory,
                has_outputs,
            ))
        call_vt(adapter, 2, ctypes.c_long)  # Release
    call_vt(factory, 2, ctypes.c_long)  # Release
    # ディスプレイ非接続の GPU を除外
    adapters = [a for a in adapters if a.has_outputs]
    return adapters or None


def _display_luid_name_map():
    """ディスプレイごとに接続先 GPU の LUID を特定し {luid: GPU名} を返す

    EnumDisplayDevicesW でアクティブなディスプレイを列挙し、
    D3DKMTOpenAdapterFromDeviceName で各ディスプレイに対応する LUID を取得する。
    """
    user32 = ctypes.WinDLL("user32.dll")
    gdi32 = ctypes.WinDLL("gdi32.dll")

    class DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("DeviceName", wintypes.WCHAR * 32),
            ("DeviceString", wintypes.WCHAR * 128),
            ("StateFlags", wintypes.DWORD),
            ("DeviceID", wintypes.WCHAR * 128),
            ("DeviceKey", wintypes.WCHAR * 128),
        ]

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", ctypes.c_ulong), ("HighPart", ctypes.c_long)]

    class OPEN_ADAPTER(ctypes.Structure):
        _fields_ = [
            ("hDc", ctypes.c_void_p),
            ("hAdapter", ctypes.c_uint),
            ("AdapterLuid", LUID),
        ]

    ATTACHED_TO_DESKTOP = 0x00000001
    result = {}
    i = 0
    while True:
        dev = DISPLAY_DEVICEW()
        dev.cb = ctypes.sizeof(dev)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(dev), 0):
            break
        i += 1
        if not (dev.StateFlags & ATTACHED_TO_DESKTOP):
            continue
        hdc = gdi32.CreateDCW(dev.DeviceName, None, None, None)
        if not hdc:
            continue
        info = OPEN_ADAPTER()
        info.hDc = hdc
        if gdi32.D3DKMTOpenAdapterFromHdc(ctypes.byref(info)) == 0:
            result[(info.AdapterLuid.LowPart, info.AdapterLuid.HighPart)] = dev.DeviceString
        gdi32.DeleteDC(hdc)
    return result


def _active_display_gpu_names():
    """ディスプレイが接続されている GPU 名の一覧を取得（EnumDisplayDevicesW）"""
    user32 = ctypes.WinDLL("user32.dll")

    class DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("DeviceName", wintypes.WCHAR * 32),
            ("DeviceString", wintypes.WCHAR * 128),
            ("StateFlags", wintypes.DWORD),
            ("DeviceID", wintypes.WCHAR * 128),
            ("DeviceKey", wintypes.WCHAR * 128),
        ]

    ATTACHED_TO_DESKTOP = 0x00000001
    names = set()
    i = 0
    while True:
        dev = DISPLAY_DEVICEW()
        dev.cb = ctypes.sizeof(dev)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(dev), 0):
            break
        if dev.StateFlags & ATTACHED_TO_DESKTOP:
            names.add(dev.DeviceString)
        i += 1
    return names


def _enum_adapters_registry():
    """フォールバック: レジストリからディスプレイアダプタ名を取得（LUID は不明）"""
    import winreg

    key_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    active_names = _active_display_gpu_names()
    adapters = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as base:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(base, i)
                    i += 1
                except OSError:
                    break
                if not sub.startswith("0"):
                    continue
                try:
                    with winreg.OpenKey(base, sub) as k:
                        name, _ = winreg.QueryValueEx(k, "DriverDesc")
                        try:
                            mem, _ = winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")
                        except OSError:
                            mem = 0
                        # ディスプレイが接続されている GPU のみ残す
                        has_outputs = any(
                            a.lower() in name.lower() or name.lower() in a.lower()
                            for a in active_names
                        )
                        if not has_outputs:
                            continue
                        adapters.append(_Adapter(name, None, mem or 0, 0))
                except OSError:
                    continue
    except OSError:
        pass
    return adapters


_RE_PID = re.compile(r"pid_(\d+)")


def _display_luids(local):
    """DWM（デスクトップ描画）プロセスが使用している GPU の LUID 一覧を返す

    DWM はディスプレイに接続されている GPU でのみ動作するため、
    その LUID を「接続中 GPU」として判定に使う。
    """
    import psutil

    try:
        dwm_pids = {p.pid for p in psutil.process_iter(["name"]) if p.info["name"] == "dwm.exe"}
    except Exception:
        return set()

    luids = set()
    for name in local:
        m_pid = _RE_PID.search(name)
        m_luid = _RE_LUID.search(name)
        if not m_pid or not m_luid:
            continue
        luid = (int(m_luid.group(2), 16), int(m_luid.group(1), 16))
        if int(m_pid.group(1)) in dwm_pids:
            luids.add(luid)
    return luids


class WindowsGpuMonitor:
    """GPU 使用率・VRAM 使用量の取得（PDH + DXGI）"""

    def __init__(self):
        self._query = ctypes.c_void_p()
        self._counters = {}
        self._adapters = {}

        adapters = _enum_adapters_dxgi()
        if adapters is None:
            adapters = _enum_adapters_registry()
        # ディスプレイ接続 GPU の LUID → 名前対応表
        display_map = _display_luid_name_map()
        if display_map:
            self._display_luids = set(display_map)
            reg_adapters = _enum_adapters_registry() or []
            for luid, name in display_map.items():
                total = 0
                for a in reg_adapters:
                    if a.name.lower() == name.lower():
                        total = a.dedicated
                        break
                self._adapters[luid] = _Adapter(name, luid, total, 0)
        else:
            self._display_luids = None
        for i, a in enumerate(adapters):
            if a.luid is None:
                # LUID 不明（フォールバック）：衝突しない仮キーで登録
                self._adapters[("unmatched", i)] = a
            else:
                self._adapters[a.luid] = a

        self._available = True
        try:
            if _pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query)) != 0:
                self._available = False
                return
            paths = {
                "engine": r"\GPU Engine(*)\Utilization Percentage",
                "local": r"\GPU Process Memory(*)\Local Usage",
                "nonlocal": r"\GPU Process Memory(*)\Non Local Usage",
            }
            for key, path in paths.items():
                holder = ctypes.c_void_p()
                ret = _pdh.PdhAddEnglishCounterW(self._query, path, 0, ctypes.byref(holder))
                if ret != 0:
                    self._available = False
                    return
                self._counters[key] = holder
            # 使用率カウンタは 2 サンプル必要
            _pdh.PdhCollectQueryData(self._query)
        except Exception:
            self._available = False

    @property
    def available(self):
        return self._available

    def _luid_name(self, luid):
        a = self._adapters.get(luid)
        if a is not None:
            return a.name
        # LUID 不明アダプタに順に名前を充てる
        for key, a in self._adapters.items():
            if isinstance(key, tuple) and key[0] == "unmatched":
                self._adapters[luid] = a
                del self._adapters[key]
                return a.name
        return f"GPU (LUID 0x{luid[1]:08x})"

    def _luid_total(self, luid):
        a = self._adapters.get(luid)
        if a is not None:
            if a.luid is not None:
                return a.dedicated + a.shared
            return a.dedicated
        return 0

    def snapshot(self):
        """全 GPU の使用率・メモリを取得
        戻り値: [(name, util_percent, mem_used_bytes, mem_total_bytes), ...]
        """
        if not self._available:
            return []
        _pdh.PdhCollectQueryData(self._query)

        engine = _read_counter_array(self._counters["engine"])
        local = _read_counter_array(self._counters["local"])
        nonlocal_ = _read_counter_array(self._counters["nonlocal"])

        # 使用率: LUID × engtype ごとに合計 → engtype の最大値（タスクマネージャ方式）
        util = {}  # luid -> {engtype: sum}
        for name, value in engine.items():
            luid, engtype = _parse_instance_name(name)
            if luid is None or engtype is None:
                continue
            util.setdefault(luid, {}).setdefault(engtype, 0.0)
            util[luid][engtype] += value

        # メモリ: LUID ごとに合計
        mem = {}
        for src in (local, nonlocal_):
            for name, value in src.items():
                luid, _ = _parse_instance_name(name)
                if luid is None:
                    continue
                mem[luid] = mem.get(luid, 0.0) + value

        # ディスプレイ接続中 GPU（DWM が使用中の LUID）のみに絞る
        display_luids = self._display_luids or _display_luids(local)
        if display_luids:
            luids = [l for l in sorted(set(util) | set(mem)) if l in display_luids]
        else:
            luids = sorted(set(util) | set(mem))
        result = []
        for luid in luids:
            per_engine = util.get(luid, {})
            util_percent = min(100.0, max(per_engine.values())) if per_engine else 0.0
            name = self._luid_name(luid)
            total = self._luid_total(luid)
            result.append((name, util_percent, mem.get(luid, 0.0), total))
        return result


_monitor = None


def get_monitor():
    """シングルトン取得（PDH クエリは使い回す）"""
    global _monitor
    if _monitor is None:
        _monitor = WindowsGpuMonitor()
    return _monitor
