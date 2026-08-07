# -*- coding: utf-8 -*-
"""合成英文配音演示视频：
逐镜帧 → 视频段（按旁白时长）→ 拼接 → 混入旁白音频 → 最终 MP4。
"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FF = r"C:\Users\Administrator\AppData\Local\Programs\Python\Python312\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
ROOT = "demo/frames"
NARR = "demo/narration"
OUT = "demo"
W, H = 1440, 860

# 镜头播放顺序（8 镜：新增 shot8 中英切换 + shot7 库外诚实）
ORDER = ["shot1", "shot2", "shot8", "shot3", "shot7", "shot4", "shot5", "shot6"]


def narr_dur(shot):
    """读旁白 mp3 实测时长（秒），视频段按此对齐，保证音画同步。"""
    mp3 = os.path.join(NARR, shot + ".mp3")
    r = subprocess.run([FF, "-i", mp3], capture_output=True, text=True)
    import re
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", r.stderr)
    if not m:
        return 12.0
    h, mm, s = m.groups()
    return int(h) * 3600 + int(mm) * 60 + float(s)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("FFMPEG ERR:", r.stderr[-800:])
        return False
    return True


def frames_of(shot):
    d = os.path.join(ROOT, shot)
    if not os.path.isdir(d):
        return []
    return [f for f in sorted(os.listdir(d)) if f.endswith(".png")]


def main():
    os.makedirs(OUT, exist_ok=True)
    shot_files = []

    # 1) 各镜编码为视频段（时长 = 旁白实测时长，fps 由帧数决定 → 音画同步）
    for shot in ORDER:
        frames = frames_of(shot)
        if not frames:
            print(f"skip {shot}: no frames"); continue
        n = len(frames)
        dur = narr_dur(shot)
        fps = n / dur if dur and dur > 0 else 1.0
        pat = os.path.join(ROOT, shot, "frame_%04d.png")
        outv = os.path.join(OUT, f"seg_{shot}.mp4")
        cmd = [FF, "-y", "-framerate", f"{fps:.4f}", "-i", pat,
               "-c:v", "libx264", "-preset", "fast", "-crf", "20",
               "-pix_fmt", "yuv420p", "-vf", f"scale={W}:{H}",
               "-r", "25", "-vsync", "cfr",   # 输出恒定 25fps → concat 时间戳正确
               "-an", outv]
        if run(cmd):
            shot_files.append((shot, outv, dur))
            print(f"  {shot}: {n} frames @ {fps:.2f}fps -> {dur}s")

    # 2) 拼接视频
    lst = os.path.join(OUT, "concat_video.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for _, outv, _ in shot_files:
            f.write(f"file '{os.path.abspath(outv)}'\n")
    full_v = os.path.join(OUT, "full_video.mp4")
    run([FF, "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", full_v])

    # 3) 拼接旁白（shot 间加 0.6s 静音）
    aud = os.path.join(OUT, "concat_audio.txt")
    with open(aud, "w", encoding="utf-8") as f:
        for s, _, _ in shot_files:
            f.write(f"file '{os.path.abspath(os.path.join(NARR, s + '.mp3'))}'\n")
            f.write("silence\n")   # ffmpeg concat 支持 'silence' 指令? 需用 filter
    # 用 filter_complex 在每段后加静音更稳
    inputs = []
    filter_parts = []
    for i, (s, _, _) in enumerate(shot_files):
        inputs += ["-i", os.path.join(NARR, s + ".mp3")]
        filter_parts.append(f"[{i}:a]")
    # 每段后接 0.6s 静音，再 concat
    chain = []
    for i in range(len(shot_files)):
        chain.append(filter_parts[i])
        if i < len(shot_files) - 1:
            chain.append(f"apad=pad_dur=0.6,atrim=0:999,asetpts=N/SR/TB")
    chain_spec = "".join(chain)
    # 简单方案：concat filter
    concat_filter = f"concat=n={len(shot_files)}:v=0:a=1[aout]"
    flt = ""
    for i in range(len(shot_files)):
        flt += f"[{i}:a]"
    flt += concat_filter
    full_a = os.path.join(OUT, "full_audio.m4a")
    cmd = [FF, "-y"] + inputs + ["-filter_complex", flt, "-map", "[aout]", "-c:a", "aac", full_a]
    if not run(cmd):
        print("audio concat failed, using raw concat")
        with open(aud, "w", encoding="utf-8") as f:
            for s, _, _ in shot_files:
                f.write(f"file '{os.path.abspath(os.path.join(NARR, s + '.mp3'))}'\n")
        run([FF, "-y", "-f", "concat", "-safe", "0", "-i", aud, "-c:a", "aac", full_a])

    # 4) 混音
    final = os.path.join(OUT, "private_rag_agent_demo_narrated.mp4")
    run([FF, "-y", "-i", full_v, "-i", full_a,
         "-c:v", "copy", "-c:a", "aac", "-shortest",
         "-movflags", "+faststart", final])
    print("FINAL:", final)


if __name__ == "__main__":
    main()
