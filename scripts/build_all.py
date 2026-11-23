#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 config/journals.json 批量生成 feeds。单项失败不影响其他项。"""
import json, subprocess, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    only = None
    if len(sys.argv) > 2 and sys.argv[1] == "--only":
        only = sys.argv[2]
    jobs = json.loads((ROOT / "config" / "journals.json").read_text(encoding="utf-8"))
    failed, ran = [], 0
    for j in jobs:
        if only and only not in j["label"]:
            continue
        cmd = [sys.executable, str(ROOT / j["script"])] + j["args"] + ["--out", str(ROOT / j["out"])]
        ran += 1
        print(f"\n=== {j['label']}", flush=True)
        try:
            r = subprocess.run(cmd, cwd=ROOT, timeout=900)
            if r.returncode != 0:
                failed.append(j["label"])
                print(f"[失败] {j['label']} returncode={r.returncode}", flush=True)
        except subprocess.TimeoutExpired:
            failed.append(j["label"])
            print(f"[超时] {j['label']}", flush=True)
        except Exception as e:
            failed.append(j["label"])
            print(f"[异常] {j['label']}: {e}", flush=True)
    print(f"\n完成 {ran - len(failed)}/{ran}，失败: {failed or '无'}", flush=True)
    return 0  # 让校验步骤判断产物是否为空


if __name__ == "__main__":
    sys.exit(main())
