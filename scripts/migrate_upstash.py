"""Copy every key from one Upstash Redis instance to another.

用於更換 Upstash 區域。加密金鑰不變，所以搬過去的 token 依然有效，
使用者不需要重新連結 Google。

用法（PowerShell）：
    $env:SRC_URL   = "https://舊的.upstash.io"
    $env:SRC_TOKEN = "舊的 token"
    $env:DST_URL   = "https://新的.upstash.io"
    $env:DST_TOKEN = "新的 token"
    python scripts/migrate_upstash.py            # 先試跑，不寫入
    python scripts/migrate_upstash.py --apply    # 實際搬移
"""

from __future__ import annotations

import os
import sys

import requests

TIMEOUT = 15


def _command(url: str, token: str, *args: str):
    resp = requests.post(
        url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        json=list(args),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(payload["error"])
    return payload.get("result") if isinstance(payload, dict) else payload


def scan_all(url: str, token: str) -> list[str]:
    keys: list[str] = []
    cursor = "0"
    while True:
        cursor, batch = _command(url, token, "SCAN", cursor, "COUNT", "200")
        keys.extend(batch or [])
        if str(cursor) == "0":
            return keys


def main() -> int:
    apply = "--apply" in sys.argv

    try:
        src_url, src_token = os.environ["SRC_URL"], os.environ["SRC_TOKEN"]
        dst_url, dst_token = os.environ["DST_URL"], os.environ["DST_TOKEN"]
    except KeyError as missing:
        print(f"缺少環境變數 {missing}")
        return 1

    if src_url.rstrip("/") == dst_url.rstrip("/"):
        print("來源與目標是同一個資料庫，停止。")
        return 1

    print(f"來源: {src_url}")
    print(f"目標: {dst_url}")
    print(f"模式: {'實際寫入' if apply else '試跑（不寫入）'}")
    print()

    keys = scan_all(src_url, src_token)
    print(f"來源共有 {len(keys)} 個鍵")

    existing = scan_all(dst_url, dst_token)
    if existing:
        print(f"⚠ 目標已有 {len(existing)} 個鍵：{existing[:5]}")
        if apply:
            print("  同名鍵會被覆蓋。若不是預期行為請先中止。")
    print()

    copied = skipped = 0
    for key in keys:
        value = _command(src_url, src_token, "GET", key)
        if value is None:
            print(f"  跳過 {key}（不是字串型別或已消失）")
            skipped += 1
            continue

        # 保留剩餘存活時間，pkce 這類暫存鍵才不會變成永久資料。
        ttl = _command(src_url, src_token, "TTL", key)
        ttl = int(ttl) if ttl is not None else -1

        label = f"{key}  ({len(value)} 字元" + (f", TTL {ttl}s)" if ttl > 0 else ")")
        if apply:
            if ttl > 0:
                _command(dst_url, dst_token, "SET", key, value, "EX", str(ttl))
            else:
                _command(dst_url, dst_token, "SET", key, value)
            print(f"  已複製 {label}")
        else:
            print(f"  將複製 {label}")
        copied += 1

    print()
    if not apply:
        print(f"試跑完成：{copied} 個鍵待複製，{skipped} 個略過。")
        print("確認無誤後加上 --apply 實際執行。")
        return 0

    print(f"複製完成：{copied} 個，略過 {skipped} 個。")
    print("驗證中…")

    after = scan_all(dst_url, dst_token)
    print(f"  目標現有 {len(after)} 個鍵")

    mismatched = []
    for key in keys:
        if _command(src_url, src_token, "GET", key) != _command(
            dst_url, dst_token, "GET", key
        ):
            mismatched.append(key)

    if mismatched:
        print(f"  ✗ 內容不一致: {mismatched}")
        return 1

    print("  ✓ 所有鍵的內容完全一致")
    print()
    print("接著把 Render 的 UPSTASH_REDIS_REST_URL / TOKEN 換成新的並重新部署。")
    print("舊資料庫先留著別刪，確認新的運作正常後再刪。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
