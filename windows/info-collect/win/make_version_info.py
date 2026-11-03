#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_version_info.py —— 生成 PyInstaller 的 Windows 版本资源

版本号的唯一来源是 config.APP_VERSION。build_exe.bat 会在打包前调用本脚本，
生成 version_info.txt 再交给 PyInstaller，这样 exe 文件属性里的版本不会和
托盘/状态页显示的版本号分家。

单独运行：
    py -3 -X utf8 make_version_info.py
"""

from __future__ import annotations

from pathlib import Path

import config


def _parts(version: str) -> tuple[int, int, int, int]:
    """把 "0.3" / "0.3.1" 补成 Windows 需要的四段版本号。"""
    nums: list[int] = []
    for seg in str(version).split("."):
        try:
            nums.append(max(0, int(seg)))
        except ValueError:
            nums.append(0)
    nums = (nums + [0, 0, 0, 0])[:4]
    return tuple(nums)  # type: ignore[return-value]


def main() -> int:
    v = _parts(config.APP_VERSION)
    dotted = ".".join(str(x) for x in v)
    text = f"""# UTF-8
# 由 make_version_info.py 生成，不要手改；版本号改 config.APP_VERSION。
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={v},
    prodvers={v},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '080404b0',
          [StringStruct('CompanyName', 'InfoCollect'),
           StringStruct('FileDescription', 'InfoCollect 时间去向记录器'),
           StringStruct('FileVersion', '{dotted}'),
           StringStruct('InternalName', 'InfoCollect'),
           StringStruct('OriginalFilename', 'InfoCollect.exe'),
           StringStruct('ProductName', 'InfoCollect'),
           StringStruct('ProductVersion', '{dotted}')])
      ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""
    out = Path(__file__).resolve().parent / "version_info.txt"
    out.write_text(text, encoding="utf-8")
    print(f"已生成 {out}（版本 {dotted}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
