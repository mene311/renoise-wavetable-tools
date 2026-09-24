#!/usr/bin/env python3
"""Drive the real pages in a browser and fail on anything that looks wrong.

Serves docs/ locally, then:
  builder  drops a synthesised 12-frame wavetable, builds, re-reads the instrument it produced
  library  clicks a row, switches to the by-category view, runs a batch download
  both     collects console errors and page exceptions, which is how the "WT is not defined"
           and CORS faults showed up

    ./browser_check.py                 against a local server
    ./browser_check.py --url https://mene311.github.io/renoise-wavetable-tools/
"""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

DOCS = Path(__file__).resolve().parent.parent / "docs"
results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    results.append((bool(ok), name, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


class ReusableServer(socketserver.TCPServer):
    allow_reuse_address = True


def serve(port: int = 0) -> socketserver.TCPServer:
    """Bind an ephemeral port unless one is asked for, so a stale listener can't collide."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DOCS))
    httpd = ReusableServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


MAKE_WAV = """
(frames, frameSize, sampleRate) => {
  const total = frames * frameSize;
  const buf = new ArrayBuffer(44 + total * 2);
  const view = new DataView(buf);
  const str = (off, t) => { for (let i = 0; i < t.length; i++) view.setUint8(off + i, t.charCodeAt(i)); };
  str(0, "RIFF"); view.setUint32(4, 36 + total * 2, true); str(8, "WAVEfmt ");
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  str(36, "data"); view.setUint32(40, total * 2, true);
  for (let f = 0; f < frames; f++) {
    const harmonics = 1 + f * 2;
    for (let i = 0; i < frameSize; i++) {
      let v = 0;
      for (let h = 0; h < harmonics; h++)
        v += Math.sin(2 * Math.PI * (2 * h + 1) * i / frameSize) / (2 * h + 1);
      view.setInt16(44 + (f * frameSize + i) * 2, Math.max(-1, Math.min(1, v)) * 32000, true);
    }
  }
  return new Uint8Array(buf);
}
"""


def test_builder(page, base: str, errors: list[str]) -> None:
    page.goto(f"{base}/index.html", wait_until="load")
    check(page.evaluate("typeof WTBuilder === 'object'"), "module global exists",
          "WTBuilder published by wt-builder.js")
    check(page.evaluate("typeof WT === 'object'"), "page alias points at it", "const WT = WTBuilder")

    wav = page.evaluate("(" + MAKE_WAV + ")(12, 2048, 44100)")
    page.evaluate(
        """(bytes) => {
             const file = new File([new Uint8Array(bytes)], "smoke table.wav", {type: "audio/wav"});
             const dt = new DataTransfer();
             dt.items.add(file);
             const input = document.getElementById("files");
             input.files = dt.files;
             input.dispatchEvent(new Event("change"));
           }""",
        wav,
    )
    page.wait_for_function(
        "() => document.getElementById('fileinfo').textContent.includes('smoke table.wav')",
        timeout=20000,
    )
    check(True, "builder read a 12-frame wavetable",
          page.inner_text("#fileinfo").strip()[:80])

    page.click("#build")
    page.wait_for_selector("#results tr", timeout=60000)
    row = page.inner_text("#results tr").replace("\n", " ")
    check(".xrni" in row, "builder wrote an instrument", row[:80])

    href = page.get_attribute("#results tr a", "href")
    name = page.get_attribute("#results tr a", "download") or ""
    check(bool(href) and name.endswith(".xrni"), "download link", name[:60])

    parsed = page.evaluate(
        """async (href) => {
             const bytes = new Uint8Array(await (await fetch(href)).arrayBuffer());
             const entries = await WT.listZip(bytes);
             const files = new Map(entries.map((e) => [e.name, e.data]));
             const frames = [...files.keys()].filter((k) => k.startsWith("SampleData/"));
             const xml = new TextDecoder().decode(files.get("Instrument.xml") || new Uint8Array());
             const first = frames[0] ? files.get(frames[0]) : null;
             let drawn = 0;
             if (first) {
               drawn = (first[0] === 0x52)
                 ? WT.parseWav(first).samples.length
                 : (await (async () => {
                     const ctx = new AudioContext();
                     const buf = await ctx.decodeAudioData(first.buffer.slice(0));
                     ctx.close();
                     return buf.length;
                   })());
             }
             return { frames: frames.length, macro: /WT Position/.test(xml),
                      sweep: /CustomDeviceName>SWEEP</.test(xml), drawn, size: bytes.length };
           }""",
        href,
    )
    check(parsed["frames"] == 12, "instrument holds 12 frames", f"{parsed['frames']} frames")
    check(parsed["macro"], "WT Position macro is mapped", f"sweep rig: {parsed['sweep']}")
    check(parsed["drawn"] > 100, "its first frame decodes", f"{parsed['drawn']} samples")


def test_library(page, base: str, errors: list[str]) -> None:
    page.goto(f"{base}/library.html", wait_until="load")
    page.wait_for_selector("tr[data-n]", timeout=40000)
    rows = page.eval_on_selector_all("tr[data-n]", "els => els.length")
    check(rows > 100, "library lists instruments", f"{rows} rows")

    page.click("tr[data-n]")
    page.wait_for_function(
        """() => {
             const t = document.getElementById('detailInfo').textContent;
             return t.includes('frames ·') || t.includes('could not read');
           }""",
        timeout=40000,
    )
    info = page.inner_text("#detailInfo").replace("\n", " ")
    check("frames ·" in info, "clicking a row fetches and draws it", info[:90])

    drawn = page.evaluate(
        """() => {
             const c = document.getElementById('detail');
             const ctx = c.getContext('2d');
             const d = ctx.getImageData(0, 0, c.width, c.height).data;
             let lit = 0;
             for (let i = 3; i < d.length; i += 4) if (d[i] > 0) lit++;
             return lit;
           }"""
    )
    check(drawn > 500, "the waveform is actually on the canvas", f"{drawn} painted pixels")

    page.select_option("#view", "category")
    page.wait_for_selector("[data-batch-cat]", timeout=20000)
    page.select_option("#cat", "Kaidiak")
    page.wait_for_function(
        "() => [...document.querySelectorAll('[data-batch-cat]')].some(b => b.textContent.includes('3'))",
        timeout=20000,
    )
    btn = page.query_selector("[data-batch-cat]")
    label = btn.inner_text().strip()
    check("download all 3" in label.lower(), "by category view offers a batch", label)
    btn.click()
    page.wait_for_function(
        "() => { const t = document.getElementById('status').textContent; return t.includes('wrote') || t.includes('failed'); }",
        timeout=90000,
    )
    status = page.inner_text("#status").strip()
    check(status.startswith("wrote"), "batch zip built in the browser", status[:90])


def test_selftest(page, base: str) -> None:
    page.goto(f"{base}/selftest.html", wait_until="load")
    page.wait_for_function("() => document.title.startsWith('SMOKE')", timeout=90000)
    text = page.inner_text("#out")
    fails = [l for l in text.splitlines() if l.startswith("FAIL")]
    check(not fails, "network smoke test inside the browser", page.title())
    for line in text.splitlines():
        print(f"        {line}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="test a deployed copy instead of the local one")
    ap.add_argument("--port", type=int, default=0, help="0 picks a free port")
    args = ap.parse_args()

    httpd = None
    if args.url:
        base = args.url.rstrip("/")
        print(f"checking {base}")
    else:
        httpd = serve(args.port)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        print(f"checking {base} (serving {DOCS})")

    errors: list[str] = []
    with sync_playwright() as p:
        # the system chromium where there is one, otherwise whatever playwright installed
        system = Path("/usr/bin/chromium")
        browser = p.chromium.launch(
            executable_path=str(system) if system.exists() else None,
            args=["--no-sandbox"],
        )
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        def note(msg):
            text = msg.text
            if "favicon" in text or "404" in text:   # missing favicon is not an app fault
                return
            errors.append(f"console.{msg.type}: {text}")

        page.on("console", lambda m: note(m) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        try:
            test_builder(page, base, errors)
            test_library(page, base, errors)
            test_selftest(page, base)
        finally:
            browser.close()
    if httpd:
        httpd.shutdown()

    check(not errors, "no console errors or exceptions",
          "" if not errors else "; ".join(errors[:3]))

    passed = sum(1 for ok, _, _ in results if ok)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
