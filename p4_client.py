# -*- coding: utf-8 -*-
"""P4 client: run p4 describe for each CL and parse changed files, submit time, and diff line info."""

import os
import re
import subprocess
import tempfile
import warnings
from typing import List, Optional, Tuple

# 用于解析 p4 describe 第一行的提交时间：Change 4875980 by user@client on 2026/03/04 21:20:36
_RE_CHANGE_ON = re.compile(r"Change\s+\d+\s+by\s+\S+\s+on\s+(.+)", re.I)
# 解析 diff 中的 @@ -old_start,old_count +new_start,new_count @@
_RE_DIFF_HUNK = re.compile(r"@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")
# 文本 diff 每个 hunk 最多展示的删/增行数（用于「修改内容」摘要）
_DIFF_SNIPPET_MAX_MINUS = 3
_DIFF_SNIPPET_MAX_PLUS = 3
_DIFF_LINE_MAX_LEN = 100
# 每个文件最多展示带内容的 hunk 数，超出只显示行号
_DIFF_HUNKS_WITH_SNIPPETS = 3

# xlsx/xlsm 单元格内容在摘要中显示的最大长度（避免单条过长；超出部分用 … 表示）
_EXCEL_CELL_DISPLAY_MAX = 120
# xlsx/xlsm 变更条数最多展示几条（超出则写「等共 N 处变更」）
_EXCEL_MAX_CHANGES_SHOW = 20

# 常见二进制/Office 扩展名：这些文件 P4 不会产生文本 diff，无法显示「第几行」变更
_BINARY_EXTENSIONS = frozenset(
    "xlsx xls doc docx ppt pptx pdf zip rar 7z png jpg jpeg gif bmp ico webp "
    "mp3 wav mp4 avi mov wmv dll so dylib exe bin".split()
)


def _no_diff_hint(depot_path: str, p4_marked_binary: bool = False) -> str:
    """对无行级 diff 的文件给出更易懂的说明（如 xlsx 等二进制）。"""
    ext = (depot_path.split(".")[-1].lower() if "." in depot_path else "").split("#")[0]
    if ext in _BINARY_EXTENSIONS:
        return "（二进制/Office 文件如 xlsx，无行级 diff，仅记录文件变更）"
    if p4_marked_binary:
        return "（P4 将该文件标为 binary，未输出文本 diff）"
    return "（未解析到行级 diff：可能 P4 标为 binary、或为空/集成变更、或编码异常）"


def _excel_change_summary(depot_path: str, new_rev: int, cwd: Optional[str] = None) -> Optional[str]:
    """
    对 xlsx/xlsm 用 p4 print 取新旧两版，用 openpyxl 比较单元格，返回可读的变更摘要。
    若未安装 openpyxl 或比较失败则返回 None。
    """
    try:
        import openpyxl
    except ImportError:
        return None
    if new_rev <= 1:
        return "（新文件，无旧版可对比）"
    old_rev = new_rev - 1
    spec_old = f"{depot_path}#{old_rev}"
    spec_new = f"{depot_path}#{new_rev}"
    cmd_old = ["p4", "print", "-q", spec_old]
    cmd_new = ["p4", "print", "-q", spec_new]
    try:
        r_old = subprocess.run(cmd_old, cwd=cwd, capture_output=True, timeout=30)
        r_new = subprocess.run(cmd_new, cwd=cwd, capture_output=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if r_old.returncode != 0 or r_new.returncode != 0:
        return None
    data_old = r_old.stdout
    data_new = r_new.stdout
    if not data_old or not data_new:
        return None
    suffix = ".xlsx" if depot_path.lower().endswith(".xlsx") else ".xlsm"
    changes = []
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f_old:
            f_old.write(data_old)
            path_old = f_old.name
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f_new:
            f_new.write(data_new)
            path_new = f_new.name
        try:
            # 抑制 openpyxl 对 WMF 等不支持图片格式的警告（我们只比较单元格数据，不依赖图片）
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                wb_old = openpyxl.load_workbook(path_old, data_only=True)
                wb_new = openpyxl.load_workbook(path_new, data_only=True)
            sheets_old = set(wb_old.sheetnames)
            sheets_new = set(wb_new.sheetnames)
            for name in sorted(sheets_new | sheets_old):
                if name not in sheets_old:
                    changes.append(f"【{name}】新增工作表")
                    continue
                if name not in sheets_new:
                    changes.append(f"【{name}】删除工作表")
                    continue
                ws_old = wb_old[name]
                ws_new = wb_new[name]
                cells_old = set()
                for row in ws_old.iter_rows():
                    for c in row:
                        cells_old.add((c.row, c.column))
                for row in ws_new.iter_rows():
                    for c in row:
                        coord = (c.row, c.column)
                        addr = openpyxl.utils.get_column_letter(c.column) + str(c.row)
                        new_val = c.value
                        if coord in cells_old:
                            old_val = ws_old.cell(c.row, c.column).value
                            if old_val != new_val:
                                max_len = _EXCEL_CELL_DISPLAY_MAX
                                old_s = "" if old_val is None else str(old_val)[:max_len]
                                new_s = "" if new_val is None else str(new_val)[:max_len]
                                if old_val is not None and len(str(old_val)) > max_len:
                                    old_s += "…"
                                if new_val is not None and len(str(new_val)) > max_len:
                                    new_s += "…"
                                changes.append(f"【{name}】{addr}: 「{old_s}」→「{new_s}」")
                        else:
                            max_len = _EXCEL_CELL_DISPLAY_MAX
                            new_s = "" if new_val is None else str(new_val)[:max_len]
                            if new_val is not None and len(str(new_val)) > max_len:
                                new_s += "…"
                            changes.append(f"【{name}】{addr}: 新增「{new_s}」")
        finally:
            try:
                os.unlink(path_old)
            except OSError:
                pass
            try:
                os.unlink(path_new)
            except OSError:
                pass
    except Exception:
        return None
    if not changes:
        return "（内容未变或无法解析）"
    parts = changes[:_EXCEL_MAX_CHANGES_SHOW]
    summary = "；".join(parts)
    if len(changes) > _EXCEL_MAX_CHANGES_SHOW:
        summary += f" 等共 {len(changes)} 处变更"
    return summary


def describe_cl(cl: int, cwd: Optional[str] = None) -> tuple[List[str], Optional[str]]:
    """
    Run `p4 describe -s <CL>` and return (list of depot paths, error_message).

    -s: short output, one line per file.
    """
    cmd = ["p4", "describe", "-s", str(cl)]
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except FileNotFoundError:
        return [], "未找到 p4 命令，请确保 Perforce 已在 PATH 中"
    except subprocess.TimeoutExpired:
        return [], f"p4 describe 超时: CL {cl}"

    out = result.stdout or ""
    err = result.stderr or ""
    if result.returncode != 0:
        return [], f"CL {cl}: p4 describe 失败 (returncode={result.returncode})\n{err[:300]}"

    # 解析 depot 路径。p4 describe -s 中文件行格式为: "... //FantasyWorld/.../file.cs#59 edit"
    # 不要跳过以 "..." 开头的行（那里才有真实路径）；只跳过纯 "..." 或 "Change ..." 等
    paths = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("Change ") or line == "...":
            continue
        # 提取该行中所有 // 开头的 depot 路径（到空格或 # 为止）
        for m in re.finditer(r"//[^\s#]+", line):
            p = m.group(0)
            if len(p) <= 2:
                continue
            # 排除描述里的 URL（如 [Jira] https://xindong.atlassian.net/... 被误匹配为 //xindong.atlassian.net/...）
            if ".atlassian.net" in p or "http" in p.lower():
                continue
            paths.append(p)
    return paths, None


def _parse_describe_full(out: str, cl: int) -> tuple[str, List[str], List[Tuple[str, str]], dict]:
    """
    解析 p4 describe（完整输出）：提交时间、文件路径列表、每个文件的变更行摘要、路径对应的 rev。
    Returns: (submit_time, paths, [(path, line_summary), ...], path_to_rev)
    """
    path_to_rev = {}  # path -> revision number (from #59 in "... //path/file.xlsx#59 edit")
    submit_time = ""
    paths = []
    file_line_summaries = []  # [(path, summary), ...]

    lines = out.splitlines()
    # 第一行：Change 4875980 by user@client on 2026/03/04 21:20:36
    for line in lines[:5]:
        m = _RE_CHANGE_ON.match(line.strip())
        if m:
            submit_time = m.group(1).strip()
            break

    current_path = None
    # list of (new_start, new_count, old_start, old_count, [(sign, text), ...])
    current_diffs: List[Tuple[int, int, int, int, List[Tuple[str, str]]]] = []
    current_section_has_binary = False  # P4 在该文件段落里输出了 (binary) 等

    def _truncate_line(s: str) -> str:
        s = (s or "").replace("\r", "").replace("\n", " ")
        return s[: _DIFF_LINE_MAX_LEN] + ("…" if len(s) > _DIFF_LINE_MAX_LEN else "")

    def flush_file():
        if not current_path:
            return
        if current_diffs:
            parts = []
            for idx, hunk in enumerate(current_diffs):
                ns, nc, os, oc = hunk[0], hunk[1], hunk[2], hunk[3]
                snippets = hunk[4] if len(hunk) > 4 else []
                line_info = f"第{ns}-{ns + nc - 1}行(+{nc}/-{oc})"
                if idx < _DIFF_HUNKS_WITH_SNIPPETS and snippets:
                    snip_strs = []
                    for sign, text in snippets:
                        t = _truncate_line(text)
                        snip_strs.append(f"{sign}{t}")
                    parts.append(line_info + ": " + " ".join(snip_strs))
                else:
                    parts.append(line_info)
            file_line_summaries.append(
                (current_path, "；".join(parts[:5]) + (" 等" if len(parts) > 5 else ""))
            )
        else:
            file_line_summaries.append((current_path, _no_diff_hint(current_path, current_section_has_binary)))

    def _is_new_file_line(ln: str) -> bool:
        s = ln.strip()
        if "..." not in s[:10]:
            return False
        return bool(re.search(r"//[^\s#]+", s) and ".atlassian.net" not in s and "http" not in s.lower())

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # 文件行: "... //depot/.../file#rev action"
        path_match = re.search(r"//[^\s#]+", stripped)
        if path_match and "..." in stripped[:10] and ".atlassian.net" not in stripped and "http" not in stripped.lower():
            p = path_match.group(0)
            if len(p) > 2:
                flush_file()
                paths.append(p)
                rev_m = re.search(r"#(\d+)", stripped)
                if rev_m:
                    path_to_rev[p] = int(rev_m.group(1))
                current_path = p
                current_diffs = []
                current_section_has_binary = False
        # P4 对 binary 文件会输出 (binary) 或 binary file，不输出 @@ diff
        if current_path and "binary" in stripped.lower():
            current_section_has_binary = True
        # diff 块 @@ -a,b +c,d @@，并收集后续 -/+ 行作为修改内容
        mm = _RE_DIFF_HUNK.search(stripped)
        if mm and current_path:
            old_start = int(mm.group(1))
            old_count = int(mm.group(2) or 1)
            new_start = int(mm.group(3))
            new_count = int(mm.group(4) or 1)
            snippets: List[Tuple[str, str]] = []
            j = i + 1
            n_minus, n_plus = 0, 0
            while j < len(lines):
                next_ln = lines[j]
                next_s = next_ln.strip()
                if _RE_DIFF_HUNK.search(next_s) or _is_new_file_line(next_ln):
                    break
                if next_ln.startswith("-") and not next_ln.startswith("---") and n_minus < _DIFF_SNIPPET_MAX_MINUS:
                    snippets.append(("-", next_ln[1:].strip()))
                    n_minus += 1
                elif next_ln.startswith("+") and not next_ln.startswith("+++") and n_plus < _DIFF_SNIPPET_MAX_PLUS:
                    snippets.append(("+", next_ln[1:].strip()))
                    n_plus += 1
                j += 1
            current_diffs.append((new_start, new_count, old_start, old_count, snippets))
            i = j - 1  # 已读取到 j，下一轮 i+1 会从 j 开始（下一段 @@ 或 path）
        i += 1
    flush_file()

    for p in paths:
        if not any(fp == p for fp, _ in file_line_summaries):
            file_line_summaries.append((p, _no_diff_hint(p, False)))
    return submit_time, paths, file_line_summaries, path_to_rev


def describe_cl_full(cl: int, cwd: Optional[str] = None) -> tuple[str, List[str], List[Tuple[str, str]], Optional[str]]:
    """
    执行 p4 describe <CL>（完整，非 -s），解析提交时间、文件列表、每个文件的变更行摘要。
    Returns: (submit_time, paths, [(path, line_summary)], error_message)
    """
    cmd = ["p4", "describe", str(cl)]
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except FileNotFoundError:
        return "", [], [], "未找到 p4 命令"
    except subprocess.TimeoutExpired:
        return "", [], [], f"p4 describe 超时: CL {cl}"

    out = result.stdout or ""
    err = result.stderr or ""
    if result.returncode != 0:
        return "", [], [], f"CL {cl}: p4 describe 失败\n{err[:200]}"

    try:
        submit_time, paths, file_line_summaries, path_to_rev = _parse_describe_full(out, cl)
    except Exception:
        # 解析失败时退化为只取路径（用 -s 结果）
        paths_short, _ = describe_cl(cl, cwd=cwd)
        return "", paths_short, [(p, "（解析失败）") for p in paths_short], None
    # 对 xlsx/xlsm 尝试用 openpyxl 生成单元格级变更摘要
    excel_ext = frozenset(("xlsx", "xlsm"))
    result_summaries = []
    for path, summary in file_line_summaries:
        ext = (path.split(".")[-1].lower() if "." in path else "").split("#")[0]
        if ext in excel_ext and summary == _no_diff_hint(path):
            rev = path_to_rev.get(path)
            if rev:
                excel_sum = _excel_change_summary(path, rev, cwd=cwd)
                if excel_sum:
                    summary = excel_sum
        result_summaries.append((path, summary))
    return submit_time, paths, result_summaries, None


def get_changed_files_for_cls(
    cl_list: List[int],
    cwd: Optional[str] = None,
) -> Tuple[List[Tuple[int, List[str], str, List[Tuple[str, str]]]], List[int], List[str]]:
    """
    For each CL, run p4 describe (full) and collect paths, submit time, and per-file line change summary.

    Returns:
        (files_by_cl, failed_cls, error_messages)
        - files_by_cl: list of (cl, paths, submit_time, file_line_summaries)
          file_line_summaries: list of (depot_path, line_summary_str)
        - failed_cls: list of CL numbers that failed
        - error_messages: list of error strings for failed CLs
    """
    files_by_cl = []
    failed_cls = []
    errors = []

    for cl in cl_list:
        submit_time, paths, file_line_summaries, err = describe_cl_full(cl, cwd=cwd)
        if err:
            failed_cls.append(cl)
            errors.append(err)
        else:
            files_by_cl.append((cl, paths, submit_time, file_line_summaries))

    return files_by_cl, failed_cls, errors


def _common_depot_prefix(paths: List[str]) -> str:
    """计算 depot 路径列表的最长公共前缀（按路径段）。"""
    if not paths:
        return ""
    cleaned = [p.strip() for p in paths if (p or "").strip()]
    if not cleaned:
        return ""
    segments_list = [p.split("/") for p in cleaned]
    common = []
    for i in range(min(len(s) for s in segments_list)):
        seg = segments_list[0][i]
        if all(s[i] == seg for s in segments_list):
            common.append(seg)
        else:
            break
    return "/".join(common) if common else ""


# 项目上下文：列举的目录/文件数量上限
_PROJECT_CONTEXT_MAX_DIRS = 80
_PROJECT_CONTEXT_MAX_FILES = 250


def get_project_context(depot_paths: List[str], cwd: Optional[str] = None) -> str:
    """
    根据变更涉及的 depot 路径，查询该区域的项目结构（子目录 + 文件示例），
    供 AI 结合「项目全貌」给出更全面的测试范围建议。

    Returns:
        一段可读的「项目结构」摘要；查询失败或路径为空则返回空字符串。
    """
    if not depot_paths:
        return ""
    prefix = _common_depot_prefix(depot_paths)
    if not prefix or prefix.count("/") < 2:
        return ""
    # 避免范围过大：至少取到变更路径的父级（如 //depot/Proj/Module）
    parts = prefix.split("/")
    if len(parts) <= 2:
        return ""

    lines = [f"项目 depot 区域（与本次变更相关）：{prefix}", ""]
    # 子目录：p4 dirs prefix/*
    spec_dirs = f"{prefix}/*"
    try:
        r = subprocess.run(
            ["p4", "dirs", spec_dirs],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if r.returncode == 0 and (r.stdout or "").strip():
            dirs = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()][:_PROJECT_CONTEXT_MAX_DIRS]
            if dirs:
                lines.append("直接子目录：")
                for d in dirs:
                    short = d.split("/")[-1] if "/" in d else d
                    lines.append(f"  - {short}")
                lines.append("")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # 文件示例：p4 files prefix/...
    spec_files = f"{prefix}/..."
    try:
        r = subprocess.run(
            ["p4", "files", "-m", str(_PROJECT_CONTEXT_MAX_FILES), spec_files],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        if r.returncode == 0 and (r.stdout or "").strip():
            file_lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
            if file_lines:
                lines.append("该区域文件示例（用于了解模块与类型）：")
                for ln in file_lines[: _PROJECT_CONTEXT_MAX_FILES]:
                    # p4 files 输出形如：//depot/path#rev - action
                    path = ln.split("#")[0].strip().split("-")[0].strip()
                    if path:
                        lines.append(f"  {path}")
                if len(file_lines) > _PROJECT_CONTEXT_MAX_FILES:
                    lines.append(f"  ... 共约 {len(file_lines)} 个文件（已截断）")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "\n".join(lines).strip() if len(lines) > 1 else ""
